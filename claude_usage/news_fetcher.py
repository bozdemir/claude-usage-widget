"""Fetches recent Anthropic/Claude news from RSS and caches locally.

Network call happens at most once per hour. Falls back silently if offline.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# Sources tried in order; first successful fetch wins.
NEWS_RSS_SOURCES = [
    "https://hnrss.org/newest?q=anthropic&points=50&count=10",  # at least 50 upvotes
    "https://hnrss.org/newest?q=claude&points=50&count=10",     # fallback: claude keyword
    "https://www.reddit.com/r/ClaudeAI.rss",                    # last resort
]
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_NEWS_ITEMS = 8


def _cache_file() -> str:
    """Cache path under the same config root as config.py (honours
    XDG_CONFIG_HOME, unlike a hardcoded ~/.config)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claude-usage", "news-cache.json")


@dataclass
class NewsItem:
    ts: float
    title: str
    url: str


def _load_cache() -> tuple[float, list[NewsItem]] | None:
    try:
        with open(_cache_file(), encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = float(data["fetched_at"])
        items = [NewsItem(ts=float(i["ts"]), title=i["title"], url=i["url"]) for i in data["items"]]
        return fetched_at, items
    except Exception:
        return None


def _save_cache(items: list[NewsItem]) -> None:
    try:
        os.makedirs(os.path.dirname(_cache_file()), exist_ok=True)
        with open(_cache_file(), "w", encoding="utf-8") as f:
            json.dump({
                "fetched_at": time.time(),
                "items": [{"ts": i.ts, "title": i.title, "url": i.url} for i in items],
            }, f)
    except Exception:
        pass


def _parse_entries(raw: bytes) -> list[NewsItem]:
    from datetime import datetime, timezone
    root = ET.fromstring(raw)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[NewsItem] = []
    atom_entries = root.findall(".//atom:entry", ns)
    entries = atom_entries if atom_entries else root.findall(".//item")
    for entry in entries[:MAX_NEWS_ITEMS]:
        title_el = entry.find("atom:title", ns)
        if title_el is None:
            title_el = entry.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        link_el = entry.find("atom:link", ns)
        if link_el is not None:
            item_url = link_el.get("href", "")
        else:
            link_el = entry.find("link")
            item_url = (link_el.text or "").strip() if link_el is not None else ""

        pub_el = (entry.find("atom:published", ns)
                  or entry.find("atom:updated", ns)
                  or entry.find("pubDate"))
        ts = time.time()
        if pub_el is not None and pub_el.text:
            raw_date = pub_el.text.strip()
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
                try:
                    dt = datetime.strptime(raw_date, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = dt.timestamp()
                    break
                except ValueError:
                    continue

        items.append(NewsItem(ts=ts, title=title, url=item_url))
    return items


def _fetch_rss() -> list[NewsItem]:
    # Reuse the collector's certifi-backed SSL context: without it, macOS
    # python.org builds fail CERTIFICATE_VERIFY_FAILED on every source and
    # the bare except turns that into a permanently empty news strip.
    from claude_usage.collector import _ssl_context
    for source_url in NEWS_RSS_SOURCES:
        try:
            req = urllib.request.Request(
                source_url, headers={"User-Agent": "claude-usage-widget"})
            with urllib.request.urlopen(req, timeout=8, context=_ssl_context()) as resp:
                raw = resp.read()
            if raw:
                return _parse_entries(raw)
        except Exception:
            continue
    return []


def get_news_items(force_refresh: bool = False) -> list[NewsItem]:
    """Return cached news items, refreshing if the cache is stale."""
    cached = _load_cache()
    if cached and not force_refresh:
        fetched_at, items = cached
        if time.time() - fetched_at < CACHE_TTL_SECONDS:
            return items

    items = _fetch_rss()
    if items:
        _save_cache(items)
        return items

    # Network failed — return stale cache if available
    if cached:
        return cached[1]
    return []


__all__ = ["NewsItem", "get_news_items"]
