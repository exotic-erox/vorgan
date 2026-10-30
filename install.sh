#!/usr/bin/env bash
# Vorgan installer for Arch Linux (fish). Safe to run again to update.
set -e
cd "$(dirname "$0")"
need() { command -v "$1" >/dev/null 2>&1; }
if ! need bsdtar; then echo "Installing libarchive (archive support)..."; sudo pacman -S --needed libarchive; fi
if ! need pipx;  then echo "Installing pipx...";                      sudo pacman -S --needed python-pipx; fi
pipx install --force .
mkdir -p "$HOME/.config/fish/functions"
cp shell/vg.fish "$HOME/.config/fish/functions/vg.fish"
echo
echo "Done. Open a new fish shell and run:  vg"
echo "(q quits and drops your shell into the folder you ended in, Q quits without moving)"
