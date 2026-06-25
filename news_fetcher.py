#!/usr/bin/env python3
"""
news_fetcher.py — Multi-source Indian financial news pipeline

Fetches from 9 concurrent RSS sources, deduplicates, scores by relevance,
and builds structured context for Claude prompts.

Sources:
  1. Zerodha Pulse RSS
  2. Mint Markets RSS
  3. Mint Economy RSS
  4. Mint Companies RSS
  5. Economic Times Markets RSS
  6. Economic Times Economy RSS
  7. MoneyControl Top News RSS
  8. SEBI RSS / Circulars
  9. RBI Press Releases RSS

Deduplication: 4+ consecutive word match between headlines.
Scoring: Regulatory > Capital Flows > Market > Macro > General.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

try:
    import feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False
    print("  [News] feedparser not installed — pip install feedparser")

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UndeployedCapital/1.0; +https://undeployedcapital.com)"}
FETCH_TIMEOUT = 12
MAX_AGE_HOURS = 24

NEWS_SOURCES = [
    ("Zerodha Pulse",  "https://pulse.zerodha.com/feed"),
    ("Mint Markets",   "https://www.livemint.com/rss/markets"),
    ("Mint Economy",   "https://www.livemint.com/rss/economy"),
    ("Mint Companies", "https://www.livemint.com/rss/companies"),
    ("ET Markets",     "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Economy",     "https://economictimes.indiatimes.com/economy/rssfeeds/1373380680.cms"),
    ("MoneyControl",   "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("SEBI",           "https://www.sebi.gov.in/rss/sebi.xml"),
    ("RBI",            "https://www.rbi.org.in/rss/PressReleases.xml"),
]

# ─────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────

_REGULATORY_KW = [
    "SEBI", "RBI", "circular", "regulation", "compliance", "notification",
    "repo rate", "CRR", "SLR", "NBFC", "AMC", "mutual fund", "AMFI",
    "IRDAI", "PFRDA", "guidelines", "directive", "penalty", "enforcement",
]
_MARKET_KW = [
    "Nifty", "Sensex", "rally", "selloff", "crash", "surge", "FII", "DII",
    "earnings", "results", "quarterly", "IPO", "merger", "acquisition",
    "buyback", "dividend", "block deal", "bulk deal",
]
_VC_STARTUP_KW = [
    "startup", "funding", "unicorn", "venture capital", "VC", "series A",
    "series B", "series C", "pre-IPO", "angel", "seed round", "fintech",
    "edtech", "healthtech", "SaaS", "Zomato", "Paytm", "Nykaa", "CRED",
    "Meesho", "Flipkart", "OYO", "Byju", "Swiggy", "PhonePe",
]
_MACRO_KW = [
    "GDP", "inflation", "CPI", "WPI", "trade deficit", "fiscal deficit",
    "current account", "monetary policy", "budget", "crude oil", "rupee",
    "dollar", "DXY", "Fed", "US Federal Reserve", "interest rate",
]


def _score_item(title: str, summary: str = "") -> Tuple[int, str]:
    """Score a news item. Returns (score 0-100, category string)."""
    text = (title + " " + summary).lower()

    reg  = sum(1 for kw in _REGULATORY_KW  if kw.lower() in text)
    mkt  = sum(1 for kw in _MARKET_KW      if kw.lower() in text)
    vc   = sum(1 for kw in _VC_STARTUP_KW  if kw.lower() in text)
    mac  = sum(1 for kw in _MACRO_KW        if kw.lower() in text)

    if reg >= 2:
        return (90 + min(reg, 5), "regulatory")
    if reg == 1:
        return (70 + mkt * 5,     "regulatory")
    if vc >= 1:
        return (65 + vc * 5 + mkt * 3, "capital_flows")
    if mkt >= 3:
        return (60 + mkt * 3,    "market")
    if mac >= 2:
        return (55 + mac * 5,    "macro")
    if mkt >= 1:
        return (40 + mkt * 5,    "market")
    return (20, "general")


# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────

def _is_duplicate(title: str, seen_titles: List[str], min_consecutive: int = 4) -> bool:
    """True if title shares 4+ consecutive words with any seen title."""
    words = re.findall(r"\w+", title.lower())
    if len(words) < min_consecutive:
        return False
    for seen in seen_titles:
        seen_words = re.findall(r"\w+", seen.lower())
        seen_str = " ".join(seen_words)
        for i in range(len(words) - min_consecutive + 1):
            window = " ".join(words[i:i + min_consecutive])
            if window in seen_str:
                return True
    return False


# ─────────────────────────────────────────────
# RSS FETCHING
# ─────────────────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    """Extract UTC datetime from feedparser entry."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_rss_source(source_name: str, url: str) -> List[dict]:
    """Fetch one RSS feed. Returns list of item dicts."""
    if not _FEEDPARSER_OK:
        return []
    items = []
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=MAX_AGE_HOURS)

        for entry in feed.entries[:25]:
            title = entry.get("title", "").strip()
            if not title or len(title) < 20:
                continue

            pub_date = _parse_date(entry)
            if pub_date and pub_date < cutoff:
                continue

            summary = entry.get("summary", entry.get("description", ""))
            summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]
            link = entry.get("link", "")
            score, category = _score_item(title, summary)

            items.append({
                "title":     title,
                "summary":   summary,
                "link":      link,
                "source":    source_name,
                "published": pub_date.isoformat() if pub_date else "",
                "score":     score,
                "category":  category,
            })
    except Exception as e:
        print(f"  [News] {source_name}: {e}")
    return items


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def fetch_all_news(max_workers: int = 4) -> List[dict]:
    """
    Fetch all sources concurrently, deduplicate, sort by score.
    Returns list of item dicts (highest score first).
    """
    all_items: List[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_rss_source, name, url): name
            for name, url in NEWS_SOURCES
        }
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"  [News] {source_name}: {len(items)} items")
            except Exception as e:
                print(f"  [News] {source_name} exception: {e}")

    # Deduplicate (highest score wins)
    all_items.sort(key=lambda x: x["score"], reverse=True)
    seen_titles: List[str] = []
    deduped: List[dict] = []
    for item in all_items:
        if not _is_duplicate(item["title"], seen_titles):
            deduped.append(item)
            seen_titles.append(item["title"])

    return deduped


def build_claude_context(news_items: List[dict], top_n: int = 25) -> str:
    """
    Format top news items for Claude prompts grouped by category.
    Every item includes source attribution as required.
    """
    if not news_items:
        return "No news items available."

    by_cat: Dict[str, List[dict]] = {}
    for item in news_items[:top_n]:
        cat = item.get("category", "general")
        by_cat.setdefault(cat, []).append(item)

    cat_labels = {
        "regulatory":    "REGULATORY (SEBI / RBI)",
        "capital_flows": "CAPITAL FLOWS & STARTUPS",
        "market":        "MARKET MOVES",
        "macro":         "MACRO",
        "general":       "GENERAL",
    }

    lines: List[str] = []
    for cat in ["regulatory", "capital_flows", "market", "macro", "general"]:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"\n## {cat_labels.get(cat, cat.upper())}")
        for item in items[:6]:
            line = f"- {item['title']} (Source: {item['source']})"
            if item.get("summary"):
                line += f"\n  Context: {item['summary'][:150]}"
            lines.append(line)

    return "\n".join(lines) if lines else "No categorized news available."


def get_regulatory_items(news_items: List[dict], top_n: int = 8) -> List[dict]:
    """SEBI/RBI items for Regulatory Watch section."""
    return [i for i in news_items if i.get("category") == "regulatory"][:top_n]


def get_capital_flow_items(news_items: List[dict], top_n: int = 8) -> List[dict]:
    """VC/startup/capital flow items for Capital Flows section."""
    return [i for i in news_items if i.get("category") == "capital_flows"][:top_n]


def get_sources_used(news_items: List[dict]) -> List[str]:
    """Unique source names that contributed at least one item."""
    seen = set()
    sources = []
    for item in news_items:
        s = item.get("source", "")
        if s and s not in seen:
            seen.add(s)
            sources.append(s)
    return sources


if __name__ == "__main__":
    print("Testing news pipeline...")
    items = fetch_all_news()
    print(f"\n✅ Total unique items: {len(items)}")
    print(f"   Regulatory: {len(get_regulatory_items(items))}")
    print(f"   Capital flows: {len(get_capital_flow_items(items))}")
    print(f"   Sources: {', '.join(get_sources_used(items))}")
    print("\n" + "=" * 60)
    print(build_claude_context(items, top_n=15)[:1500])
