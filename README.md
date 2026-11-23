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

The URL means nothing until the machine running RommDeck knows the scheme. On
Linux, a `.desktop` entry with `MimeType=x-scheme-handler/rommdeck` that runs
`rommdeck-open %u`, registered with `xdg-mime default`, is enough; the script
receives the URL on the command line and opens RommDeck. On Windows, a registry
entry under `HKEY_CLASSES_ROOT\rommdeck` does the same.

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
