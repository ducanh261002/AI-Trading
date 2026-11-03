"""Local setup/start helper. Uses standard library until the venv is installed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent.parent


def python_path(directory):
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def lock_hash(root):
    return hashlib.sha256((root / "requirements.lock.txt").read_bytes()).hexdigest()


def prepare(root):
    if sys.version_info < (3, 12):
        raise RuntimeError("Can Python 3.12 tro len. Xem docs/WINDOWS_LOCAL.md.")
    directory = root / ".venv-windows"
    executable = python_path(directory)
    marker = directory / ".atc-ready.json"
    # A failed refresh must not leave a stale 'ready' marker.
    if marker.exists():
        marker.unlink()
    if not executable.is_file():
        if directory.exists():
            raise RuntimeError("Thu muc .venv-windows da co nhung khong hop le; khong tu dong xoa du lieu. Hay bao loi nay.")
        print("Dang tao moi truong Python rieng...", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    print("Dang cai thu vien. Lan dau can Internet, vui long doi...", flush=True)
    subprocess.run([str(executable), "-m", "pip", "install", "-r", "requirements.lock.txt"], cwd=root, check=True)
    subprocess.run([str(executable), "-m", "pip", "check"], cwd=root, check=True)
    settings = root / ".env"
    if not settings.exists():
        shutil.copyfile(root / ".env.example", settings)
    marker.write_text(json.dumps({"requirements_sha256": lock_hash(root)}), encoding="utf-8")
    print("Cai dat xong. Bam MO_WEBSITE.cmd de mo giao dien.", flush=True)


def check_ready(root):
    directory = root / ".venv-windows"
    marker = directory / ".atc-ready.json"
    try:
        ready = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("Chua cai dat xong. Hay chay CAI_DAT_WINDOWS.cmd.") from None
    if not isinstance(ready, dict) or not python_path(directory).is_file() or ready.get("requirements_sha256") != lock_hash(root):
        raise RuntimeError("Thu vien chua khop ban code. Hay chay lai CAI_DAT_WINDOWS.cmd.")
    return python_path(directory)


def local_environment(port):
    # These overrides are process-local; existing .env and saved history remain.
    return dict(os.environ, ATC_HOSTED="false", ATC_MODE="paper",
                ATC_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}",
                ATC_PAPER_AUTO="false", ATC_AGENT_AUTO_SECONDS="0")


def stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def serve(root, executable, port=8000, open_browser=True, startup_timeout=45):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Cong {port} dang duoc su dung. Dong cua so website cu truoc; khong tu dong dung ung dung khac.") from None
    address = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([str(executable), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=root, env=local_environment(port))
    # Only loopback health checks bypass inherited proxy settings. Market
    # traffic continues using its normal proxy/CA configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Backend khong khoi dong duoc. Xem dong loi phia tren.")
            try:
                with opener.open(address + "/api/health", timeout=1) as response:
                    healthy = json.load(response).get("status") == "ok"
                if healthy:
                    break
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.3)
        else:
            raise RuntimeError("Backend chua san sang sau thoi gian cho. Xem loi tren cua so nay.")
        print(f"\nWebsite: {address}\nGiu cua so nay mo. Bam Ctrl+C de dung.\nChi chay PAPER, khong gui lenh tien that.\n", flush=True)
        if open_browser:
            try:
                webbrowser.open(address)
            except webbrowser.Error:
                print("Mo trinh duyet va nhap dia chi website o tren.", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        stop_child(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("setup", "start"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise RuntimeError("Port phai nam trong khoang 1024..65535.")
        if args.operation == "setup":
            prepare(ROOT)
            return 0
        return serve(ROOT, check_ready(ROOT), args.port, not args.no_browser)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\nLOI: {exc}\nKhong gui mat khau/API Key khi chup loi.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
