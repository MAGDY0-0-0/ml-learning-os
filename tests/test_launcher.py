"""The one-click launcher: a real server started, reused, restarted and stopped.

These spawn an actual uvicorn on a spare port, so they cover what the shortcut
really does on a click rather than a mock of it.
"""

from __future__ import annotations

import http.server
import socket
import struct
import subprocess
import sys
import threading
import zlib

import pytest

from app import launcher


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def spare(tmp_path, monkeypatch):
    """Point the launcher at a free port and a throwaway state folder.

    The server it starts still reads the suite's seeded database: it inherits
    MLOS_DATA_DIR from conftest. Only the launcher's own files land here.
    """
    monkeypatch.setattr(launcher, "PORT", _free_port())
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    opened = []
    monkeypatch.setattr(launcher, "open_window", lambda: opened.append(launcher.url()))
    yield opened
    launcher.stop_server(timeout=5)


def test_every_page_carries_the_marker_the_launcher_looks_for(client):
    """is_ours() reads the first 4 KB of / to tell this app from another program."""
    head = client.get("/").content[:4096]
    assert launcher.MARKER in head


def test_a_click_starts_the_server_once_then_reuses_it(spare):
    assert launcher.ensure_server() is None
    assert launcher.is_ours()
    first = launcher.read_state()["pid"]

    assert launcher.ensure_server() is None          # second click: same server
    assert launcher.read_state()["pid"] == first


def test_changed_code_restarts_the_server(spare, monkeypatch):
    assert launcher.ensure_server() is None
    before = launcher.read_state()["pid"]
    monkeypatch.setattr(launcher, "fingerprint", lambda root=launcher.ROOT: "after-a-git-pull")
    assert launcher.ensure_server() is None
    after = launcher.read_state()
    assert after["pid"] != before
    assert after["fingerprint"] == "after-a-git-pull"
    assert launcher.is_ours()


def test_stop_frees_the_port_and_forgets_the_server(spare):
    assert launcher.ensure_server() is None
    assert launcher.stop_server()
    assert not launcher.port_in_use()
    assert launcher.read_state() == {}


def test_main_opens_a_window_but_server_mode_does_not(spare):
    assert launcher.main(["--server"]) == 0
    assert spare == []
    assert launcher.main([]) == 0
    assert spare == [launcher.url()]


def test_another_program_on_the_port_is_reported_not_overrun(spare):
    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"someone else")
        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", launcher.PORT), Other)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        err = launcher.ensure_server()
        assert err and "another program" in err
        assert launcher.read_state() == {}              # nothing was started
    finally:
        srv.shutdown()


def test_a_stale_pid_never_kills_an_unrelated_process(spare):
    """Windows reuses PIDs: the state file may name a program that is not ours."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        launcher.DATA_DIR.mkdir(parents=True, exist_ok=True)
        launcher.state_file().write_text(f'{{"pid": {other.pid}}}', encoding="utf-8")
        launcher.stop_server(timeout=0.5)
        assert other.poll() is None, "an unrelated process was killed"
    finally:
        other.kill()


def test_fingerprint_follows_python_files_only(tmp_path):
    (tmp_path / "app" / "templates").mkdir(parents=True)
    py = tmp_path / "app" / "x.py"
    py.write_text("a = 1\n")
    (tmp_path / "app" / "templates" / "t.html").write_text("<p>")
    before = launcher.fingerprint(tmp_path)
    (tmp_path / "app" / "templates" / "t.html").write_text("<p>changed, read per request")
    assert launcher.fingerprint(tmp_path) == before
    py.write_text("a = 22\n")
    assert launcher.fingerprint(tmp_path) != before


# --------------------------------------------------------------------------
# the icon and the shortcuts
# --------------------------------------------------------------------------


def _decode_png(data: bytes) -> tuple[int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", 0
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            size = struct.unpack(">I", body[:4])[0]
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    assert len(raw) == size * (1 + 4 * size)
    return size, b"".join(raw[r * (1 + 4 * size) + 1:(r + 1) * (1 + 4 * size)] for r in range(size))


def _px(size, rgba, x, y):
    i = (y * size + x) * 4
    return tuple(rgba[i:i + 4])


def test_the_icon_is_the_logo_at_every_size(tmp_path):
    ico = launcher.make_icon(tmp_path / "i.ico").read_bytes()
    _, kind, count = struct.unpack("<HHH", ico[:6])
    assert (kind, count) == (1, 4)
    images = {}
    for k in range(count):
        w, _, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", ico[6 + 16 * k:22 + 16 * k])
        size, rgba = _decode_png(ico[offset:offset + length])
        assert size == (w or 256)
        images[size] = rgba

    big = images[256]
    assert _px(256, big, 0, 0)[3] == 0                         # rounded corner: transparent
    assert _px(256, big, 128, 44)[:3] == (0x3f, 0xd9, 0xc4)    # the ring (radius 21, top)
    assert _px(256, big, 128, 76)[:3] == (0x0b, 0x0e, 0x13)    # the tile inside the ring
    assert _px(256, big, 96, 128)[:3] == (0xf4, 0xf6, 0xf8)    # the M's left stroke

    small = images[16]                                          # no M below 20px
    assert all(small[i:i + 3] != bytes((0xf4, 0xf6, 0xf8)) for i in range(0, len(small), 4))


def test_shortcut_script_makes_the_three_links_and_quotes_paths(tmp_path):
    weird = tmp_path / "Magdy's ML" / "pythonw.exe"
    script = launcher.shortcut_script(weird, tmp_path / "i.ico")
    assert script.count("CreateShortcut") == 3
    assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script
    assert "'Stop ML Journey.lnk'" in script
    assert "Magdy''s ML" in script                              # apostrophe escaped
    assert "'-m app.launcher'" in script
    assert "Startup" not in script
    assert "GetFolderPath('Startup')" in launcher.shortcut_script(weird, tmp_path / "i.ico", autostart=True)
