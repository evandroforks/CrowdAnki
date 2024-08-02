import json
import os

import shutil
from pathlib import Path
from typing import Callable


from .deck_exporter import DeckExporter
from ..anki.adapters.anki_deck import AnkiDeck
from ..representation import deck_initializer
from ..representation.deck import Deck
from ..utils.constants import DECK_FILE_NAME, DECK_FILE_EXTENSION, MEDIA_SUBDIRECTORY_NAME
from ..utils.filesystem.name_sanitizer import sanitize_anki_deck_name
from .note_sorter import NoteSorter
from ..config.config_settings import ConfigSettings



import sys
import timeit
import subprocess
import multiprocessing.shared_memory
import datetime

g_start_time = timeit.default_timer()


def print_time(start=None):
    global g_start_time
    start = g_start_time if start is None else start
    end = timeit.default_timer()
    g_start_time = end
    return str(datetime.timedelta(seconds=end-start))[:-4]


def get_time():
    return str(datetime.datetime.now())[:-4]


class AnkiJsonExporter(DeckExporter):
    def __init__(self, collection,
                 config: ConfigSettings,
                 deck_name_sanitizer: Callable[[str], str] = sanitize_anki_deck_name,
                 deck_file_name: str = DECK_FILE_NAME):
        self.config = config
        self.collection = collection
        self.last_exported_count = 0
        self.deck_name_sanitizer = deck_name_sanitizer
        self.deck_file_name = deck_file_name
        self.note_sorter = NoteSorter(config)

    def export_to_directory(self, deck: AnkiDeck, output_dir=Path("."), copy_media=True, create_deck_subdirectory=True) -> Path:
        deck_name = deck.name
        deck_directory = output_dir
        if create_deck_subdirectory:
            deck_directory = output_dir.joinpath(self.deck_name_sanitizer(deck.name))
            deck_directory.mkdir(parents=True, exist_ok=True)

        deck = deck_initializer.from_collection(self.collection, deck.name)

        self.note_sorter.sort_deck(deck)

        self.last_exported_count = deck.get_note_count()

        deck_filename_yaml = deck_directory.joinpath(self.deck_file_name).with_suffix('.yml')
        print(f"{get_time()} {print_time()} Starting json read for {deck_filename_yaml}")
        deck_json = json.dumps(deck,
           default=Deck.default_json,
           sort_keys=True,
           indent=4,
           ensure_ascii=False)

        deck_json_bin = deck_json.encode("utf-8")
        filesize = len(deck_json_bin)
        shared_mem = multiprocessing.shared_memory.SharedMemory(name='MyMemoryAnkiExporterDeckJsonStr', size=filesize, create=True)
        shared_mem.buf[:filesize] = deck_json_bin

        print(f"{get_time()} {print_time()} Starting yaml dump")
        python_script = fr"""\
import os
import sys
import json
import tempfile
import multiprocessing.shared_memory
import warnings
import datetime

import ruamel.yaml as yaml
warnings.simplefilter('ignore', PendingDeprecationWarning)

shared_mem = multiprocessing.shared_memory.SharedMemory(name='MyMemoryAnkiExporterDeckJsonStr', create=False)

def get_time():
    return str(datetime.datetime.now())[:-4]

with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            dir=r"{str(deck_directory)}",
            suffix=".ignore",
            newline='\n',
            encoding='utf8',
        ) as temporaryfile:
    jsonobject = json.loads(bytes(shared_mem.buf[:{filesize}]).decode("utf-8"))
    print(fr"{{get_time()}} Converting to yml", file=sys.stderr)
    yaml.dump(jsonobject, temporaryfile, default_flow_style=False, default_style='|', allow_unicode=True)
    temporaryfile.close()  # atomic write for safety
    os.replace(temporaryfile.name, r"{str(deck_filename_yaml)}")
"""
        # C:\\Python\\python.exe -m pip install ruamel.yaml==0.17.32
        with subprocess.Popen([
                "C:\\Python\\python.exe",
                # "F:\\Python\\python.exe",
                "-u",
                "-c",
                python_script
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=os.environ,
        ) as process:
            # https://stackoverflow.com/questions/18421757/live-output-from-subprocess-command
            # https://stackoverflow.com/questions/1606795/catching-stdout-in-realtime-from-subprocess
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.decode("UTF-8", errors='replace')
                line = line.replace('\r\n', '\n').rstrip(' \n\r')
                print(line)

        if process.returncode != 0:
            print(f"Error: non zero exit code: {process.returncode}, for {python_script}", file=sys.stderr)

        print(f"{get_time()} {print_time()} Starting json dump")
        deck_filename = deck_directory.joinpath(self.deck_file_name).with_suffix(DECK_FILE_EXTENSION)
        with deck_filename.open(mode='w', encoding="utf8") as deck_file:
            deck_file.write(deck_json)

        self._save_changes(deck)

        if copy_media:
            self._copy_media(deck, deck_directory)

        return deck_directory

    def _save_changes(self, deck, is_export_child=False):
        """Save updates that were made during the export. E.g. UUID fields

        It saves decks, deck configurations and models.

        is_export_child refers to whether this deck is a child for the
        _purposes of the current export operation_.  For instance, if
        we're exporting or snapshotting a specific subdeck, then it's
        considered the "parent" here.  We need the argument to avoid
        duplicately saving deck configs and note models.

        """

        self.collection.decks.save(deck.anki_dict)
        for child_deck in deck.children:
            self._save_changes(child_deck, is_export_child=True)

        if not is_export_child:
            for deck_config in deck.metadata.deck_configs.values():
                self.collection.decks.save(deck_config.anki_dict)

            for model in deck.metadata.models.values():
                self.collection.models.save(model.anki_dict)

        # Notes?

    def _copy_media(self, deck, deck_directory):
        media_directory = deck_directory.joinpath(MEDIA_SUBDIRECTORY_NAME)

        shutil.rmtree(str(media_directory.resolve()), ignore_errors=True)
        media_directory.mkdir(parents=True, exist_ok=True)

        for file_src in deck.get_media_file_list():
            try:
                shutil.copy(os.path.join(self.collection.media.dir(), file_src),
                            str(media_directory.resolve()))
            except IOError as ioerror:
                print("Failed to copy a file {}. Full error: {}".format(file_src, ioerror))
