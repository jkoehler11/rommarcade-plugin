#!/usr/bin/env python3
"""Why does Dolphin abort when the bridge starts it? Try the plausible ways."""
import os, subprocess, sys, time, glob

ROM_DIR = "/home/james/ROMs/gc"
ROM = os.path.join(ROM_DIR, "Luigi's Mansion (USA).nkit.rvz")
RUNTIME = "/run/user/1000"

def case(name, extra, argv):
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["XDG_RUNTIME_DIR"] = RUNTIME
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={RUNTIME}/bus"
    env.update(extra)
    t0 = time.time()
    try:
        p = subprocess.run(argv, env=env, cwd=ROM_DIR, capture_output=True, text=True, timeout=20)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        code = "still-running-20s"
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    print(f"=== {name}: rc={code} after {time.time()-t0:.1f}s")
    print("stdout:", (out or "").strip()[-600:])
    print("stderr:", (err or "").strip()[-1200:])

print("exists:", os.path.exists(ROM))
case("wayland only", {"WAYLAND_DISPLAY": "wayland-1"}, ["/usr/bin/dolphin-emu", "--batch", "--exec=" + ROM])
case("x11 only", {"DISPLAY": ":0"}, ["/usr/bin/dolphin-emu", "--batch", "--exec=" + ROM])
case("systemd-run --user", {}, ["systemd-run", "--user", "--collect", "--quiet", "--wait", "--pipe",
                                "--unit=rommdeck-probe", "/usr/bin/dolphin-emu", "--batch", "--exec=" + ROM])
