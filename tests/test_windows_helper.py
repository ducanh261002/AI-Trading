import json
from pathlib import Path
import socket
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from scripts import windows


def prepared_tree(tmp_path):
    (tmp_path / "requirements.lock.txt").write_text("fastapi==0.162.0\n")
    (tmp_path / ".env.example").write_text("ATC_MODE=paper\n")
    executable = windows.python_path(tmp_path / ".venv-windows")
    executable.parent.mkdir(parents=True)
    executable.touch()
    return executable


def test_setup_preserves_existing_config_and_marks_only_success(tmp_path, monkeypatch):
    executable = prepared_tree(tmp_path)
    (tmp_path / ".env").write_text("EXISTING_SETTING=preserve\n")
    marker = tmp_path / ".venv-windows/.atc-ready.json"
    marker.write_text('{"requirements_sha256":"stale"}')

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(windows.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        windows.prepare(tmp_path)
    assert not marker.exists()
    assert (tmp_path / ".env").read_text() == "EXISTING_SETTING=preserve\n"
    monkeypatch.setattr(windows.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 0))
    windows.prepare(tmp_path)
    assert windows.check_ready(tmp_path) == executable
    assert (tmp_path / ".env").read_text() == "EXISTING_SETTING=preserve\n"
    (tmp_path / "requirements.lock.txt").write_text("changed\n")
    with pytest.raises(RuntimeError, match="chua khop"):
        windows.check_ready(tmp_path)


def test_incomplete_setup_and_local_overrides(tmp_path, monkeypatch):
    prepared_tree(tmp_path)
    with pytest.raises(RuntimeError, match="Chua cai dat"):
        windows.check_ready(tmp_path)
    monkeypatch.setenv("ATC_HOSTED", "true")
    monkeypatch.setenv("ATC_MODE", "live")
    monkeypatch.setenv("ATC_PAPER_AUTO", "true")
    environment = windows.local_environment(8123)
    assert environment["ATC_HOSTED"] == "false" and environment["ATC_MODE"] == "paper"
    assert environment["ATC_PAPER_AUTO"] == "false" and environment["ATC_AGENT_AUTO_SECONDS"] == "0"
    assert environment["ATC_PUBLIC_ORIGIN"] == "http://127.0.0.1:8123"


def test_startup_http_and_owned_child_cleanup(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("ATC_DATABASE_PATH", str(tmp_path / "runner.db"))
    monkeypatch.setenv("ATC_MARKET_ENABLED", "false")
    children = []
    real_popen = subprocess.Popen

    def spawn(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(windows.subprocess, "Popen", spawn)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    def browser(address):
        assert address == f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(address + "/api/health") as response:
            assert json.load(response)["status"] == "ok"
        with pytest.raises(urllib.error.HTTPError) as denied:
            opener.open(urllib.request.Request(address + "/api/orders", method="POST"))
        assert denied.value.code == 403
        # Simulate the owner's Ctrl+C after successful browser open.
        raise KeyboardInterrupt

    monkeypatch.setattr(windows.webbrowser, "open", browser)
    assert windows.serve(root, Path(sys.executable), port=port, startup_timeout=15) == 0
    assert len(children) == 1 and children[0].poll() is not None


def test_busy_port_does_not_spawn_or_kill_another_program(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Should not spawn a child on an occupied port")

    monkeypatch.setattr(windows.subprocess, "Popen", unexpected)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with pytest.raises(RuntimeError, match="dang duoc su dung"):
            windows.serve(tmp_path, Path(sys.executable), port=server.getsockname()[1])
