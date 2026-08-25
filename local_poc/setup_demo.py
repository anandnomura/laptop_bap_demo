from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SETTINGS_DIR = ROOT / ".claude"
SETTINGS_PATH = SETTINGS_DIR / "settings.local.json"


def hook(command: str, matcher: str | None = None) -> list[dict[str, object]]:
    entry: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": f'"{sys.executable}" "{ROOT / "hooks" / "bap_hook.py"}" {command}',
                "timeout": 10,
                "statusMessage": f"BAP: {command}",
            }
        ]
    }
    if matcher is not None:
        entry["matcher"] = matcher
    return [entry]


def main() -> int:
    settings = {
        "hooks": {
            "SessionStart": hook("session-start"),
            "UserPromptSubmit": hook("capture-intent"),
            "PreToolUse": hook("authorize", "*"),
            "PermissionRequest": hook("permission-request", "*"),
            "PostToolUse": hook("post-tool", "*"),
            "SessionEnd": hook("session-end"),
        }
    }
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"Configured real Claude Code hooks: {SETTINGS_PATH}")
    print(f"Hook Python: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

