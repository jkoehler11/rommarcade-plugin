#!/bin/sh
# Register the rommarcade:// handler for the current user (Linux).
#
# RomMArcade's own packaging/install.sh already writes a small handler and a
# desktop entry. This one is for the release bundle, which installs the app
# without claiming the scheme, and it replaces that small handler with one that
# also starts the desktop app and reads the port it actually bound.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR=${ROMARCADE_BIN_DIR:-"$HOME/.local/bin"}
APPS_DIR=${XDG_DATA_HOME:-"$HOME/.local/share"}/applications
ENTRY="$APPS_DIR/rommarcade-url.desktop"

refresh_desktop_database() {
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  fi
}

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$BIN_DIR/rommarcade-open" "$ENTRY"
  refresh_desktop_database
  echo "Removed the rommarcade:// handler and its desktop entry."
  exit 0
fi

install -d "$BIN_DIR" "$APPS_DIR"
install -m 755 "$HERE/rommarcade-open" "$BIN_DIR/rommarcade-open"
sed "s|__BIN__|$BIN_DIR|g" "$HERE/rommarcade-url.desktop.example" > "$ENTRY"
chmod 644 "$ENTRY"
refresh_desktop_database

echo "Handler: $BIN_DIR/rommarcade-open"
echo "Entry:   $ENTRY"

if command -v xdg-mime >/dev/null 2>&1; then
  if xdg-mime default rommarcade-url.desktop x-scheme-handler/rommarcade; then
    echo "Scheme:  $(xdg-mime query default x-scheme-handler/rommarcade)"
  else
    echo "xdg-mime could not set the default. Run this from a desktop session:"
    echo "  xdg-mime default rommarcade-url.desktop x-scheme-handler/rommarcade"
  fi
else
  echo "xdg-mime is missing; install xdg-utils and set the default by hand."
fi

echo
echo "Send a link to a game with:"
echo "  $BIN_DIR/rommarcade-open 'rommarcade://open?rom=1&name=Test'"
