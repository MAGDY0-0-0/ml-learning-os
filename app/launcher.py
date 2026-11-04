"""Open the app with one click: start the server if needed, then show its window.

The shortcuts made by `install-shortcuts.bat` run this with pythonw.exe, so no
console appears. What a click does:

1. If the app already answers on its port, open a window on it.
2. If the code changed since this launcher started that server (a `git pull`),
   restart it first, so you never study on stale code.
3. Otherwise start the server hidden, wait until it answers, then open the
   window: Edge or Chrome in app mode (no tabs, no address bar), so it behaves
   like a program rather than a browser tab.

Anything that goes wrong is said in a message box, because a launcher with no
console that fails silently looks exactly like a launcher that did nothing.

    python -m app.launcher             open the app (start the server if needed)
    python -m app.launcher --stop      stop the background server
    python -m app.launcher --restart   stop it, then open the app again
    python -m app.launcher --install   create the Desktop and Start-menu shortcuts
                                       (add --autostart to start it at sign-in)
    python -m app.launcher --server    start the server only, no window
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("MLOS_DATA_DIR") or ROOT / "data")
PORT = int(os.environ.get("MLOS_PORT") or 8000)
HOST = "127.0.0.1"
NAME = "ML Journey"

#: Text every page of this app carries in its <title>; how the launcher tells
#: its own server apart from some other program holding the port.
MARKER = b"ML Journey"


def url() -> str:
    return f"http://{HOST}:{PORT}/"


def state_file() -> Path:
    return DATA_DIR / "server.json"


def log_file() -> Path:
    return DATA_DIR / "server.log"


# --------------------------------------------------------------------------
# is it running, and is it ours?
# --------------------------------------------------------------------------


def port_in_use(port: int | None = None) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port or PORT)) == 0


def is_ours(timeout: float = 1.5) -> bool:
    """True when this app (not some other program) answers on the port."""
    try:
        with urllib.request.urlopen(url(), timeout=timeout) as r:
            return r.status == 200 and MARKER in r.read(4096)
    except (OSError, ValueError):
        return False


def fingerprint(root: Path = ROOT) -> str:
    """Changes whenever server code changes. Templates and static files are
    read from disk on every request, so only Python needs a restart."""
    h = hashlib.sha1()
    for p in sorted((root / "app").rglob("*.py")):
        st = p.stat()
        h.update(f"{p.relative_to(root)}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return h.hexdigest()[:16]


def read_state() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------
# start / stop
# --------------------------------------------------------------------------


def _python() -> str:
    """The console interpreter next to us. Under pythonw.exe there is no
    stdout, so the server runs on python.exe with its window suppressed."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def start_server() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if log_file().stat().st_size > 1_000_000:      # keep the log from growing forever
            log_file().write_bytes(log_file().read_bytes()[-200_000:])
    except OSError:
        pass
    log = open(log_file(), "ab")
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [_python(), "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT)],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs,
    )
    log.close()
    state_file().write_text(json.dumps({
        "pid": proc.pid, "port": PORT, "fingerprint": fingerprint(), "started": time.time(),
    }), encoding="utf-8")
    return proc.pid


def wait_until_ready(timeout: float = 25.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if is_ours(timeout=1.0):
            return True
        time.sleep(0.2)
    return False


def _is_server_process(pid: int) -> bool:
    """Is this PID still our Python server? Windows reuses PIDs quickly, and a
    stale state file must never get an unrelated program killed."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=5).stdout.lower()
            return "python" in out
        cmdline = Path(f"/proc/{pid}/cmdline")
        if cmdline.exists():
            return b"uvicorn" in cmdline.read_bytes()
        os.kill(pid, 0)                     # other POSIX: it exists; trust the state file
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def stop_server(timeout: float = 8.0) -> bool:
    """Stop the server this launcher started. Returns True once the port is free."""
    pid = read_state().get("pid")
    if pid and _is_server_process(int(pid)):
        try:
            os.kill(int(pid), signal.SIGTERM)   # TerminateProcess on Windows
        except (OSError, ValueError):
            pass
    end = time.monotonic() + timeout
    while time.monotonic() < end and port_in_use():
        time.sleep(0.1)
    try:
        state_file().unlink()
    except OSError:
        pass
    return not port_in_use()


def ensure_server() -> str | None:
    """Make sure the current code is serving. Returns an error message or None."""
    if is_ours():
        st = read_state()
        if st.get("pid") and st.get("fingerprint") != fingerprint():
            if not stop_server():
                return (f"The app's code changed, but the old server on port {PORT} "
                        "would not stop. Close it from Task Manager (python.exe) and try again.")
        else:
            return None
    elif port_in_use():
        return (f"Port {PORT} is already used by another program, so {NAME} cannot start.\n\n"
                "Close that program, or set MLOS_PORT to another port.")
    start_server()
    if wait_until_ready():
        return None
    tail = ""
    try:
        tail = log_file().read_text(encoding="utf-8", errors="replace")[-1500:]
    except OSError:
        pass
    return f"The server did not start. The last lines of {log_file()}:\n\n{tail}"


# --------------------------------------------------------------------------
# the window
# --------------------------------------------------------------------------


def _app_browser() -> str | None:
    """Edge ships with Windows; Chrome is the fallback. Both support --app."""
    candidates: list[Path] = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe"]
        for c in candidates:
            if c.exists():
                return str(c)
        return None
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_window() -> None:
    browser = _app_browser()
    if browser:
        subprocess.Popen([browser, f"--app={url()}"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import webbrowser
        webbrowser.open(url())


def say(message: str, error: bool = True) -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, NAME, 0x10 if error else 0x40)
            return
        except Exception:  # noqa: BLE001 - the message must reach the user somehow
            pass
    print(message, file=sys.stderr if error else sys.stdout)


# --------------------------------------------------------------------------
# shortcuts and their icon
# --------------------------------------------------------------------------


def _png(size: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def logo_pixels(size: int) -> bytes:
    """The mark from templates/_logo.html, drawn with signed distances so every
    size is anti-aliased and crisp: a 64-unit tile at radius 16, a full ring of
    radius 21 and stroke 6, and the M at stroke 3.5. Below 20px the M is
    dropped, as the logo's own spec says."""
    tile, ring, ink = (0x0b, 0x0e, 0x13), (0x3f, 0xd9, 0xc4), (0xf4, 0xf6, 0xf8)
    m = [(24, 39, 24, 25), (24, 25, 32, 33), (32, 33, 40, 25), (40, 25, 40, 39)]
    k = 64 / size                      # design units per pixel
    out = bytearray()
    for j in range(size):
        for i in range(size):
            x, y = (i + 0.5) * k, (j + 0.5) * k
            qx, qy = max(abs(x - 32) - 16, 0), max(abs(y - 32) - 16, 0)
            d_tile = (qx * qx + qy * qy) ** 0.5 - 16
            a = max(0.0, min(1.0, 0.5 - d_tile / k))
            if a == 0:
                out += b"\x00\x00\x00\x00"
                continue
            r, g, b = tile
            cov = max(0.0, min(1.0, 0.5 - (abs(((x - 32) ** 2 + (y - 32) ** 2) ** 0.5 - 21) - 3) / k))
            r, g, b = (r + (ring[0] - r) * cov, g + (ring[1] - g) * cov, b + (ring[2] - b) * cov)
            if size >= 20:
                d_m = min(_seg(x, y, *s) for s in m) - 1.75
                cov = max(0.0, min(1.0, 0.5 - d_m / k))
                r, g, b = (r + (ink[0] - r) * cov, g + (ink[1] - g) * cov, b + (ink[2] - b) * cov)
            out += bytes((round(r), round(g), round(b), round(a * 255)))
    return bytes(out)


def make_icon(path: Path, sizes: tuple[int, ...] = (256, 48, 32, 16)) -> Path:
    """Write a Windows .ico (PNG entries) of the logo."""
    images = [_png(s, logo_pixels(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for s, img in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(images))
    return path


def _ps(s: str) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(s).replace("'", "''") + "'"


def shortcut_script(pythonw: Path, icon: Path, autostart: bool = False) -> str:
    """PowerShell that writes the .lnk files (WScript.Shell, present on every Windows)."""
    links = [("Desktop", NAME, "-m app.launcher"),
             ("Programs", NAME, "-m app.launcher"),
             ("Programs", f"Stop {NAME}", "-m app.launcher --stop")]
    if autostart:
        links.append(("Startup", f"{NAME} (background)", "-m app.launcher --server"))
    lines = ["$sh = New-Object -ComObject WScript.Shell"]
    for folder, title, args in links:
        lines += [
            f"$l = $sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath({_ps(folder)})) {_ps(title + '.lnk')}))",
            f"$l.TargetPath = {_ps(pythonw)}",
            f"$l.Arguments = {_ps(args)}",
            f"$l.WorkingDirectory = {_ps(ROOT)}",
            f"$l.IconLocation = {_ps(str(icon) + ',0')}",
            f"$l.Description = {_ps('Open ' + NAME)}",
            "$l.Save()",
        ]
    return "\n".join(lines)


def install(autostart: bool = False) -> str:
    if os.name != "nt":
        return "Shortcuts are made for Windows. Elsewhere, run: python -m app.launcher"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        return f"pythonw.exe was not found next to {sys.executable}."
    icon = make_icon(DATA_DIR / "ml-journey.ico")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         shortcut_script(pythonw, icon, autostart)],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        return "Could not create the shortcuts:\n\n" + (done.stderr or done.stdout)[-1500:]
    extra = " It will also start in the background when you sign in." if autostart else ""
    return (f"Done. Double-click \"{NAME}\" on your Desktop or in the Start menu to open the app."
            f" Right-click it and choose \"Pin to taskbar\" for one-click access.{extra}")


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--install" in args:
        msg = install(autostart="--autostart" in args)
        print(msg)
        return 0 if msg.startswith("Done") else 1
    if "--stop" in args:
        ok = stop_server()
        if not ok:
            say(f"Something is still using port {PORT}; it may not have been started by {NAME}.")
        return 0 if ok else 1
    if "--restart" in args:
        stop_server()
    err = ensure_server()
    if err:
        say(err)
        return 1
    if "--server" not in args:
        open_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
