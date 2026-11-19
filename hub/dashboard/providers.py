"""Sources de consommation IA réellement accessibles.

- Anthropic Admin API (clé admin sk-ant-admin...) : tokens + coûts de l'organisation API.
- Logs locaux Claude Code (~/.claude/projects/**/*.jsonl) : tokens par modèle.
- OpenAI Admin API (clé admin) : tokens + coûts de l'organisation API.
Les quotas des abonnements Claude.ai / ChatGPT ne sont exposés par aucune API.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMEOUT = 30


@dataclass
class Usage:
    source: str
    # (date ISO, modèle) -> compteurs
    tokens: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    cost_by_day: dict = field(default_factory=lambda: defaultdict(float))  # USD
    has_cost: bool = False

    def add(self, day: str, model: str, **counts: int) -> None:
        row = self.tokens[(day, model or "?")]
        for k, v in counts.items():
            row[k] += int(v or 0)

    def by_model(self) -> dict[str, dict[str, int]]:
        out: dict = defaultdict(lambda: defaultdict(int))
        for (_, model), row in self.tokens.items():
            for k, v in row.items():
                out[model][k] += v
        return out

    def by_day(self) -> dict[str, dict[str, int]]:
        out: dict = defaultdict(lambda: defaultdict(int))
        for (day, _), row in self.tokens.items():
            for k, v in row.items():
                out[day][k] += v
        return dict(sorted(out.items()))

    def total(self) -> dict[str, int]:
        out: dict = defaultdict(int)
        for row in self.tokens.values():
            for k, v in row.items():
                out[k] += v
        return out

    def total_cost(self) -> float:
        return sum(self.cost_by_day.values())


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "hub-windows"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _paged(base: str, params: list[tuple[str, str]], headers: dict, page_param: str = "page"):
    page = None
    for _ in range(50):
        p = list(params) + ([(page_param, page)] if page else [])
        data = _get(f"{base}?{urllib.parse.urlencode(p)}", headers)
        yield data
        page = data.get("next_page")
        if not data.get("has_more") or not page:
            break


# ---------- Anthropic ----------

def parse_anthropic_usage(pages, usage: Usage) -> None:
    for data in pages:
        for bucket in data.get("data", []):
            day = bucket["starting_at"][:10]
            for r in bucket.get("results", []):
                cc = r.get("cache_creation") or {}
                usage.add(
                    day, r.get("model") or "?",
                    input=r.get("uncached_input_tokens", 0),
                    output=r.get("output_tokens", 0),
                    cache_read=r.get("cache_read_input_tokens", 0),
                    cache_write=sum(int(v or 0) for v in cc.values()),
                )


def parse_anthropic_cost(pages, usage: Usage) -> None:
    usage.has_cost = True
    for data in pages:
        for bucket in data.get("data", []):
            day = bucket["starting_at"][:10]
            for r in bucket.get("results", []):
                # Montant en centimes (plus petite unité), chaîne décimale.
                usage.cost_by_day[day] += float(r.get("amount") or 0) / 100.0


def fetch_anthropic(admin_key: str, days: int) -> Usage:
    usage = Usage("Claude (API)")
    h = {"x-api-key": admin_key, "anthropic-version": "2023-06-01"}
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=days)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    base = "https://api.anthropic.com/v1/organizations"
    common = [("starting_at", iso(start)), ("ending_at", iso(end)), ("bucket_width", "1d")]
    parse_anthropic_usage(
        _paged(f"{base}/usage_report/messages", common + [("group_by[]", "model"), ("limit", "31")], h), usage)
    parse_anthropic_cost(_paged(f"{base}/cost_report", common + [("limit", "31")], h), usage)
    return usage


# ---------- Claude Code (local) ----------

def claude_code_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def read_claude_code(days: int, root: Path | None = None) -> Usage:
    usage = Usage("Claude Code (local)")
    root = root or claude_code_dir()
    if not root.exists():
        return usage
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    seen: set = set()
    for f in root.rglob("*.jsonl"):
        try:
            lines = f.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with lines:
            for line in lines:
                if '"usage"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                msg = e.get("message") or {}
                u = msg.get("usage")
                ts = (e.get("timestamp") or "")[:10]
                if not isinstance(u, dict) or not ts or ts < since:
                    continue
                key = (msg.get("id"), e.get("requestId"))
                if key[0] and key in seen:  # lignes dupliquées du streaming
                    continue
                seen.add(key)
                usage.add(
                    ts, msg.get("model") or "?",
                    input=u.get("input_tokens", 0),
                    output=u.get("output_tokens", 0),
                    cache_read=u.get("cache_read_input_tokens", 0),
                    cache_write=u.get("cache_creation_input_tokens", 0),
                    requests=1,
                )
    return usage


# ---------- OpenAI ----------

def parse_openai_usage(pages, usage: Usage) -> None:
    for data in pages:
        for bucket in data.get("data", []):
            day = datetime.fromtimestamp(bucket["start_time"], timezone.utc).strftime("%Y-%m-%d")
            for r in bucket.get("results", []):
                cached = int(r.get("input_cached_tokens") or 0)
                usage.add(
                    day, r.get("model") or "?",
                    input=int(r.get("input_tokens") or 0) - cached,
                    output=r.get("output_tokens", 0),
                    cache_read=cached,
                    requests=r.get("num_model_requests", 0),
                )


def parse_openai_cost(pages, usage: Usage) -> None:
    usage.has_cost = True
    for data in pages:
        for bucket in data.get("data", []):
            day = datetime.fromtimestamp(bucket["start_time"], timezone.utc).strftime("%Y-%m-%d")
            for r in bucket.get("results", []):
                usage.cost_by_day[day] += float((r.get("amount") or {}).get("value") or 0)


def fetch_openai(admin_key: str, days: int) -> Usage:
    usage = Usage("ChatGPT / OpenAI (API)")
    h = {"Authorization": f"Bearer {admin_key}"}
    start = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    base = "https://api.openai.com/v1/organization"
    common = [("start_time", str(start)), ("bucket_width", "1d")]
    parse_openai_usage(
        _paged(f"{base}/usage/completions", common + [("group_by", "model"), ("limit", "31")], h), usage)
    parse_openai_cost(_paged(f"{base}/costs", common + [("limit", "180")], h), usage)
    return usage
