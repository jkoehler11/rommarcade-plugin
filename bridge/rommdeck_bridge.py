#!/usr/bin/env python3
"""rommdeck-bridge — hands a RomM game to the machine RommDeck manages.

RomM's frontend (UI v2, shipped since 5.4) feature-detects `window.rommNative`
and, when it is present, offers "Play in {emulator}" on every game it can hand
to a locally installed emulator. That bridge is normally injected by RomM's
Electron desktop shell. This service is the back end for a browser-side
implementation of the same contract: the extension defines `window.rommNative`,
and every call it makes lands here.

It knows what RommDeck knows — the RomM pairing token, which platforms are
mapped to which emulator, and which ROM directory each one downloads into — and
it does the two things RommDeck does not: wait for a download and start the
emulator.

Stdlib only, no third-party imports: it runs inside the user's session as a
systemd unit next to romm-sync.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
USER_AGENT = f"rommdeck-bridge/{VERSION}"

HOME = Path(os.path.expanduser("~"))
DATA = HOME / ".local" / "share"
CONF = HOME / ".config"
STATE = HOME / ".local" / "state" / "rommdeck-bridge"
ROMMDECK_CONFIG = DATA / "romm-sync" / "config.json"
BRIDGE_CONFIG = CONF / "rommdeck-bridge" / "config.json"
LOG = STATE / "bridge.log"

MAX_BODY = 64 * 1024
DOWNLOAD_TIMEOUT = 60 * 30


# ── logging ──────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ── configuration ────────────────────────────────────────────────────────────


@dataclass
class BridgeConfig:
    """Everything the bridge needs that is not RommDeck's own config."""

    port: int = 8781
    bind: str = "0.0.0.0"
    # emulator id (RommDeck's own name) -> command template. `{rom}` is the
    # file that was downloaded, `{rom_dir}` its directory.
    emulators: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "BridgeConfig":
        cfg = cls()
        if BRIDGE_CONFIG.exists():
            try:
                raw = json.loads(BRIDGE_CONFIG.read_text(encoding="utf-8"))
                if isinstance(raw.get("port"), int):
                    cfg.port = raw["port"]
                if isinstance(raw.get("bind"), str):
                    cfg.bind = raw["bind"]
                if isinstance(raw.get("emulators"), dict):
                    cfg.emulators = raw["emulators"]
            except (OSError, ValueError) as exc:
                log(f"config: ignoring unreadable {BRIDGE_CONFIG}: {exc}")
        return cfg

    def emulator(self, emu_id: str) -> dict[str, Any] | None:
        """The command for an emulator id, or a built-in preset for it."""
        if emu_id in self.emulators:
            return self.emulators[emu_id]
        return PRESETS.get(emu_id)


# Resolved at call time, since a preset's first existing candidate wins.
PRESETS: dict[str, dict[str, Any]] = {
    "dolphin": {
        "name": "Dolphin",
        "command": ["{bin}", "--batch", "--exec={rom}"],
        "bins": ["/usr/bin/dolphin-emu", "dolphin-emu", "dolphin-emu-nogui"],
        "flatpak": "org.DolphinEmu.dolphin-emu",
    },
    "retroarch": {
        "name": "RetroArch",
        "command": ["{bin}", "{rom}"],
        "bins": ["/usr/bin/retroarch", "retroarch"],
        "flatpak": "org.libretro.RetroArch",
    },
    "duckstation": {
        "name": "DuckStation",
        "command": ["{bin}", "-batch", "{rom}"],
        "bins": ["/usr/bin/duckstation-qt", "duckstation-qt", "duckstation"],
        "flatpak": "org.duckstation.DuckStation",
    },
    "pcsx2": {
        "name": "PCSX2",
        "command": ["{bin}", "-batch", "-fullscreen", "{rom}"],
        "bins": ["/usr/bin/pcsx2-qt", "pcsx2-qt", "pcsx2"],
        "flatpak": "net.pcsx2.PCSX2",
    },
    "ppsspp": {
        "name": "PPSSPP",
        "command": ["{bin}", "--fullscreen", "{rom}"],
        "bins": ["/usr/bin/ppsspp-qt", "ppsspp-qt", "ppsspp"],
        "flatpak": "org.ppsspp.PPSSPP",
    },
    "mgba": {
        "name": "mGBA",
        "command": ["{bin}", "-f", "{rom}"],
        "bins": ["/usr/bin/mgba-qt", "mgba-qt", "mgba"],
        "flatpak": "io.mgba.mGBA",
    },
    "melonds": {
        "name": "melonDS",
        "command": ["{bin}", "{rom}"],
        "bins": ["/usr/bin/melonDS", "melonDS"],
        "flatpak": "net.kuribo64.melonDS",
    },
    "cemu": {
        "name": "Cemu",
        "command": ["{bin}", "-g", "{rom}"],
        "bins": ["/usr/bin/Cemu", "Cemu", "/usr/bin/cemu"],
        "flatpak": "info.cemu.Cemu",
    },
    "rpcs3": {
        "name": "RPCS3",
        "command": ["{bin}", "--no-gui", "{rom}"],
        "bins": ["/usr/bin/rpcs3", "rpcs3"],
        "flatpak": "net.rpcs3.RPCS3",
    },
    "flycast": {
        "name": "Flycast",
        "command": ["{bin}", "{rom}"],
        "bins": ["/usr/bin/flycast", "flycast", "flycast-qt"],
        "flatpak": "org.flycast.Flycast",
    },
    "xemu": {
        "name": "xemu",
        "command": ["{bin}", "-dvd_path", "{rom}"],
        "bins": ["/usr/bin/xemu", "xemu"],
        "flatpak": "app.xemu.xemu",
    },
    "azahar": {
        "name": "Azahar",
        "command": ["{bin}", "{rom}"],
        "bins": ["/usr/bin/azahar", "azahar", "azahar-qt"],
        "flatpak": "org.azahar_emu.Azahar",
    },
    "scummvm": {
        "name": "ScummVM",
        "command": ["{bin}", "--auto-detect", "{rom}"],
        "bins": ["/usr/bin/scummvm", "scummvm"],
        "flatpak": "org.scummvm.ScummVM",
    },
}


# ── RommDeck ─────────────────────────────────────────────────────────────────


def rommdeck_config() -> dict[str, Any] | None:
    try:
        return json.loads(ROMMDECK_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rommdeck_base(cfg: dict[str, Any]) -> str:
    port = cfg.get("web_port") or 8780
    return f"http://127.0.0.1:{int(port)}"


def deck_call(method: str, path: str, payload: dict | None = None, timeout: float = 60.0) -> tuple[int, Any]:
    """RommDeck's own local API. Status 0 means it did not answer at all."""
    cfg = rommdeck_config()
    if not cfg:
        return 0, "RommDeck is not installed on this machine"
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        rommdeck_base(cfg) + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw or b"null")
            except ValueError:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"null")
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, socket.timeout) as exc:
        return 0, str(exc)


def romm_call(path: str, timeout: float = 30.0) -> tuple[int, Any]:
    """RomM's server API, with the token RommDeck already holds."""
    cfg = rommdeck_config() or {}
    server = (cfg.get("server_url") or "").rstrip("/")
    token = cfg.get("token") or ""
    if not server or not token:
        return 0, "RommDeck is not paired with a RomM server"
    req = urllib.request.Request(
        f"{server}{path}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, socket.timeout) as exc:
        return 0, str(exc)


# ── platform map ─────────────────────────────────────────────────────────────


def platform_map() -> dict[str, dict[str, str]]:
    """RomM platform slug -> {rom_dir, emulator, dir, profile}.

    Every slug a RommDeck profile claims, so "ngc" and "gamecube" both land on
    the same emulator. Only enabled profiles with a rom_dir count: a profile
    that cannot say where the files go cannot be launched into.
    """
    cfg = rommdeck_config() or {}
    out: dict[str, dict[str, str]] = {}
    for prof in cfg.get("profiles") or []:
        if not isinstance(prof, dict) or not prof.get("enabled", True):
            continue
        for plat in prof.get("platforms") or []:
            if not isinstance(plat, dict):
                continue
            rom_dir = plat.get("rom_dir") or ""
            emulator = plat.get("emulator") or prof.get("id") or ""
            if not rom_dir or not emulator:
                continue
            for slug in plat.get("romm") or []:
                if isinstance(slug, str) and slug:
                    out[slug.lower()] = {
                        "rom_dir": rom_dir,
                        "emulator": emulator,
                        "dir": plat.get("dir") or "",
                        "profile": prof.get("name") or prof.get("id") or "",
                    }
            if plat.get("dir"):
                out.setdefault(str(plat["dir"]).lower(), {
                    "rom_dir": rom_dir,
                    "emulator": emulator,
                    "dir": str(plat["dir"]),
                    "profile": prof.get("name") or prof.get("id") or "",
                })
    return out


def resolve_emulator(emu_id: str) -> tuple[str, list[str]] | None:
    """The command line for an emulator id: (display name, argv).

    `{rom}` and `{rom_dir}` are still placeholders in the returned argv; the
    caller fills them per launch. `{bin}` is resolved here, once.
    """
    spec = BridgeConfig.load().emulator(emu_id)
    if not spec:
        return None
    name = spec.get("name") or emu_id
    exe = None
    for cand in spec.get("bins") or []:
        cand = str(cand)
        if cand.startswith("/"):
            if os.access(cand, os.X_OK):
                exe = cand
                break
        else:
            found = shutil.which(cand)
            if found:
                exe = found
                break
    if not exe:
        flatpak = spec.get("flatpak")
        if flatpak and shutil.which("flatpak"):
            return name, ["flatpak", "run", flatpak, "{rom}"]
        return None
    tmpl = spec.get("command") or ["{bin}", "{rom}"]
    return name, [exe if part == "{bin}" else str(part) for part in tmpl]


# ── launches ─────────────────────────────────────────────────────────────────


class Launches:
    """One record per rom id, and every subscriber waiting on it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[int, dict[str, Any]] = {}
        self.subs: list[Any] = []
        self.cancel: set[int] = set()
        self.procs: dict[int, subprocess.Popen] = {}

    def publish(self, state: dict[str, Any]) -> None:
        rid = int(state["romId"])
        with self.lock:
            self.state[rid] = state
            subs = list(self.subs)
        log(f"launch {rid}: {state.get('status')} {state.get('emulator') or ''}".rstrip())
        for q in subs:
            q.append(state)

    def get(self, rid: int) -> dict[str, Any] | None:
        with self.lock:
            return self.state.get(rid)

    def subscribe(self):
        q: list = []
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)


LAUNCHES = Launches()


def matches(rom_dir: Path, want_names: list[str], stem: str) -> Path | None:
    """The local file for a rom, by exact name first, then by a shared stem."""
    try:
        entries = [p for p in rom_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return None
    lowered = {p.name.lower(): p for p in entries}
    for name in want_names:
        if name and name.lower() in lowered:
            return lowered[name.lower()]
    want = re.sub(r"[^a-z0-9]+", "", stem.lower())
    if not want:
        return None
    for p in entries:
        have = re.sub(r"[^a-z0-9]+", "", p.stem.lower())
        if have and (have == want or have.startswith(want)):
            return p
    return None


def ensure_downloaded(rid: int, name: str, cover: str) -> tuple[bool, str]:
    """Ask RommDeck for the rom and wait for it to land."""
    st, body = deck_call("GET", f"/api/roms/{rid}/on_console")
    if st == 200 and isinstance(body, dict) and body.get("installed"):
        return True, ""
    if st not in (0, 200):
        return False, f"RommDeck could not answer for this game ({st}: {body})"

    st, body = deck_call("POST", "/api/download", {"rom_id": rid, "name": name, "cover": cover})
    if st not in (200, 202):
        return False, f"RommDeck refused the download ({st}: {body})"
    log(f"download queued for {rid}")

    deadline = time.time() + DOWNLOAD_TIMEOUT
    announced = -1
    while time.time() < deadline:
        if rid in LAUNCHES.cancel:
            deck_call("POST", "/api/downloads/cancel", {"rom_id": rid})
            return False, "cancelled"
        time.sleep(1.0)
        st, body = deck_call("GET", f"/api/roms/{rid}/on_console")
        if st == 200 and isinstance(body, dict) and body.get("installed"):
            return True, ""
        pct = progress_for(rid)
        if pct is not None and pct != announced:
            announced = pct
            LAUNCHES.publish({"romId": rid, "status": "downloading", "stage": "rom", "progress": pct / 100.0})
        st, body = deck_call("GET", "/api/downloads")
        if st == 200 and isinstance(body, list):
            for item in body:
                if int(item.get("rom_id") or item.get("id") or 0) == rid and item.get("state") in ("failed", "error"):
                    return False, str(item.get("error") or "the download failed")
    return False, "the download did not finish in time"


def progress_for(rid: int) -> int | None:
    st, body = deck_call("GET", "/api/downloads")
    if st != 200 or not isinstance(body, list):
        return None
    for item in body:
        if int(item.get("rom_id") or item.get("id") or 0) != rid:
            continue
        got, total = item.get("received") or item.get("done") or 0, item.get("total") or item.get("size") or 0
        if total:
            return max(0, min(100, int(100 * got / total)))
        if item.get("percent") is not None:
            return int(item["percent"])
    return None


def session_env() -> dict[str, str]:
    """The session a detached emulator needs, for a service that has none.

    systemd user units get XDG_RUNTIME_DIR but not WAYLAND_DISPLAY or
    DISPLAY, which are set per graphical session.
    """
    env = dict(os.environ)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    if not env.get("WAYLAND_DISPLAY"):
        for cand in sorted(Path(runtime).glob("wayland-*")):
            if not cand.name.endswith(".lock"):
                env["WAYLAND_DISPLAY"] = cand.name
                break
    if not env.get("DISPLAY") and env.get("WAYLAND_DISPLAY"):
        env["DISPLAY"] = ":0"
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    env.setdefault("PULSE_SERVER", f"unix:{runtime}/pulse/native")
    return env


def run_launch(rid: int, request: dict[str, Any]) -> None:
    name = str(request.get("name") or f"rom {rid}")
    slug = str(request.get("platformSlug") or request.get("platform_slug") or "").lower()

    map_ = platform_map()
    entry = map_.get(slug)
    if not entry:
        LAUNCHES.publish({
            "romId": rid, "status": "failed",
            "error": {"code": "no-emulator-configured",
                      "message": f"RommDeck has no emulator mapped for platform '{slug}'"},
        })
        return

    resolved = resolve_emulator(entry["emulator"])
    if not resolved:
        LAUNCHES.publish({
            "romId": rid, "status": "failed",
            "error": {"code": "emulator-not-found",
                      "message": f"{entry['emulator']} is not installed on this machine"},
        })
        return
    emu_name, argv_prefix = resolved

    LAUNCHES.publish({"romId": rid, "status": "downloading", "stage": "rom", "progress": 0.0})
    ok, why = ensure_downloaded(rid, name, str(request.get("cover") or ""))
    if not ok:
        code = "download-failed"
        LAUNCHES.publish({"romId": rid, "status": "failed", "error": {"code": code, "message": why}})
        return

    rom_dir = Path(entry["rom_dir"])
    file_name = str(request.get("fileName") or "")
    want = [file_name] if file_name else []
    path = matches(rom_dir, want, str(request.get("name") or "") or Path(file_name).stem)
    if path is None:
        st, details = romm_call(f"/api/roms/{rid}")
        if st == 200 and isinstance(details, dict):
            files = [str(f.get("file_name") or "") for f in details.get("files") or []]
            path = matches(rom_dir, files, name)
    if path is None:
        LAUNCHES.publish({
            "romId": rid, "status": "failed",
            "error": {"code": "download-failed",
                      "message": f"no file for {name} in {rom_dir}"},
        })
        return

    argv = [
        part.replace("{rom}", str(path)).replace("{rom_dir}", str(rom_dir))
        for part in argv_prefix
    ]
    env = session_env()
    log(f"launch {rid}: {' '.join(shlex.quote(a) for a in argv)}")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(rom_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        LAUNCHES.publish({
            "romId": rid, "status": "failed",
            "error": {"code": "launch-failed", "message": f"could not start {emu_name}: {exc}"},
        })
        return

    with LAUNCHES.lock:
        LAUNCHES.procs[rid] = proc
    LAUNCHES.publish({"romId": rid, "status": "running", "emulator": emu_name})

    code = proc.wait()
    with LAUNCHES.lock:
        LAUNCHES.procs.pop(rid, None)
        LAUNCHES.cancel.discard(rid)
    LAUNCHES.publish({"romId": rid, "status": "exited", "emulator": emu_name, "exitCode": code})


# ── HTTP ─────────────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = f"rommdeck-bridge/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib name
        log(f"{self.address_string()} {fmt % args}")

    # -- helpers ------------------------------------------------------------

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def reply(self, code: int, payload: Any) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            raw = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}
        return raw if isinstance(raw, dict) else {}

    # -- verbs --------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib name
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path in ("/", "/health"):
            cfg = rommdeck_config() or {}
            return self.reply(200, {
                "ok": True,
                "version": VERSION,
                "rommdeck": {
                    "paired": bool(cfg.get("token")),
                    "server": cfg.get("server_url") or None,
                    "platforms": len(platform_map()),
                },
            })
        if path == "/support":
            slugs = [s for s in (dict(x.split("=", 1) for x in query.split("&") if "=" in x).get("platforms", "")).split(",") if s]
            return self.reply(200, {"platforms": support_for(slugs)})
        if path == "/events":
            return self.stream()
        if path == "/launches":
            with LAUNCHES.lock:
                return self.reply(200, {"launches": list(LAUNCHES.state.values())})
        return self.reply(404, {"error": "no such endpoint"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0]
        payload = self.body()
        if path == "/launch":
            return self.launch(payload)
        if path == "/cancel":
            rid = int(payload.get("romId") or 0)
            with LAUNCHES.lock:
                LAUNCHES.cancel.add(rid)
            return self.reply(200, {"ok": True})
        if path == "/selftest":
            return self.selftest(payload)
        return self.reply(404, {"error": "no such endpoint"})

    # -- routes -------------------------------------------------------------

    def launch(self, payload: dict[str, Any]) -> None:
        if not platform_map():
            return self.reply(503, {"error": "RommDeck has no platforms mapped yet; finish its setup wizard"})
        try:
            rid = int(payload.get("romId") or payload.get("rom_id") or 0)
        except (TypeError, ValueError):
            rid = 0
        if rid <= 0:
            return self.reply(400, {"error": "romId is required"})
        current = LAUNCHES.get(rid)
        if current and current.get("status") in ("downloading", "running"):
            return self.reply(409, {"error": "already-running"})

        slug = str(payload.get("platformSlug") or "").lower()
        entry = platform_map().get(slug)
        resolved = resolve_emulator(entry["emulator"]) if entry else None
        if not entry or not resolved:
            return self.reply(409, {
                "error": "no-emulator-configured" if entry else "unsupported-platform",
                "message": f"nothing mapped for '{slug}'",
            })
        threading.Thread(target=run_launch, args=(rid, payload), daemon=True).start()
        return self.reply(202, {"romId": rid, "emulator": resolved[0]})

    def selftest(self, payload: dict[str, Any]) -> None:
        """Launch a mapped game by its RomM id, bypassing RomM's frontend."""
        rid = int(payload.get("romId") or 0)
        slug = str(payload.get("platformSlug") or "")
        if rid <= 0 or not slug:
            return self.reply(400, {"error": "romId and platformSlug are required"})
        threading.Thread(
            target=run_launch,
            args=(rid, {"name": payload.get("name"), "platformSlug": slug, "fileName": payload.get("fileName")}),
            daemon=True,
        ).start()
        return self.reply(202, {"romId": rid})

    def stream(self) -> None:
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = LAUNCHES.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                if q:
                    state = q.pop(0)
                    self.wfile.write(b"data: " + json.dumps(state).encode() + b"\n\n")
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            LAUNCHES.unsubscribe(q)


def support_for(slugs: list[str]) -> dict[str, dict[str, Any]]:
    map_ = platform_map()
    out: dict[str, dict[str, Any]] = {}
    for slug in slugs or list(map_):
        key = slug.lower()
        entry = map_.get(key)
        if not entry:
            out[key] = {"supported": False, "reason": "unsupported-platform",
                        "detail": f"RommDeck has no emulator mapped for {slug}"}
            continue
        resolved = resolve_emulator(entry["emulator"])
        if not resolved:
            out[key] = {"supported": False, "reason": "emulator-not-found",
                        "detail": f"{entry['emulator']} is not installed in {entry['profile']}"}
            continue
        out[key] = {"supported": True, "emulator": f"RommDeck ({resolved[0]})"}
    return out


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    cfg = BridgeConfig.load()
    httpd = ThreadingHTTPServer((cfg.bind, cfg.port), Handler)
    httpd.daemon_threads = True
    log(f"rommdeck-bridge {VERSION} listening on {cfg.bind}:{cfg.port}; "
        f"{len(platform_map())} platforms mapped")

    def bye(*_a) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        httpd.server_close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
