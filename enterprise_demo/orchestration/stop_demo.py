from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.paths import PID_FILE  # noqa: E402


def command_line(pid: int) -> str:
    script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
    return subprocess.check_output(["powershell", "-NoProfile", "-Command", script], text=True).strip()


def executable_path(pid: int) -> str:
    script = f"(Get-Process -Id {pid} -ErrorAction Stop).Path"
    return subprocess.check_output(["powershell", "-NoProfile", "-Command", script], text=True).strip()


def main() -> int:
    if not PID_FILE.exists():
        print("No enterprise-demo PID file exists.")
        return 0
    state = json.loads(PID_FILE.read_text(encoding="utf-8"))
    if isinstance(state, dict) and state.get("supervisor_pid"):
        supervisor_pid = int(state["supervisor_pid"])
        try:
            os.kill(supervisor_pid, signal.SIGTERM)
            print(f"Requested enterprise-demo supervisor shutdown (PID {supervisor_pid})")
            time.sleep(0.5)
        except (ProcessLookupError, OSError):
            pass
        entries = state.get("services", [])
    else:
        entries = state
    for entry in reversed(entries):
        pid = int(entry["pid"])
        expected_executable = str(entry.get("command", [""])[0])
        try:
            actual_executable = executable_path(pid)
        except subprocess.CalledProcessError:
            continue
        if Path(actual_executable).resolve() != Path(expected_executable).resolve():
            print(
                f"Refusing to stop PID {pid}; executable mismatch: {actual_executable}",
                file=sys.stderr,
            )
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Stopped {entry['name']} (PID {pid})")
        except ProcessLookupError:
            pass
    PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
