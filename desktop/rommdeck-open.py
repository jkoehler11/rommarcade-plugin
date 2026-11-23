#!/usr/bin/env python3
"""Open RommDeck for a game URL handed over by RomM's plugin button.

RomM's plugin points its "Open in RommDeck" button at a URL like

    rommdeck://open?rom=428&platform=ngc&name=Luigi%27s%20Mansion

and this is what the desktop registers for the `rommdeck` scheme. RommDeck has
no deep link of its own, so the app is brought up (or forwarded to, since a
second launch asks the running copy to come forward) and the request is logged
for whatever comes next.

Nothing here blocks the browser: the app is started detached and the URL is
appended to a log.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
LOG = HOME / ".local" / "state" / "rommdeck-open.log"
APP = HOME / ".local" / "share" / "rommdeck" / "rommdeck"
WEB_UI = "http://127.0.0.1:8780"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def session_env() -> dict[str, str]:
    """The variables a GUI app needs that a URL handler may not inherit."""
    env = dict(os.environ)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    if not env.get("WAYLAND_DISPLAY"):
        for candidate in sorted(Path(runtime).glob("wayland-*")):
            if not candidate.name.endswith(".lock"):
                env["WAYLAND_DISPLAY"] = candidate.name
                break
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    return env


def spawn(argv: list[str]) -> bool:
    try:
        subprocess.Popen(
            argv,
            env=session_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log(f"could not start {argv[0]}: {exc}")
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        log("called without a URL")
        return 2

    url = argv[1]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    game = query.get("name", [""])[0]
    rom_id = query.get("rom", [""])[0]
    log(f"{url} rom={rom_id or '?'} name={game or '?'}")

    if APP.exists():
        # A second launch asks the running copy to come forward, so this also
        # works when RommDeck is already open.
        return 0 if spawn([str(APP)]) else 1

    if shutil.which("xdg-open"):
        return 0 if spawn(["xdg-open", WEB_UI]) else 1

    log("RommDeck not found and xdg-open is missing")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
