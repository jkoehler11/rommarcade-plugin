# RomMArcade plugin for RomM

Adds **Play in RomMArcade** to RomM's Play menu, and a **RomMArcade** entry to
the Settings navigation. Pressing Play opens

```
rommarcade://open?rom=428&platform=ngc&name=Luigi%27s%20Mansion&play=1
```

which the machine running [RomMArcade](https://github.com/jkoehler11/RomMArcade)
turns into "install this game if it isn't there, then start it". Clear the
`play=1` parameter and the same button only opens the game's page.

This repository is a manifest and a URL handler. RomM reads `plugin.json`, draws
the button and opens the URL; nothing runs on the RomM server, and adding or
removing the plugin needs no restart.

## What it needs

| On the RomM host | On the machine you play on |
| --- | --- |
| RomM 5.x with the plugin shelf, which today means [ROMulus](https://github.com/jkoehler11/ROMulus). A stock RomM release answers 404 on `GET /api/plugins` and has nowhere to install this. | [RomMArcade](https://github.com/jkoehler11/RomMArcade), from its releases page or `packaging/install.sh` |
| | EmuDeck, which owns the ROM folders, the launchers and the emulators RomMArcade drives |

The plugin is optional. RomMArcade works without it; the plugin only puts its
button where you already press Play.

## Install the plugin

In RomM, open **Settings → Plugins → Add plugin** and paste this address into the
URL field. The server fetches and validates it.

```
https://raw.githubusercontent.com/jkoehler11/rommarcade-plugin/main/plugin.json
```

Or by hand: drop this folder into the plugins directory and mount that directory
into the container.

```yaml
volumes:
  - ./plugins:/romm/plugins
```

## Register the handler

The URL means nothing until the machine running RomMArcade knows the scheme. On
Linux this repository carries the handler for that:

```bash
./desktop/install.sh
xdg-mime query default x-scheme-handler/rommarcade   # must print rommarcade-url.desktop
```

It installs `rommarcade-open` in `~/.local/bin`, adds a hidden desktop entry that
claims `x-scheme-handler/rommarcade`, and makes that entry the default. An
install made with RomMArcade's own `packaging/install.sh` already registers a
handler; run this one after the release bundle, or when the app was unpacked by
hand.

What the handler does, in order, so a press always lands somewhere:

1. Finds the copy that is already serving (the port in `desktop-port`, then the
   configured port, then 8790) and posts the game to `POST /api/deeplink`. The
   service keeps one pending target and hands it out once, so a page reload does
   not navigate again.
2. Starts the desktop app when nothing answers, waits for its service, then posts
   the same target.
3. Opens the web UI in the browser as a last resort.

Every step is appended to `~/.local/state/rommarcade-open.log`, which is the file
to read when a press appears to do nothing.

The macOS and Windows builds do not claim the scheme yet, so the button there
opens nothing until the OS has a handler for `rommarcade://`.

## Settings

RomM renders these as a form on **Settings → Plugins**. They reach the link as
`{setting.<key>}`, so they change what the button does rather than only being
displayed.

| Setting | What it changes |
| --- | --- |
| `enabled` | Off hides the Play entry (`enabled_by`); RomM's own Play stays as it was. |
| `extra_query` | Appended to the hand-over URL. The default, `&play=1`, makes RomMArcade install the game and then start it; clearing it only opens the game. |
| `web_url` | The address the **RomMArcade** entry in Settings navigation opens, for a machine where the `rommarcade://` handler is not registered. |

## Where the button appears

`slot` decides which surface an action lands on:

| Value | Where it lands |
| --- | --- |
| `game.play` | A way to start the game, inside Play. The Play action uses it. |
| `game.details` | A button in the game's action row. |
| `app.nav` | A link in the Settings navigation. The RomMArcade shortcut uses it. |
| `settings.page` | A row on Settings → Plugins. |

When RomMArcade is the only way to start a game, Play opens it straight away.
When RomM can also play the game in the browser, Play asks which target to use,
with RomM's own player listed first.

## Offer it only where RomMArcade can play

RomMArcade installs and launches through EmuDeck, so a button on a platform that
machine has not mapped is a dead end. Name the platforms on the Play action and
it appears only on their games:

```json
"platforms": ["ngc", "wii"]
```

Matched against both of a platform's slugs, so `gc` also finds `ngc`. Leave
`platforms` out to offer the button on every game, which is what this manifest
does: the mapping lives on each machine, and RomMArcade itself says which
emulator is missing when a press cannot be served.

## What it does not do

- It does not install emulators. RomMArcade installs and launches through
  EmuDeck, and names the emulator to add when one is missing.
- It does not run anything on the RomM server, and it does not download on it.
  The game lands on the machine running RomMArcade.
- It does not register the scheme for you outside Linux; see above.

## Files

| Path | What it is |
| --- | --- |
| `plugin.json` | The manifest RomM reads and validates, and the file the install URL points at. |
| `desktop/rommarcade-open` | The `rommarcade://` handler: finds or starts RomMArcade, then hands it the game. Python 3, standard library only. |
| `desktop/rommarcade-url.desktop.example` | The desktop entry that claims the scheme. `install.sh` fills in the binary path. |
| `desktop/install.sh` | Installs the handler and the entry for the current user; `--uninstall` removes them. |

## License

MIT. RomM, ROMulus, RomMArcade and EmuDeck remain their authors' work.
