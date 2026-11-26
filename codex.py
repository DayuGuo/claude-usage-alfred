"""Codex CLI / app usage: daily API-price cost and plan limits, both from Codex's session rollouts.

Rollouts:  <codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]  (and archived_sessions/)
  token_usage_record   one per API response: response_id + token usage
  turn_context         the model used for the following turn
  event_msg/token_count  carries rate_limits: used_percent, window_minutes, resets_at
<codex home> is $codex_home (workflow setting), else $CODEX_HOME, else ~/.codex.
Compressed rollouts need the zstd command (brew install zstd).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from usage import cached_scan, merge_entries

CACHE_VERSION = 2
# Early rollouts (2025) often don't name the model; Codex defaulted to gpt-5 / gpt-5-codex (same price).
DEFAULT_MODEL = "gpt-5"

# (model slug pattern, input, cached input, output) in USD per million tokens, first match wins.
# Requests over 272K input tokens use the long-context rates (LONG) where a model has them.
# Source: developers.openai.com/api/docs/pricing, November 2026 (GPT-5.6 Sol at its promotional price).
PRICES: List[Tuple[str, float, float, float]] = [
    (r"^gpt-6\.2-astra", 8.00, 0.40, 40.00),
    (r"^gpt-6\.2-sol", 2.00, 0.10, 10.00),
    (r"^gpt-6\.1-sol", 2.00, 0.10, 10.00),
    (r"^gpt-6\.1-terra", 1.00, 0.05, 5.00),
    (r"^gpt-6-astra", 10.00, 1.00, 50.00),
    (r"^gpt-6-sol", 2.00, 0.20, 10.00),
    (r"^gpt-6-luna", 0.10, 0.01, 0.50),
    (r"^gpt-5\.6-sol", 4.00, 0.40, 20.00),
    (r"^gpt-5\.6-terra", 2.00, 0.20, 12.00),
    (r"^gpt-5\.6-luna", 0.20, 0.02, 1.20),
    (r"^gpt-5\.5", 5.00, 0.50, 30.00),
    (r"^gpt-5\.4-mini", 0.75, 0.075, 4.50),
    (r"^gpt-5\.4-nano", 0.20, 0.02, 1.25),
    (r"^gpt-5\.4", 2.50, 0.25, 15.00),
    (r"^gpt-5\.[23]", 1.75, 0.175, 14.00),
    (r"^gpt-5-mini", 0.25, 0.025, 2.00),
    (r"^gpt-5-nano", 0.05, 0.005, 0.40),
    (r"^gpt-5(\.1)?(-codex)?(-|$)", 1.25, 0.125, 10.00),
    # Unknown future versions: price as the newest model of the tier.
    (r"astra", 8.00, 0.40, 40.00),
    (r"sol", 2.00, 0.10, 10.00),
    (r"terra", 1.00, 0.05, 5.00),
    (r"luna", 0.10, 0.01, 0.50),
]
_PRICE_RES = [(re.compile(p), i, c, o) for p, i, c, o in PRICES]
LONG_CONTEXT = 272_000
LONG_MULTIPLIER = {"input": 2.0, "output": 1.5}  # long-context rates are 2x input/cached, 1.5x output
NO_LONG_CONTEXT = re.compile(r"mini|nano|gpt-5\.[23]|gpt-5(\.1)?(-codex)?(-|$)")
USAGE_URL = "https://chatgpt.com/codex/settings/usage"


def codex_home() -> Path:
    raw = os.environ.get("codex_home") or os.environ.get("CODEX_HOME") or "~/.codex"
    return Path(raw).expanduser()


def zstd_path() -> Optional[str]:
    for candidate in ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("zstd")


def request_cost(model: str, usage: dict) -> float:
    for rx, pin, pcached, pout in _PRICE_RES:
        if rx.search(model or ""):
            break
    else:
        return 0.0
    inp = usage.get("input_tokens") or 0  # includes cached input
    cached = min(usage.get("cached_input_tokens") or 0, inp)
    out = usage.get("output_tokens") or 0  # includes reasoning
    if inp > LONG_CONTEXT and not NO_LONG_CONTEXT.search(model):
        pin, pcached = pin * LONG_MULTIPLIER["input"], pcached * LONG_MULTIPLIER["input"]
        pout *= LONG_MULTIPLIER["output"]
    return ((inp - cached) * pin + cached * pcached + out * pout) / 1e6


def _epoch(ts: str) -> Optional[int]:
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return None


def _read(path: Path) -> bytes:
    if path.suffix == ".zst":
        zstd = zstd_path()
        if not zstd:
            raise OSError("zstd not installed")
        return subprocess.run([zstd, "-dcq", str(path)], capture_output=True, check=True, timeout=30).stdout
    return path.read_bytes()


def _scan_file(path: Path, prev: Optional[dict]) -> dict:
    st = path.stat()
    if prev and prev.get("m") == st.st_mtime and prev.get("s") == st.st_size:
        return prev
    try:
        data = _read(path)
    except (subprocess.SubprocessError, OSError):
        return {"m": st.st_mtime, "s": st.st_size, "e": {}, "zstd_missing": path.suffix == ".zst" and not zstd_path()}

    entries: Dict[str, list] = {}
    limits: Optional[list] = None  # [epoch, rate_limits]
    model = ""
    has_records = b'"token_usage_record"' in data
    prev_total = -1
    for n, raw in enumerate(data.splitlines()):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        kind = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if kind in ("session_meta", "turn_context"):
            model = payload.get("model") or model
        elif kind == "token_usage_record":
            ts = _epoch(rec.get("timestamp", ""))
            usage = payload.get("usage") or {}
            if ts is None or not usage:
                continue
            key = payload.get("response_id") or f"{payload.get('thread_id')}:{rec.get('ordinal', n)}"
            entries.setdefault(key, [ts, round(request_cost(model or DEFAULT_MODEL, usage), 6)])
        elif kind == "event_msg" and payload.get("type") == "token_count":
            ts = _epoch(rec.get("timestamp", ""))
            if ts is None:
                continue
            if payload.get("rate_limits") and (limits is None or ts >= limits[0]):
                limits = [ts, payload["rate_limits"]]
            info = payload.get("info") or {}
            if not has_records and info.get("last_token_usage"):
                # Older rollouts: count a request each time the running total grows.
                total = (info.get("total_token_usage") or {}).get("total_tokens") or 0
                if total > prev_total:
                    entries[f"{path.name}:{n}"] = [ts, round(request_cost(model or DEFAULT_MODEL, info["last_token_usage"]), 6)]
                    prev_total = total
    return {"m": st.st_mtime, "s": st.st_size, "e": entries, "l": limits}


def _rollouts(home: Path):
    for folder in ("sessions", "archived_sessions"):
        base = home / folder
        if base.is_dir():
            yield from base.glob("**/rollout-*.jsonl")
            yield from base.glob("**/rollout-*.jsonl.zst")


def scan(home: Optional[Path] = None) -> Tuple[Dict[str, list], Optional[dict], bool]:
    """(requests {key: [epoch, cost]}, limits, some compressed rollouts couldn't be read)."""
    home = home or codex_home()
    files = cached_scan("codex-rollouts", CACHE_VERSION, home, _rollouts(home), _scan_file)
    latest = None
    for info in files.values():
        lim = info.get("l")
        if lim and (latest is None or lim[0] > latest[0]):
            latest = lim
    missing = any(info.get("zstd_missing") for info in files.values())
    return merge_entries(files), _normalise_limits(latest), missing


def _normalise_limits(latest: Optional[list]) -> Optional[dict]:
    if not latest:
        return None
    ts, rl = latest
    windows = []
    for name in ("primary", "secondary"):
        w = rl.get(name)
        if isinstance(w, dict) and w.get("used_percent") is not None:
            resets = w.get("resets_at")
            if resets is None and w.get("resets_in_seconds") is not None:  # older Codex versions
                resets = ts + int(w["resets_in_seconds"])
            windows.append({"minutes": w.get("window_minutes"), "used_percentage": w["used_percent"], "resets_at": resets})
    return {"updated_at": ts, "windows": windows, "plan": rl.get("plan_type")}
