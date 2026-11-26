#!/usr/bin/python3
"""Claude Code status line that also saves your plan limits for the Claude Usage Alfred workflow.

Claude Code pipes session JSON to this script on every status line refresh. For Pro/Max/Ultra
accounts it includes `rate_limits` (5-hour and 7-day windows), which nothing else stores on disk,
so we merge it into <config dir>/usage-limits.json and print a compact status line.

settings.json:
  "statusLine": {"type": "command", "command": "/usr/bin/python3 ~/.claude/statusline-usage.py"}

To keep a status line you already have, set CLAUDE_USAGE_STATUSLINE_CMD to its command:
this script passes the same JSON to it and prints its output instead of the built-in line.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = ("five_hour", "seven_day", "spend_limit")


SAME_WINDOW = 3600  # resets_at values this close belong to the same window


def merge_window(saved, incoming: dict, now: int):
    """(window to keep, whether incoming is current).

    Every Claude Code session redraws its status line with the limits from its own last API
    response, so an idle session can hold an old snapshot. Usage within a window only grows,
    and a later window has a later resets_at, so the newest reading is the one to keep.
    """
    if not isinstance(saved, dict) or saved.get("used_percentage") is None:
        return incoming, True
    s_reset = saved.get("resets_at") or 0
    i_reset = incoming.get("resets_at") or 0
    if s_reset and s_reset <= now:
        return incoming, True  # the saved window is over; anything reported now is newer
    if i_reset and i_reset <= now:
        return saved, False  # incoming describes a window that has already reset
    if abs(i_reset - s_reset) <= SAME_WINDOW:
        if incoming["used_percentage"] >= saved["used_percentage"]:
            return incoming, True
        return saved, False
    return (incoming, True) if i_reset > s_reset else (saved, False)


def save_limits(data: dict) -> None:
    limits = data.get("rate_limits")
    if not isinstance(limits, dict) or not limits:
        return
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    path = cfg / "usage-limits.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    now = int(time.time())
    new = dict(old)
    current = False  # did this session report anything at least as new as what's saved?
    for name in WINDOWS:
        window = limits.get(name)
        if isinstance(window, dict) and window.get("used_percentage") is not None:
            new[name], fresh = merge_window(old.get(name), window, now)
            current = current or fresh
    if not current:
        return  # an idle session re-drawing an old snapshot: don't let it overwrite newer data
    changed = any(new.get(n) != old.get(n) for n in WINDOWS)
    if not changed and now - int(old.get("updated_at") or 0) < 60:
        return
    new["updated_at"] = now
    tmp = path.with_name(f".usage-limits.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(new))
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def short_wait(seconds: float) -> str:
    m = max(0, int(seconds // 60))
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d{h}h" if h else f"{d}d"


def tint(pct: float, text: str) -> str:
    code = "31" if pct >= 90 else "33" if pct >= 75 else "32"
    return f"\033[{code}m{text}\033[0m"


def builtin_line(data: dict) -> str:
    parts = []
    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(model)
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    limits = data.get("rate_limits") or {}
    now = time.time()
    for name, label in (("five_hour", "5h"), ("seven_day", "wk")):
        w = limits.get(name) or {}
        pct = w.get("used_percentage")
        if pct is None:
            continue
        text = f"{label} {pct:.0f}%"
        if name == "five_hour" and w.get("resets_at"):
            text += f" ↺{short_wait(w['resets_at'] - now)}"
        parts.append(tint(pct, text))
    return " \033[2m·\033[0m ".join(parts)


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    save_limits(data)

    chained = os.environ.get("CLAUDE_USAGE_STATUSLINE_CMD")
    if chained:
        try:
            out = subprocess.run(chained, shell=True, input=raw, capture_output=True, text=True, timeout=10)
            sys.stdout.write(out.stdout)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    print(builtin_line(data))


if __name__ == "__main__":
    main()
