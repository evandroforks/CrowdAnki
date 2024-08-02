from dataclasses import field, dataclass
from pathlib import Path
from typing import Any

from .anki_deck_archiver import AnkiDeckArchiver
from .archiver import AllDeckArchiver
from .dulwich_repo import DulwichAnkiRepo
from ..anki.adapters.deck_manager import AnkiStaticDeckManager, DeckManager
from ..anki.ui.utils import progress_indicator
from ..config.config_settings import ConfigSettings
from ..export.anki_exporter import AnkiJsonExporter
from ..utils.notifier import Notifier, AnkiTooltipNotifier
from ..utils.disambiguate_uuids import disambiguate_note_model_uuids


@dataclass
class ArchiverVendor:
    window: Any
    config: ConfigSettings
    notifier: Notifier = field(default_factory=AnkiTooltipNotifier)

    @property
    def deck_manager(self) -> DeckManager:
        return AnkiStaticDeckManager(self.window.col.decks)

    def all_deck_archiver(self):
        return AllDeckArchiver(
            self.deck_manager,
            lambda deck: AnkiDeckArchiver(deck,
                                          self.config.full_snapshot_path,
                                          AnkiJsonExporter(self.window.col, self.config),
                                          DulwichAnkiRepo))

    def snapshot_path(self):
        return Path(self.config.snapshot_path)

    def do_manual_snapshot(self):
        self.do_snapshot('CrowdAnki: Manual snapshot')

    def snapshot_on_sync(self):
        if self.config.automated_snapshot:
            self.do_snapshot('CrowdAnki: Snapshot on sync')

    def do_snapshot(self, reason):
        # Clean up duplicate note models. See
        # https://github.com/Stvad/CrowdAnki/wiki/Workarounds-%E2%80%94-Duplicate-note-model-uuids.
        disambiguate_note_model_uuids(self.window.col)

        with progress_indicator(self.window, 'Taking CrowdAnki snapshot of all decks'):
            import timeit
            import datetime
            from ..export.anki_exporter import print_time, get_time
            start = timeit.default_timer()
            print(f"{get_time()} {print_time()} Starting snapshot for {self.config.full_snapshot_path}...")
            self.all_deck_archiver().archive(overrides=self.overrides(),
                                             reason=reason)
            print(f"{get_time()} {print_time(start)} Finished snapshot for {self.config.full_snapshot_path}...")
            self.notifier.info(f"Snapshot successful after {print_time(start)}, ",
                               f"The CrowdAnki snapshot to {str(self.config.full_snapshot_path)} successfully completed")

    def overrides(self):
        return self.deck_manager.for_names(self.config.snapshot_root_decks)
