"""Claude Code usage data: daily API-price cost from transcripts, plan limits from the status line cache.

Transcripts:  <config dir>/projects/**/*.jsonl  (every assistant message carries `usage` + `model`)
Limits:       <config dir>/usage-limits.json    (written by statusline.py on every status line refresh)

<config dir> is $claude_config_dir (workflow setting), else $CLAUDE_CONFIG_DIR, else ~/.claude.
Runs on the macOS system Python (/usr/bin/python3, 3.9), standard library only.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Bump when prices or parsing change, so cached per-file costs are recomputed.
CACHE_VERSION = 4

# (model id pattern, input, output, cache read) in USD per million tokens, first match wins.
# Cache writes are priced from input: 1.25x for the 5-minute TTL, 2x for the 1-hour TTL.
PRICES: List[Tuple[str, float, float, float]] = [
    (r"fable-5-2|mythos-5-2", 8.00, 40.00, 0.20),
    (r"fable-5-1|mythos-5-1", 10.00, 50.00, 0.25),
    (r"fable-5|mythos-5|mythos-preview", 10.00, 50.00, 1.00),
    (r"opus-5-5", 4.00, 20.00, 0.20),
    (r"opus-5", 5.00, 25.00, 0.50),
    (r"opus-4-[5-9]", 5.00, 25.00, 0.50),
    (r"opus-4|opus-3|3-opus", 15.00, 75.00, 1.50),
    (r"sonnet-5-5", 2.00, 10.00, 0.10),
    (r"sonnet-5", 2.00, 10.00, 0.20),
    (r"sonnet-4|sonnet-3|3-[57]-sonnet", 3.00, 15.00, 0.30),
    (r"haiku-5-5", 0.10, 0.50, 0.01),
    (r"haiku-4", 1.00, 5.00, 0.10),
    (r"3-5-haiku", 0.80, 4.00, 0.08),
    (r"3-haiku", 0.25, 1.25, 0.03),
    # Unknown future versions: price as the current model of the family.
    (r"fable|mythos", 8.00, 40.00, 0.20),
    (r"opus", 4.00, 20.00, 0.20),
    (r"sonnet", 2.00, 10.00, 0.10),
    (r"haiku", 0.10, 0.50, 0.01),
]
_PRICE_RES = [(re.compile(p), i, o, r) for p, i, o, r in PRICES]
HAIKU_55_LONG = (0.50, 2.50, 0.05)  # Haiku 5.5 prompts over 100K tokens
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches


def config_dir() -> Path:
    raw = os.environ.get("claude_config_dir") or os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    return Path(raw).expanduser()


def limits_file(cfg: Optional[Path] = None) -> Path:
    return (cfg or config_dir()) / "usage-limits.json"


def cache_dir() -> Path:
    base = os.environ.get("alfred_workflow_cache")
    path = Path(base) if base else Path.home() / "Library/Caches/claude-usage-alfred"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- pricing

def price_for(model: str) -> Optional[Tuple[float, float, float]]:
    for rx, i, o, r in _PRICE_RES:
        if rx.search(model):
            return i, o, r
    return None


def request_cost(model: str, usage: dict) -> float:
    """API-list-price cost of one request, in USD."""
    prices = price_for(model)
    if not prices:
        return 0.0
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    read = usage.get("cache_read_input_tokens") or 0
    write = usage.get("cache_creation_input_tokens") or 0
    split = usage.get("cache_creation") or {}
    w1h = split.get("ephemeral_1h_input_tokens") or 0
    w5m = split.get("ephemeral_5m_input_tokens") or 0
    if w1h + w5m == 0 and write:
        w5m = write

    pin, pout, pread = prices
    if "haiku-5-5" in model and inp + read + write > 100_000:
        pin, pout, pread = HAIKU_55_LONG
    cost = (inp * pin + out * pout + read * pread + w5m * pin * 1.25 + w1h * pin * 2.0) / 1e6
    if usage.get("speed") == "fast":
        cost *= 2.0
    searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
    return cost + searches * WEB_SEARCH_USD


# ---------------------------------------------------------------- transcripts

def _epoch(ts: str) -> Optional[int]:
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return None


def _parse_lines(chunk: bytes, entries: Dict[str, list], rejections: List[list]) -> None:
    for raw in chunk.splitlines():
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        quota = rec.get("quotaLimits")
        if rec.get("isApiErrorMessage") and isinstance(quota, dict) and quota.get("status") == "rejected":
            # "You've hit your 5-hour limit": the request was refused, so the status line never
            # hears about it. Remember the window type and when it resets.
            ts = _epoch(rec.get("timestamp", ""))
            if ts and quota.get("resetsAt"):
                rejections.append([ts, quota.get("rateLimitType") or "", int(quota["resetsAt"])])
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage")
        model = msg.get("model") or ""
        if not usage or not model or model.startswith("<"):
            continue
        ts = _epoch(rec.get("timestamp", ""))
        if ts is None:
            continue
        # One API response is written as several lines (one per content block) sharing id + requestId.
        key = f"{msg.get('id', '')}:{rec.get('requestId', '')}"
        if key not in entries:
            entries[key] = [ts, round(request_cost(model, usage), 6)]


def _scan_file(path: Path, prev: Optional[dict]) -> dict:
    st = path.stat()
    if prev and prev.get("m") == st.st_mtime and prev.get("s") == st.st_size:
        return prev
    entries: Dict[str, list] = {}
    rejections: List[list] = []
    offset = 0
    if prev and st.st_size >= prev.get("o", 0) > 0:
        # Transcripts are append-only: parse just the new tail.
        entries = dict(prev.get("e", {}))
        rejections = list(prev.get("r", []))
        offset = prev["o"]
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = data.rfind(b"\n") + 1  # leave a partially written last line for next time
    _parse_lines(data[:end], entries, rejections)
    return {"m": st.st_mtime, "s": st.st_size, "o": offset + end, "e": entries, "r": rejections[-5:]}


def cached_scan(name: str, version: int, root: Path, paths, scan) -> Dict[str, dict]:
    """Run scan(path, previous result) over every path, keeping results in a per-file cache.

    scan returns {"m": mtime, "s": size, "e": {key: [epoch, cost]}, ...} and should return
    the previous result unchanged when the file hasn't changed.
    """
    cache_path = cache_dir() / f"{name}.json"
    try:
        cache = json.loads(cache_path.read_text())
        if cache.get("v") != version or cache.get("root") != str(root):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    old_files = cache.get("files", {})

    files: Dict[str, dict] = {}
    for path in paths:
        try:
            files[str(path)] = scan(path, old_files.get(str(path)))
        except OSError:
            continue

    if files != old_files:
        tmp = cache_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"v": version, "root": str(root), "files": files}, separators=(",", ":")))
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return files


def merge_entries(files: Dict[str, dict]) -> Dict[str, list]:
    merged: Dict[str, list] = {}
    for info in files.values():
        merged.update(info["e"])  # resumed / forked sessions copy requests: same key, counted once
    return merged


def collect(cfg: Optional[Path] = None) -> Tuple[Dict[str, list], List[list]]:
    """(every unique API request as {key: [epoch, cost]}, limit rejections as [epoch, type, resets_at])."""
    cfg = cfg or config_dir()
    files = cached_scan("transcripts", CACHE_VERSION, cfg, (cfg / "projects").glob("**/*.jsonl"), _scan_file)
    rejections = [r for info in files.values() for r in info.get("r", [])]
    return merge_entries(files), rejections


def collect_requests(cfg: Optional[Path] = None) -> Dict[str, list]:
    return collect(cfg)[0]


def daily_totals(requests: Dict[str, list]) -> Dict[date, List[float]]:
    """{local date: [cost, request count]}"""
    days: Dict[date, List[float]] = {}
    for ts, cost in requests.values():
        d = datetime.fromtimestamp(ts).date()
        slot = days.setdefault(d, [0.0, 0])
        slot[0] += cost
        slot[1] += 1
    return days


def current_streak(days: Dict[date, List[float]], today: date) -> int:
    """Consecutive active days ending today (or yesterday, while today has no activity yet)."""
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


# ---------------------------------------------------------------- limits

def load_limits(cfg: Optional[Path] = None, rejections: Optional[List[list]] = None,
                now_ts: Optional[float] = None) -> Optional[dict]:
    """Limits as {"updated_at": epoch, "windows": [{"minutes", "used_percentage", "resets_at", "limited"?}]}.

    Percentages come from the status line cache. A limit rejection in the transcripts whose
    window hasn't reset yet overrides its window with 100%: once you're blocked, Claude Code
    stops getting fresh percentages, so the cache still shows the last reading before the limit.
    """
    now_ts = now_ts or time.time()
    try:
        data = json.loads(limits_file(cfg).read_text())
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    windows = []
    for name, minutes in (("five_hour", 300), ("seven_day", 10080)):
        w = data.get(name)
        if isinstance(w, dict) and w.get("used_percentage") is not None:
            windows.append({"minutes": minutes, "used_percentage": w["used_percentage"], "resets_at": w.get("resets_at")})
    updated = data.get("updated_at")

    for ts, kind, resets in sorted(rejections or []):
        minutes = 300 if kind.startswith("five_hour") else 10080 if kind.startswith("seven_day") else None
        if minutes is None or resets <= now_ts:
            continue
        current = next((w for w in windows if w["minutes"] == minutes), None)
        if current and (current.get("resets_at") or 0) > resets + 3600:
            continue  # the cache already has a later window than the one that was blocked
        hit = {"minutes": minutes, "used_percentage": 100, "resets_at": resets, "limited": True}
        windows = [w for w in windows if w["minutes"] != minutes] + [hit]
        updated = max(updated or 0, ts)

    if not windows and not updated:
        return None
    return {"updated_at": updated, "windows": sorted(windows, key=lambda w: w["minutes"])}


def now() -> float:
    return time.time()
