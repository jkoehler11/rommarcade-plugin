# RommDeck plugin for RomM

Adds **Open in RommDeck** to RomM's Play chooser for every game the browser
cannot start. Pressing it opens

```
rommdeck://open?rom=<id>&platform=<slug>&name=<title>
```

which a handler on the machine running [RommDeck](https://github.com/s0liton/RommDeck)
turns into "open RommDeck".

This repository is only a manifest. It ships no server code and no assets that
RomM executes: RomM reads `plugin.json`, draws the action, and opens the URL.

## Install

In RomM, go to **Settings → Plugins → Add plugin**.

- **From this repository:** paste
  `https://raw.githubusercontent.com/jkoehler11/rommdeck-plugin/main/plugin.json`
  into the URL field. The server fetches and validates it.
- **By hand:** drop this folder into the plugins directory and mount that
  directory into the container.

```yaml
volumes:
  - ./plugins:/romm/plugins
```

## Register the handler

The URL means nothing until the machine running RommDeck knows the scheme. This
repository carries the handler for Linux: `rommdeck-open` (a small Python
script) plus a `.desktop` entry that claims the scheme.

```bash
install -m755 rommdeck-open ~/.local/bin/rommdeck-open
sed "s/USER/$USER/" rommdeck-url.desktop.example > ~/.local/share/applications/rommdeck-url.desktop
update-desktop-database ~/.local/share/applications
xdg-mime default rommdeck-url.desktop x-scheme-handler/rommdeck
xdg-mime query default x-scheme-handler/rommdeck   # must echo rommdeck-url.desktop
```

The handler asks the copy of RommDeck that is already serving to open the game
(`POST /api/deeplink` on its local API), and otherwise starts RommDeck with the
URL on its command line. Either way the UI lands on that game: the Library tab,
its platform, and the game's own button pressed, so a game that isn't on the
machine yet starts downloading. A game that is already there keeps its History
and Remove buttons untouched.

That deep link is a RommDeck feature; on a release without it the URL only
brings the app up. On Windows, a registry entry under
`HKEY_CLASSES_ROOT\rommdeck` that runs the app with `%1` does the same, once
RommDeck reads the argument.

## Settings

The manifest declares three settings, which RomM renders as a form on
**Settings → Plugins** and stores beside the manifest. They reach the URL as
`{setting.<key>}`, so they change what the button does rather than only being
displayed:

| Setting | What it changes |
| --- | --- |
| `enabled` | Off hides the button entirely (`enabled_by`); RomM's own Play stays as it was. |
| `extra_query` | Appended to the hand-over URL — `&play=1` makes RommDeck download the game and play it, and clearing it only opens the game. |
| `web_url` | The address the **RommDeck** entry in Settings → navigation points at, for a machine where the `rommdeck://` handler isn't registered. |

## Choose where the button appears

`slot` decides which surface the action lands on:

| Value | Where it lands |
| --- | --- |
| `game.play` | A way to start the game, inside Play. This file uses it. |
| `game.details` | A button in the game's action row. |
| `app.nav` | A link in the Settings navigation. |
| `settings.page` | A row on Settings → Plugins. |

## Offer it only where RommDeck can play

RommDeck launches whatever emulators that machine has mapped, so a button on a
platform it cannot run is a dead end. Name those platforms on the action and it
appears only on their games:

```json
"platforms": ["ngc", "wii"]
```

Leave `platforms` out to offer it on every game, which is what this manifest
does.
