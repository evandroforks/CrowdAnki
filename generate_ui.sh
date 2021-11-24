#!/usr/bin/env bash

echo "Generating UI Files"

pyuic5 ui_files/config.ui -o config/config_ui.py
pyuic5 ui_files/import.ui -o importer/import_ui.py
