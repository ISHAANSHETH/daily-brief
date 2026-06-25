#!/usr/bin/env python3
"""
data_fetcher.py — Undeployed Capital Daily Brief
Phase 1 + Phase 2 data pipeline

Run this on your Mac at 4:30 PM IST on trading days.
It outputs a structured JSON that feeds into brief_generator.py

Requirements:
    pip install yfinance requests beautifulsoup4 pandas

External access needed (all free, no API keys):
    - finance.yahoo.com (yfinance) — indices, stocks, commodities, FX
    - nseindia.com — FII/DII flows, gainers/losers, corporate actions
    - aftermarketreport.zerodha.com — scrape latest AMR post for news bullets
"""

import yfinance as yf
import requests
import json
import time
import re
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# Optional: Kite Connect and news pipeline (fail gracefully if unavailable)
try:
    import kite_client as _kc
    _KITE_MODULE_OK = True
except ImportError:
    _KITE_MODULE_OK = False

try:
    import news_fetcher as _nf
    _NEWS_MODULE_OK = True
except ImportError:
    _NEWS_MODULE_OK = False

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

OUTPUT_FILE = "brief_data.json"

# Set True when NSE returns 403 — all NSE functions fall back to mock data
_NSE_BLOCKED = False

# NSE session headers — required to avoid 403s
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────────────────────────────────────────
# THEMATIC BASKETS — your Undeployed Capital differentiator
# These are the 5 baskets DayStarter doesn't have.
# Add/remove tickers as your coverage evolves.
# ─────────────────────────────────────────────────────────────────────────────

THEMATIC_BASKETS = {
    "VC/Startup Ecosystem": [
        "ZOMATO.NS", "NYKAA.NS", "PAYTM.NS", "POLICYBZR.NS",
        "DELHIVERY.NS", "CARTRADE.NS"
    ],
    "Defense": [
        "HAL.NS", "BEL.NS", "MAZDOCK.NS", "GRSE.NS", "COCHINSHIP.NS"
    ],
    "Diagnostics": [
        "LALPATHLAB.NS", "METROPOLIS.NS", "VIJAYA.NS",
        "THYROCARE.NS", "KRSNAA.NS"
    ],
    "AI / Tech": [
        "INFY.NS", "TCS.NS", "WIPRO.NS", "HCLTECH.NS", "LTIM.NS"
    ],
    "PLI / Manufacturing": [
        "DIXON.NS", "AMBER.NS", "KAYNES.NS", "SYRMA.NS", "AVALON.NS"
    ],
}

# ─────────────────────────────────────────────
# SECTION 1 — INDICES & SECTORS (yfinance)
# ─────────────────────────────────────────────

SECTOR_TICKERS = {
    "Nifty 50":     "^NSEI",
    "Sensex":       "^BSESN",
    "Nifty Bank":   "^NSEBANK",
    "Nifty IT":     "^CNXIT",
    "Nifty Pharma": "^CNXPHARMA",
    "Nifty Metal":  "^CNXMETAL",
    "Nifty FMCG":   "^CNXFMCG",
    "Nifty Auto":   "^CNXAUTO",
    "Nifty Realty": "^CNXREALTY",
    "Nifty Energy": "^CNXENERGY",
}

COMMODITY_TICKERS = {
    "Gold (₹/10g)":     "GC=F",      # USD — will convert
    "Silver (₹/kg)":    "SI=F",      # USD — will convert
    "Crude Oil (₹/bbl)":"CL=F",      # USD — will convert
    "Natural Gas":       "NG=F",
}

FX_TICKERS = {
    "USD/INR":  "USDINR=X",
    "EUR/INR":  "EURINR=X",
}

BOND_TICKERS = {
    "US 10Y Yield":    "^TNX",
    "India 10Y Yield": "^INBMK10Y",   # may not always be available
}

GLOBAL_TICKERS = {
    "S&P 500":    "^GSPC",
    "Nasdaq 100": "^NDX",
    "Dow Jones":  "^DJI",
    "Nikkei 225": "^N225",
    "FTSE 100":   "^FTSE",
    "Shanghai":   "000001.SS",
    "Hang Seng":  "^HSI",
}


def _mock_fii_dii() -> dict:
    return {
        "date": str(date.today()),
        "fii_net_cr": -1250.5, "dii_net_cr": 980.3,
        "fii_5d_cr": -3200.0, "dii_5d_cr": 2800.0,
        "fii_buy": 8500.0, "fii_sell": 9750.5,
        "dii_buy": 7200.0, "dii_sell": 6219.7,
        "_mock": True,
    }

def _mock_gainers_losers() -> dict:
    return {
        "index": "NIFTY 50 (MOCK)",
        "gainers": [
            {"symbol": "RELIANCE", "name": "Reliance Industries", "ltp": 2850.0, "change_pct": 1.8, "change_abs": 50.0},
            {"symbol": "INFY", "name": "Infosys", "ltp": 1650.0, "change_pct": 1.5, "change_abs": 24.5},
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "ltp": 1720.0, "change_pct": 1.2, "change_abs": 20.4},
            {"symbol": "TCS", "name": "TCS", "ltp": 3890.0, "change_pct": 0.9, "change_abs": 34.8},
            {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "ltp": 7200.0, "change_pct": 0.7, "change_abs": 50.0},
        ],
        "losers": [
            {"symbol": "TATASTEEL", "name": "Tata Steel", "ltp": 142.0, "change_pct": -2.1, "change_abs": -3.0},
            {"symbol": "HINDALCO", "name": "Hindalco", "ltp": 590.0, "change_pct": -1.8, "change_abs": -10.8},
            {"symbol": "JSWSTEEL", "name": "JSW Steel", "ltp": 820.0, "change_pct": -1.5, "change_abs": -12.5},
            {"symbol": "COALINDIA", "name": "Coal India", "ltp": 455.0, "change_pct": -1.2, "change_abs": -5.5},
            {"symbol": "ONGC", "name": "ONGC", "ltp": 265.0, "change_pct": -0.9, "change_abs": -2.4},
        ],
        "_mock": True,
    }

def _mock_market_status() -> dict:
    return {
        "india_vix": {"last": 13.5, "change_pct": -2.1, "prev": 13.79},
        "nifty_advances": "28", "nifty_declines": "22", "nifty_unchanged": "0",
        "vix_label": "Low Fear",
        "_mock": True,
    }

def _mock_corporate_actions() -> list:
    return []

def _mock_earnings_calendar() -> list:
    return []


def fetch_bse_corporate_announcements() -> list:
    """
    Fetch recent corporate announcements from BSE India API.
    Works from outside India — no session cookie needed.
    Fills the gap when NSE is blocked.
    """
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        "?pageno=1&strCat=-1&strPrevDate=&strScrip=&strSearch=P"
        "&strToDate=&strType=C&subcategory=-1"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer":    "https://www.bseindia.com/",
        "Accept":     "application/json",
    }
    try:
        r = requests.get(url, timeout=20, headers=headers)
        r.raise_for_status()
        data = r.json()
        items = data.get("Table", [])
        results = []
        for item in items[:20]:
            headline = item.get("HEADLINE", "").strip()
            company  = item.get("SLONGNAME", item.get("short_name", "")).strip()
            symbol   = str(item.get("SCRIP_CD", "")).strip()
            dt       = item.get("NEWS_DT", item.get("DT_TM", "")).strip()
            if not headline:
                continue
            # Filter for earnings/results/board meeting
            if any(kw in headline.upper() for kw in [
                "RESULT", "FINANCIAL", "QUARTERLY", "DIVIDEND",
                "BOARD MEETING", "BONUS", "SPLIT", "RIGHTS",
            ]):
                results.append({
                    "company":     company,
                    "symbol":      str(symbol),
                    "purpose":     headline[:100],
                    "ex_date":     dt[:10],
                    "record_date": "",
                    "_source":     "bse",
                })
        return results
    except Exception as e:
        print(f"  [BSE announcements error] {e}")
        return []


def fetch_yfinance_batch(tickers_dict: dict, period: str = "2d") -> dict:
    """
    Fetch a batch of tickers using yfinance.
    Returns dict of {name: {last_price, prev_close, change_pct, high, low}}
    
    IMPORTANT: Change% uses last_price vs prev_close (not open vs close).
    The uploaded example script had this wrong — using open as base.
    """
    results = {}
    symbols = list(tickers_dict.values())
    names = list(tickers_dict.keys())

    try:
        raw = yf.download(
            symbols,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"  [yfinance batch error] {e}")
        return results

    for name, symbol in tickers_dict.items():
        try:
            if len(symbols) == 1:
                df = raw
            else:
                df = raw[symbol] if symbol in raw.columns.get_level_values(0) else pd.DataFrame()

            if df is None or df.empty or len(df) < 1:
                results[name] = None
                continue

            df = df.dropna(subset=["Close"])
            if len(df) < 1:
                results[name] = None
                continue

            last_price  = float(df["Close"].iloc[-1])
            prev_close  = float(df["Close"].iloc[-2]) if len(df) >= 2 else last_price
            high        = float(df["High"].iloc[-1])
            low         = float(df["Low"].iloc[-1])
            open_price  = float(df["Open"].iloc[-1])

            # Correct formula: day-over-day change vs previous close
            change_pct  = ((last_price - prev_close) / prev_close) * 100 if prev_close else 0
            change_abs  = last_price - prev_close

            results[name] = {
                "last_price":  round(last_price, 2),
                "prev_close":  round(prev_close, 2),
                "change_pct":  round(change_pct, 2),
                "change_abs":  round(change_abs, 2),
                "high":        round(high, 2),
                "low":         round(low, 2),
                "open":        round(open_price, 2),
            }
        except Exception as e:
            print(f"  [parse error] {name} ({symbol}): {e}")
            results[name] = None

    return results


def compute_pivot_points(high: float, low: float, close: float) -> dict:
    """
    Standard pivot point calculation (floor method).
    Used for Nifty 50 key levels section.
    """
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)
    s1 = (2 * pivot) - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)

    return {
        "pivot": round(pivot, 2),
        "R1": round(r1, 2),
        "R2": round(r2, 2),
        "R3": round(r3, 2),
        "S1": round(s1, 2),
        "S2": round(s2, 2),
        "S3": round(s3, 2),
    }


# ─────────────────────────────────────────────
# SECTION 2 — NSE SCRAPER (FII/DII, Gainers/Losers, Corp Actions)
# ─────────────────────────────────────────────

def _get_nse_session() -> requests.Session:
    """
    NSE requires a valid browser session (cookie) before accepting API calls.
    This is the standard workaround — visit homepage first, then hit JSON endpoints.
    Sets _NSE_BLOCKED=True if we get a 403 (common outside India / in sandboxes).
    """
    global _NSE_BLOCKED
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        resp = session.get("https://www.nseindia.com", timeout=10)
        if resp.status_code == 403:
            _NSE_BLOCKED = True
            print("  [NSE] 403 received — switching to mock data for all NSE endpoints.")
        time.sleep(1)
    except Exception as e:
        print(f"  [NSE session warning] Could not establish session: {e}")
        _NSE_BLOCKED = True
        print("  [NSE] Session failed — switching to mock data for all NSE endpoints.")
    return session


def fetch_nse_fii_dii(session: requests.Session) -> dict:
    """
    Fetch FII/DII provisional institutional flows from NSE.
    Endpoint: /api/fiidiiTradeReact

    This endpoint works without a session cookie (no Referer block),
    so we try it directly even when NSE homepage returns 403.
    Returns daily and rolling 5-day net figures.
    Source: NSE India (official, free)
    """
    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    # Always try the API directly — it works without session cookie even outside India
    direct_headers = {
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        r = requests.get(url, timeout=10, headers=direct_headers)
        r.raise_for_status()
        data = r.json()

        # Response: flat list of {category, buyValue, sellValue, netValue, date}
        # Each trading day has 2 entries: one for FII/FPI and one for DII
        if not data:
            return _mock_fii_dii()

        def _extract(entries, cat_prefix):
            """Sum buy/sell/net for entries matching a category prefix."""
            matches = [e for e in entries if cat_prefix in e.get("category", "").upper()]
            if not matches:
                return 0.0, 0.0, 0.0
            buy  = sum(float(e.get("buyValue", 0) or 0) for e in matches)
            sell = sum(float(e.get("sellValue", 0) or 0) for e in matches)
            net  = sum(float(e.get("netValue", 0) or 0) for e in matches)
            return buy, sell, net

        # Group by date (each date has 2 rows: FII/FPI + DII)
        from collections import defaultdict
        by_date = defaultdict(list)
        for row in data:
            by_date[row.get("date", "")].append(row)

        dates = sorted(by_date.keys(), reverse=True)
        if not dates:
            return _mock_fii_dii()

        today_date   = dates[0]
        today_rows   = by_date[today_date]
        date_str     = today_date

        fii_buy, fii_sell, fii_net = _extract(today_rows, "FII")
        dii_buy, dii_sell, dii_net = _extract(today_rows, "DII")

        # 5-day rolling net
        fii_5d = sum(
            _extract(by_date[d], "FII")[2] for d in dates[:5]
        )
        dii_5d = sum(
            _extract(by_date[d], "DII")[2] for d in dates[:5]
        )

        result = {
            "date":       date_str,
            "fii_net_cr": round(fii_net, 1),
            "dii_net_cr": round(dii_net, 1),
            "fii_5d_cr":  round(fii_5d, 1),
            "dii_5d_cr":  round(dii_5d, 1),
            "fii_buy":    round(fii_buy, 1),
            "fii_sell":   round(fii_sell, 1),
            "dii_buy":    round(dii_buy, 1),
            "dii_sell":   round(dii_sell, 1),
        }
        print(f"  [FII/DII] {date_str}: FII {fii_net:+,.0f} Cr | DII {dii_net:+,.0f} Cr")
        return result
    except Exception as e:
        print(f"  [FII/DII error] {e}")
        return _mock_fii_dii()


def fetch_nse_gainers_losers(session: requests.Session, index: str = "NIFTY 50") -> dict:
    """
    Fetch top gainers and losers for a given NSE index.
    Endpoint: /api/live-analysis-variations

    Returns top 5 gainers and top 5 losers with %, abs change.
    """
    if _NSE_BLOCKED:
        return _mock_gainers_losers()
    url = f"https://www.nseindia.com/api/live-analysis-variations?index={index.replace(' ', '%20')}"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        gainers_raw = data.get("gainers", {}).get("data", [])
        losers_raw  = data.get("losers", {}).get("data", [])

        def parse(items, n=5):
            out = []
            for item in items[:n]:
                out.append({
                    "symbol":     item.get("symbol", ""),
                    "name":       item.get("companyName", item.get("symbol", "")),
                    "ltp":        float(item.get("ltp", 0)),
                    "change_pct": float(item.get("perChange", 0)),
                    "change_abs": float(item.get("netPrice", 0)),
                })
            return out

        return {
            "index":   index,
            "gainers": parse(gainers_raw),
            "losers":  parse(losers_raw),
        }
    except Exception as e:
        print(f"  [Gainers/Losers error] {e}")
        return {"gainers": [], "losers": []}


def fetch_nse_corporate_actions(session: requests.Session) -> list:
    """
    Fetch upcoming corporate actions (dividends, splits, bonuses)
    for the next 7 days from NSE official endpoint.
    """
    if _NSE_BLOCKED:
        return _mock_corporate_actions()
    today   = date.today()
    in_7d   = today + timedelta(days=7)
    url = (
        f"https://www.nseindia.com/api/corporates-corporateActions"
        f"?index=equities&from_date={today.strftime('%d-%m-%Y')}"
        f"&to_date={in_7d.strftime('%d-%m-%Y')}&csv=false"
    )
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        actions = []
        for item in data[:20]:  # cap at 20
            actions.append({
                "company":     item.get("comp", ""),
                "symbol":      item.get("symbol", ""),
                "purpose":     item.get("subject", ""),
                "ex_date":     item.get("exDate", ""),
                "record_date": item.get("recDate", ""),
            })
        return actions
    except Exception as e:
        print(f"  [Corp actions error] {e}")
        return []


def _vix_label(vix_val: float) -> str:
    if vix_val < 15:   return "Low Fear"
    if vix_val < 20:   return "Moderate"
    if vix_val < 25:   return "Elevated"
    return "High Fear"


def fetch_nse_market_status(session: requests.Session) -> dict:
    """
    Check if market is open, get market status and VIX.
    India VIX is the fear gauge — equivalent to sentiment indicator.
    Adds vix_label: Low Fear / Moderate / Elevated / High Fear.
    """
    if _NSE_BLOCKED:
        return _mock_market_status()
    url = "https://www.nseindia.com/api/allIndices"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        result = {"india_vix": None, "advance_decline": None}

        for item in data.get("data", []):
            idx_name = item.get("index", "")
            if "INDIA VIX" in idx_name.upper():
                vix_last = float(item.get("last", 0))
                result["india_vix"] = {
                    "last":       vix_last,
                    "change_pct": float(item.get("percentChange", 0)),
                    "prev":       float(item.get("previousClose", 0)),
                }
                result["vix_label"] = _vix_label(vix_last)
            if "NIFTY 50" == idx_name.upper():
                result["nifty_advances"]  = item.get("advances", "")
                result["nifty_declines"]  = item.get("declines", "")
                result["nifty_unchanged"] = item.get("unchanged", "")

        return result
    except Exception as e:
        print(f"  [Market status error] {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — ZERODHA AFTERMARKET REPORT SCRAPER
#
# DayStarter's primary source is the Zerodha AMR. Instead of calling APIs
# for news, we scrape the latest AMR Substack post and extract:
#   - Management quotes
#   - Top corporate headlines
#   - Global market bullets
#
# This is journalism (read + attribute), not redistribution.
# We always attribute: "Source: Zerodha AfterMarket Report"
# ─────────────────────────────────────────────────────────────────────────────

def fetch_zerodha_amr() -> dict:
    """
    Scrape the latest Zerodha AfterMarket Report from Substack.
    
    Strategy:
      1. Hit the Substack RSS feed to get latest post URL
      2. Fetch the post HTML
      3. Extract key sections: management quotes, top stories, global markets
    
    The AMR is free to read — we're reading it programmatically
    the same way a human would, and attributing every item.
    """
    result = {
        "url": None,
        "date": None,
        "headline": None,
        "management_quotes": [],
        "top_india_stories": [],
        "global_stories": [],
        "raw_text_excerpt": None,
    }

    # Step 1: Get latest post URL from RSS
    rss_url = "https://aftermarketreport.zerodha.com/feed"
    try:
        r = requests.get(rss_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        if not items:
            print("  [AMR RSS] No items found")
            return result

        latest = items[0]
        post_url  = latest.find("link").text.strip()
        post_date = latest.find("pubDate").text.strip() if latest.find("pubDate") else ""
        result["url"]  = post_url
        result["date"] = post_date
        print(f"  [AMR] Latest post: {post_url}")
    except Exception as e:
        print(f"  [AMR RSS error] {e}")
        # Fallback: try to get direct from Substack archive
        try:
            archive = requests.get(
                "https://aftermarketreport.zerodha.com/archive",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            soup = BeautifulSoup(archive.text, "html.parser")
            links = soup.find_all("a", href=True)
            post_links = [l["href"] for l in links if "/p/" in l["href"]]
            if post_links:
                post_url = "https://aftermarketreport.zerodha.com" + post_links[0]
                result["url"] = post_url
                print(f"  [AMR fallback] Found post: {post_url}")
            else:
                return result
        except Exception as e2:
            print(f"  [AMR fallback error] {e2}")
            return result

    # Step 2: Fetch the post
    try:
        time.sleep(1)
        r = requests.get(post_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [AMR post fetch error] {e}")
        return result

    # Step 3: Extract content
    # Substack post body is in div.available-content or article
    body = soup.find("div", class_="available-content") or \
           soup.find("article") or \
           soup.find("div", class_="post-content")

    if not body:
        print("  [AMR] Could not find post body")
        return result

    # Headline
    h1 = soup.find("h1")
    if h1:
        result["headline"] = h1.text.strip()

    # Extract all paragraphs for processing
    paragraphs = [p.text.strip() for p in body.find_all("p") if p.text.strip()]
    result["raw_text_excerpt"] = " ".join(paragraphs[:10])  # first 10 paragraphs

    # Extract blockquotes — these are management quotes in AMR
    quotes = body.find_all("blockquote")
    for q in quotes[:5]:
        quote_text = q.text.strip()
        if len(quote_text) > 20:
            result["management_quotes"].append(quote_text[:400])

    # Extract bullet-point stories
    # AMR uses <li> for story bullets in its sections
    all_items = body.find_all("li")
    india_stories = []
    global_stories = []

    for li in all_items:
        text = li.text.strip()
        if len(text) < 30:
            continue
        # Heuristic: global stories mention foreign countries/indices
        global_keywords = [
            "US ", "Fed ", "S&P", "Nasdaq", "Dow", "Nikkei", "China",
            "Europe", "ECB", "UK", "Japan", "dollar", "Wall Street"
        ]
        if any(kw in text for kw in global_keywords):
            global_stories.append(text[:250])
        else:
            india_stories.append(text[:250])

    result["top_india_stories"] = india_stories[:10]
    result["global_stories"]    = global_stories[:8]

    return result


def fetch_pulse_zerodha_headlines() -> list:
    """
    Zerodha Pulse (pulse.zerodha.com) aggregates Indian finance news in real time.
    Scrape the 10 most recent headlines as a news context layer.
    
    These are used by Claude to write the macro and corporate sections.
    """
    headlines = []
    try:
        r = requests.get(
            "https://pulse.zerodha.com",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        soup = BeautifulSoup(r.text, "html.parser")

        # Pulse lists headlines in <li> or article cards
        items = soup.find_all(["li", "article", "div"], class_=re.compile(r"story|news|item|headline", re.I))
        for item in items[:20]:
            text = item.get_text(separator=" ", strip=True)
            if len(text) > 40:
                headlines.append(text[:200])

        # Fallback: just grab all <a> tags with substantial text
        if not headlines:
            for a in soup.find_all("a", href=True):
                text = a.text.strip()
                if len(text) > 50 and len(text) < 200:
                    headlines.append(text)

        return headlines[:15]
    except Exception as e:
        print(f"  [Pulse error] {e}")
        return []


# ─────────────────────────────────────────────
# SECTION 4 — THEMATIC BASKETS (Phase 2)
# ─────────────────────────────────────────────

def fetch_thematic_performance(baskets: dict) -> dict:
    """
    Calculate performance for each thematic basket.
    
    For each basket:
      - Fetch all constituent tickers
      - Calculate equal-weighted 1-day return
      - Find top performer within basket
      - Find worst performer within basket
    
    This is the Undeployed Capital differentiator — DayStarter doesn't do this.
    """
    results = {}

    for theme_name, tickers in baskets.items():
        print(f"  [Thematic] Fetching {theme_name}...")
        try:
            raw = yf.download(
                tickers,
                period="2d",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

            if raw.empty:
                results[theme_name] = None
                continue

            close = raw["Close"] if "Close" in raw.columns else raw
            if hasattr(close, "columns"):
                # Multi-ticker
                stock_changes = {}
                for ticker in tickers:
                    col = ticker if ticker in close.columns else None
                    if col and len(close[col].dropna()) >= 2:
                        vals = close[col].dropna()
                        pct = ((vals.iloc[-1] - vals.iloc[-2]) / vals.iloc[-2]) * 100
                        stock_changes[ticker.replace(".NS", "")] = round(float(pct), 2)

                if not stock_changes:
                    results[theme_name] = None
                    continue

                basket_return = sum(stock_changes.values()) / len(stock_changes)
                top     = max(stock_changes, key=stock_changes.get)
                worst   = min(stock_changes, key=stock_changes.get)

                results[theme_name] = {
                    "basket_return_pct": round(basket_return, 2),
                    "constituents":      stock_changes,
                    "top_performer":     {"symbol": top,   "change_pct": stock_changes[top]},
                    "worst_performer":   {"symbol": worst, "change_pct": stock_changes[worst]},
                    "num_stocks":        len(stock_changes),
                }
            else:
                # Single ticker fallback
                if len(close.dropna()) >= 2:
                    pct = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2]) * 100
                    sym = tickers[0].replace(".NS", "")
                    results[theme_name] = {
                        "basket_return_pct": round(float(pct), 2),
                        "constituents":      {sym: round(float(pct), 2)},
                        "top_performer":     {"symbol": sym, "change_pct": round(float(pct), 2)},
                        "worst_performer":   {"symbol": sym, "change_pct": round(float(pct), 2)},
                        "num_stocks":        1,
                    }
                else:
                    results[theme_name] = None

        except Exception as e:
            print(f"  [Thematic error] {theme_name}: {e}")
            results[theme_name] = None

    return results


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — EARNINGS CALENDAR (NSE Board Meetings = earnings dates in India)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_earnings_calendar(session: requests.Session) -> list:
    """
    In India, companies announce results at Board Meetings.
    NSE publishes upcoming board meeting dates officially.

    Endpoint: /api/home-corporate-overview-events
    This is what powers the NSE website's corporate calendar.
    """
    if _NSE_BLOCKED:
        return _mock_earnings_calendar()
    today = date.today()
    in_14d = today + timedelta(days=14)
    url = (
        f"https://www.nseindia.com/api/home-corporate-overview-events"
        f"?index=equities&from_date={today.strftime('%d-%m-%Y')}"
        f"&to_date={in_14d.strftime('%d-%m-%Y')}"
    )
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        calendar = []
        for item in data[:15]:
            purpose = item.get("purpose", "") or item.get("bm_purpose", "")
            if any(kw in purpose.upper() for kw in ["RESULT", "FINANCIAL", "QUARTERLY", "DIVIDEND"]):
                calendar.append({
                    "company":   item.get("company", item.get("sm_name", "")),
                    "symbol":    item.get("symbol", ""),
                    "date":      item.get("bm_date", item.get("date", "")),
                    "purpose":   purpose,
                })
        return calendar
    except Exception as e:
        print(f"  [Earnings calendar error] {e}")
        return []


# ─────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def run_full_pipeline() -> dict:
    """
    Run the complete data pipeline and return structured JSON.
    
    Execution order:
      1. NSE session (needed for all NSE endpoints)
      2. Indices + sectors (yfinance)
      3. Commodities + FX + bonds (yfinance)
      4. Global markets (yfinance)
      5. FII/DII flows (NSE)
      6. Gainers/Losers (NSE)
      7. India VIX + market breadth (NSE)
      8. Corporate actions (NSE)
      9. Earnings calendar (NSE)
      10. Thematic baskets (yfinance)
      11. Zerodha AMR scrape (news layer)
      12. Zerodha Pulse headlines (news layer)
    """
    output = {
        "generated_at": datetime.now().isoformat(),
        "trading_date": str(date.today()),
        "data_source":    "yfinance",    # updated to "kite" if Kite used for indices
        "indices":         {},
        "commodities":     {},
        "mcx_commodities": {},           # Kite MCX data in ₹ (separate from USD commodities)
        "fx":              {},
        "bonds":           {},
        "global_markets":  {},
        "fii_dii":         {},
        "gainers_losers":  {},
        "market_status":   {},
        "pivot_points":    {},
        "corporate_actions": [],
        "earnings_calendar": [],
        "thematic_baskets": {},
        "option_chain":     None,        # Kite option chain summary (None if unavailable)
        "zerodha_amr":      {},
        "pulse_headlines":  [],
        "raw_news":         [],          # all scored news items from news_fetcher
        "news_context":     "",          # formatted context string for Claude prompts
        "errors":           [],
    }

    # ── Kite Connect client (optional primary source) ────────────────────────
    kite = None
    if _KITE_MODULE_OK:
        kite = _kc.get_kite_client()
        if kite:
            print("\n  [Kite] ✓ Connected — using Kite Connect as primary data source")
        else:
            print("\n  [Kite] Token stale or unavailable — falling back to yfinance")

    # ── Step 1: NSE session ──────────────────────────────────────────────────
    print("\n[1/14] Establishing NSE session...")
    nse_session = _get_nse_session()

    # ── Step 2: Indices + sectors ────────────────────────────────────────────
    if kite:
        print("[2/14] Fetching indices and sectors (Kite Connect)...")
        kite_indices = _kc.fetch_kite_indices(kite)
        if kite_indices:
            # Merge: Kite has some indices yfinance may have, keep both but Kite wins
            sectors = fetch_yfinance_batch(SECTOR_TICKERS)
            sectors.update({k: v for k, v in kite_indices.items() if v is not None})
            output["data_source"] = "kite"
        else:
            print("  [Kite indices] Empty — falling back to yfinance")
            sectors = fetch_yfinance_batch(SECTOR_TICKERS)
    else:
        print("[2/14] Fetching indices and sectors (yfinance)...")
        sectors = fetch_yfinance_batch(SECTOR_TICKERS)

    output["indices"] = sectors

    # Compute pivot points from Nifty 50 OHLC
    nifty = sectors.get("Nifty 50")
    if nifty:
        output["pivot_points"] = compute_pivot_points(
            nifty["high"], nifty["low"], nifty["last_price"]
        )
        output["pivot_points"]["nifty_current"] = nifty["last_price"]

    # ── Step 3: Commodities + FX + Bonds ────────────────────────────────────
    print("[3/14] Fetching commodities, FX, bond yields (yfinance)...")
    output["commodities"] = fetch_yfinance_batch(COMMODITY_TICKERS)
    output["fx"]          = fetch_yfinance_batch(FX_TICKERS)
    output["bonds"]       = fetch_yfinance_batch(BOND_TICKERS)

    # ── Step 3b: MCX commodities from Kite (₹ prices, separate table) ───────
    if kite:
        print("[3b/14] Fetching MCX commodity futures from Kite (₹)...")
        mcx_data = _kc.fetch_kite_mcx_commodities(kite)
        output["mcx_commodities"] = mcx_data
        if mcx_data:
            present = [k for k, v in mcx_data.items() if v]
            print(f"  [Kite MCX] {len(present)} commodities: {', '.join(present)}")

    # ── Step 4: Global markets ───────────────────────────────────────────────
    print("[4/14] Fetching global markets (yfinance)...")
    output["global_markets"] = fetch_yfinance_batch(GLOBAL_TICKERS)

    # ── Step 5: FII/DII flows ────────────────────────────────────────────────
    print("[5/14] Fetching FII/DII flows from NSE...")
    output["fii_dii"] = fetch_nse_fii_dii(nse_session)

    # ── Step 6: Gainers/Losers ───────────────────────────────────────────────
    if kite:
        print("[6/14] Fetching F&O gainers/losers (Kite Connect)...")
        kite_movers = _kc.fetch_kite_fno_movers(kite)
        output["gainers_losers"] = kite_movers if kite_movers else fetch_nse_gainers_losers(nse_session, "NIFTY 50")
    else:
        print("[6/14] Fetching Nifty 50 gainers/losers from NSE...")
        output["gainers_losers"] = fetch_nse_gainers_losers(nse_session, "NIFTY 50")

    # ── Step 7: VIX + market breadth ────────────────────────────────────────
    print("[7/14] Fetching India VIX and market breadth...")
    output["market_status"] = fetch_nse_market_status(nse_session)

    # If NSE is blocked but Kite has live VIX in indices, use it
    if output["market_status"].get("_mock") and kite:
        kite_vix = (output["indices"].get("India VIX") or {})
        if kite_vix.get("last_price"):
            vix_last = kite_vix["last_price"]
            output["market_status"]["india_vix"] = {
                "last":       vix_last,
                "change_pct": kite_vix.get("change_pct", 0),
                "prev":       kite_vix.get("prev_close", 0),
            }
            output["market_status"]["vix_label"] = _vix_label(vix_last)
            output["market_status"]["_mock"] = False
            output["market_status"]["_vix_source"] = "kite"
            print(f"  [Kite VIX override] India VIX = {vix_last} ({kite_vix.get('change_pct',0):+.2f}%)")

    # ── Step 8: Corporate actions ────────────────────────────────────────────
    print("[8/14] Fetching upcoming corporate actions...")
    corp_acts = fetch_nse_corporate_actions(nse_session)
    if not corp_acts:
        print("  [NSE corp actions] Empty — trying BSE...")
        corp_acts = fetch_bse_corporate_announcements()
        if corp_acts:
            print(f"  [BSE] {len(corp_acts)} corporate announcements")
    output["corporate_actions"] = corp_acts

    # ── Step 9: Earnings calendar ────────────────────────────────────────────
    print("[9/14] Fetching earnings calendar...")
    earnings = fetch_earnings_calendar(nse_session)
    if not earnings and corp_acts:
        # BSE announcements already filtered for results/earnings above
        earnings = [c for c in corp_acts if any(
            kw in c.get("purpose", "").upper()
            for kw in ["RESULT", "QUARTERLY", "FINANCIAL"]
        )]
    output["earnings_calendar"] = earnings

    # ── Step 10: Thematic baskets ────────────────────────────────────────────
    print("[10/14] Computing thematic basket performance...")
    output["thematic_baskets"] = fetch_thematic_performance(THEMATIC_BASKETS)

    # ── Step 11: Zerodha AMR scrape ──────────────────────────────────────────
    print("[11/14] Scraping Zerodha AfterMarket Report...")
    output["zerodha_amr"] = fetch_zerodha_amr()

    # ── Step 12: Pulse headlines ─────────────────────────────────────────────
    print("[12/14] Scraping Zerodha Pulse headlines...")
    output["pulse_headlines"] = fetch_pulse_zerodha_headlines()

    # ── Step 13: Option chain (Kite only) ───────────────────────────────────
    if kite:
        print("[13/14] Fetching Nifty option chain summary (Kite Connect)...")
        oc = _kc.fetch_kite_option_chain_summary(kite, "NIFTY")
        output["option_chain"] = oc
        if oc:
            print(f"  [Kite OC] PCR={oc['pcr']} | Max pain={oc['max_pain']} | Expiry={oc['expiry']}")
        else:
            print("  [Kite OC] Could not fetch option chain")
    else:
        print("[13/14] Skipping option chain (Kite not available)")

    # ── Step 14: Multi-source news pipeline ─────────────────────────────────
    if _NEWS_MODULE_OK:
        print("[14/14] Fetching multi-source news pipeline...")
        try:
            raw_news = _nf.fetch_all_news(max_workers=4)
            output["raw_news"] = raw_news
            output["news_context"] = _nf.build_claude_context(raw_news, top_n=25)
            print(f"  [News] {len(raw_news)} unique items across {len(_nf.get_sources_used(raw_news))} sources")
        except Exception as e:
            print(f"  [News pipeline error] {e}")
    else:
        print("[14/14] Skipping news pipeline (feedparser not installed)")

    return output


def main():
    print("=" * 60)
    print("  Undeployed Capital — Daily Brief Data Pipeline")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p IST')}")
    print("=" * 60)

    data = run_full_pipeline()

    # Save to JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n✅ Data pipeline complete. Output saved to: {OUTPUT_FILE}")
    print(f"   Data source:        {data.get('data_source', 'yfinance')}")
    print(f"   Indices fetched:    {len([v for v in data['indices'].values() if v])}")
    print(f"   MCX commodities:    {len([v for v in data.get('mcx_commodities', {}).values() if v])}")
    print(f"   Thematic baskets:   {len([v for v in data['thematic_baskets'].values() if v])}")
    print(f"   Option chain:       {'Yes' if data.get('option_chain') else 'No'}")
    print(f"   Corporate actions:  {len(data['corporate_actions'])}")
    print(f"   Earnings calendar:  {len(data['earnings_calendar'])}")
    print(f"   AMR scraped:        {'Yes' if data['zerodha_amr'].get('headline') else 'Partial'}")
    print(f"   Pulse headlines:    {len(data['pulse_headlines'])}")
    print(f"   News items:         {len(data.get('raw_news', []))}")
    print(f"\n→ Next step: run  python3 brief_generator.py")


if __name__ == "__main__":
    main()
