#!/usr/bin/env python3
"""
kite_client.py — Zerodha Kite Connect data client

Primary market data source when access token is valid.
Falls back gracefully (returns None/empty dict) when unavailable.
Access token expires daily — run kite_login.py each morning to refresh.

Data provided:
  - Indices (Nifty 50, Bank Nifty, VIX, sectors)
  - F&O top movers
  - MCX commodity futures (prices in ₹ — labeled clearly)
  - Option chain summary (PCR, max pain, OI by strike)
"""

import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List

CONFIG_FILE = Path(__file__).parent / "kite_config.json"

try:
    from kiteconnect import KiteConnect
    _KITE_LIB_OK = True
except ImportError:
    _KITE_LIB_OK = False

# ─────────────────────────────────────────────
# CONFIG MANAGEMENT
# ─────────────────────────────────────────────

def load_kite_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_kite_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_token_fresh(cfg: dict) -> bool:
    """Access token valid only for the calendar day it was generated."""
    token_date = cfg.get("token_date", "")
    if not token_date:
        return False
    try:
        return token_date == str(date.today())
    except Exception:
        return False


def get_kite_client() -> Optional[object]:
    """
    Return authenticated KiteConnect instance or None.
    Returns None if: library not installed, config missing, token stale.
    """
    if not _KITE_LIB_OK:
        return None
    cfg = load_kite_config()
    if not cfg.get("api_key") or not cfg.get("access_token"):
        return None
    if not is_token_fresh(cfg):
        print("  [Kite] Access token stale — run: python3 kite_login.py")
        return None
    try:
        kite = KiteConnect(api_key=cfg["api_key"])
        kite.set_access_token(cfg["access_token"])
        return kite
    except Exception as e:
        print(f"  [Kite] Client init failed: {e}")
        return None


# ─────────────────────────────────────────────
# INSTRUMENT CACHE
# ─────────────────────────────────────────────

_instrument_cache: Dict[str, list] = {}


def _load_instruments(kite, exchange: str) -> list:
    """Load and cache instruments for an exchange (one fetch per session)."""
    global _instrument_cache
    if exchange in _instrument_cache:
        return _instrument_cache[exchange]
    try:
        instruments = kite.instruments(exchange)
        _instrument_cache[exchange] = instruments
        return instruments
    except Exception as e:
        print(f"  [Kite instruments] {exchange}: {e}")
        return []


# ─────────────────────────────────────────────
# INDICES
# ─────────────────────────────────────────────

KITE_INDEX_SYMBOLS = {
    "Nifty 50":     "NSE:NIFTY 50",
    "Nifty Bank":   "NSE:NIFTY BANK",
    "India VIX":    "NSE:INDIA VIX",
    "Nifty IT":     "NSE:NIFTY IT",
    "Nifty Pharma": "NSE:NIFTY PHARMA",
    "Nifty Metal":  "NSE:NIFTY METAL",
    "Nifty FMCG":   "NSE:NIFTY FMCG",
    "Nifty Auto":   "NSE:NIFTY AUTO",
    "Nifty Realty": "NSE:NIFTY REALTY",
    "Nifty Energy": "NSE:NIFTY ENERGY",
    "Sensex":       "BSE:SENSEX",
}


def fetch_kite_indices(kite) -> Dict[str, Optional[dict]]:
    """
    Fetch NSE/BSE index quotes from Kite Connect.
    Returns same structure as fetch_yfinance_batch() for drop-in replacement.
    Change% = (last_price - prev_close) / prev_close.
    """
    results = {}
    symbols = list(KITE_INDEX_SYMBOLS.values())
    try:
        quotes = kite.quote(symbols)
    except Exception as e:
        print(f"  [Kite indices] {e}")
        return {}

    for name, sym in KITE_INDEX_SYMBOLS.items():
        q = quotes.get(sym)
        if not q:
            results[name] = None
            continue
        ohlc = q.get("ohlc", {})
        last_price = float(q.get("last_price", 0) or 0)
        prev_close = float(ohlc.get("close", last_price) or last_price)
        change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close else 0
        results[name] = {
            "last_price": round(last_price, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(change_pct, 2),
            "change_abs": round(last_price - prev_close, 2),
            "high":  round(float(ohlc.get("high", last_price) or last_price), 2),
            "low":   round(float(ohlc.get("low", last_price) or last_price), 2),
            "open":  round(float(ohlc.get("open", last_price) or last_price), 2),
            "source": "kite",
        }
    return results


# ─────────────────────────────────────────────
# F&O MOVERS
# ─────────────────────────────────────────────

_FNO_STOCKS = [
    "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:INFY", "NSE:TCS", "NSE:ICICIBANK",
    "NSE:BAJFINANCE", "NSE:HCLTECH", "NSE:SBIN", "NSE:AXISBANK", "NSE:WIPRO",
    "NSE:TATAMOTORS", "NSE:MARUTI", "NSE:TATASTEEL", "NSE:HINDALCO", "NSE:JSWSTEEL",
    "NSE:ONGC", "NSE:COALINDIA", "NSE:SUNPHARMA", "NSE:DRREDDY", "NSE:CIPLA",
    "NSE:ADANIENT", "NSE:ADANIPORTS", "NSE:ULTRACEMCO", "NSE:BHARTIARTL",
    "NSE:NTPC", "NSE:POWERGRID", "NSE:TITAN", "NSE:KOTAKBANK", "NSE:LT",
    "NSE:BAJAJFINSV", "NSE:TECHM", "NSE:INDUSINDBK", "NSE:EICHERMOT",
    "NSE:GRASIM", "NSE:M&M", "NSE:NESTLEIND", "NSE:BRITANNIA",
]


def fetch_kite_fno_movers(kite) -> dict:
    """
    Top gainers/losers among NSE F&O stocks.
    Returns same structure as fetch_nse_gainers_losers().
    """
    try:
        quotes = kite.quote(_FNO_STOCKS)
    except Exception as e:
        print(f"  [Kite F&O movers] {e}")
        return {}

    movers = []
    for sym, q in quotes.items():
        ohlc = q.get("ohlc", {})
        last = float(q.get("last_price", 0) or 0)
        prev = float(ohlc.get("close", last) or last)
        if prev == 0:
            continue
        chg_pct = (last - prev) / prev * 100
        symbol = sym.replace("NSE:", "").replace("BSE:", "")
        movers.append({
            "symbol":     symbol,
            "name":       symbol,
            "ltp":        round(last, 2),
            "change_pct": round(chg_pct, 2),
            "change_abs": round(last - prev, 2),
        })

    movers.sort(key=lambda x: x["change_pct"], reverse=True)
    return {
        "index":   "NSE F&O (Kite)",
        "gainers": movers[:5],
        "losers":  list(reversed(movers[-5:])),
        "source":  "kite",
    }


# ─────────────────────────────────────────────
# MCX COMMODITIES (prices in ₹)
# ─────────────────────────────────────────────

# MCX instrument name → display label
MCX_SYMBOLS = {
    "GOLD":        "MCX Gold (₹/10g)",
    "SILVER":      "MCX Silver (₹/kg)",
    "CRUDEOIL":    "MCX Crude Oil (₹/bbl)",
    "NATURALGAS":  "MCX Natural Gas (₹/MMBtu)",
}


def _nearest_mcx_future(instruments: list, name_prefix: str) -> Optional[dict]:
    """Find the nearest-expiry active MCX futures contract."""
    today = date.today()
    candidates = [
        i for i in instruments
        if str(i.get("name", "")).upper() == name_prefix.upper()
        and i.get("instrument_type", "") == "FUT"
        and i.get("expiry") and i["expiry"] >= today
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["expiry"])
    return candidates[0]


def fetch_kite_mcx_commodities(kite) -> Dict[str, Optional[dict]]:
    """
    Fetch MCX commodity futures from Kite Connect.
    All prices in Indian Rupees (₹) — labeled clearly.
    Do NOT mix these with yfinance USD commodity prices.
    """
    results = {}
    instruments = _load_instruments(kite, "MCX")
    if not instruments:
        return {}

    for mcx_name, display_name in MCX_SYMBOLS.items():
        inst = _nearest_mcx_future(instruments, mcx_name)
        if not inst:
            results[display_name] = None
            continue
        try:
            token = f"MCX:{inst['tradingsymbol']}"
            q = kite.quote([token])
            data = q.get(token, {})
            if not data:
                results[display_name] = None
                continue
            ohlc = data.get("ohlc", {})
            last = float(data.get("last_price", 0) or 0)
            prev = float(ohlc.get("close", last) or last)
            chg_pct = ((last - prev) / prev * 100) if prev else 0
            results[display_name] = {
                "last_price":     round(last, 2),
                "prev_close":     round(prev, 2),
                "change_pct":     round(chg_pct, 2),
                "change_abs":     round(last - prev, 2),
                "high":           round(float(ohlc.get("high", last) or last), 2),
                "low":            round(float(ohlc.get("low", last) or last), 2),
                "open":           round(float(ohlc.get("open", last) or last), 2),
                "tradingsymbol":  inst["tradingsymbol"],
                "expiry":         str(inst["expiry"]),
                "currency":       "INR",
                "source":         "kite_mcx",
            }
        except Exception as e:
            print(f"  [Kite MCX] {mcx_name}: {e}")
            results[display_name] = None

    return results


# ─────────────────────────────────────────────
# OPTION CHAIN SUMMARY
# ─────────────────────────────────────────────

def fetch_kite_option_chain_summary(kite, index: str = "NIFTY") -> Optional[dict]:
    """
    Fetch Nifty option chain summary from NFO instruments.

    PCR = total put OI / total call OI
    Max pain = strike where total option buyer loss is maximized
    (= strike where option writers retain maximum premium)

    Returns strike data for charting + summary stats.
    """
    try:
        nifty_q = kite.quote(["NSE:NIFTY 50"])
        nifty_price = float((nifty_q.get("NSE:NIFTY 50") or {}).get("last_price", 0) or 0)
        if not nifty_price:
            return None

        instruments = _load_instruments(kite, "NFO")
        if not instruments:
            return None

        today = date.today()
        nifty_opts = [
            i for i in instruments
            if str(i.get("name", "")).upper() == index.upper()
            and i.get("instrument_type") in ("CE", "PE")
            and i.get("expiry") and i["expiry"] >= today
        ]
        if not nifty_opts:
            return None

        expiries = sorted(set(i["expiry"] for i in nifty_opts))
        nearest_expiry = expiries[0]

        # ATM ± 1000 points, 50-point step
        atm_strike = round(nifty_price / 50) * 50
        valid_strikes = set(range(int(atm_strike - 1000), int(atm_strike + 1050), 50))

        chain_insts = [
            i for i in nifty_opts
            if i["expiry"] == nearest_expiry
            and int(i.get("strike", 0)) in valid_strikes
        ]
        if not chain_insts:
            return None

        # Batch quote (max 490 per call to stay under 500 limit)
        tokens = [f"NFO:{i['tradingsymbol']}" for i in chain_insts]
        quotes: dict = {}
        for start in range(0, len(tokens), 490):
            batch = tokens[start:start + 490]
            try:
                quotes.update(kite.quote(batch))
            except Exception:
                pass

        # Build per-strike data
        strike_data: dict = {}
        for inst in chain_insts:
            strike = int(inst.get("strike", 0))
            opt_type = inst.get("instrument_type", "")
            key = f"NFO:{inst['tradingsymbol']}"
            q = quotes.get(key, {})
            oi  = int(q.get("oi", 0) or 0)
            ltp = float(q.get("last_price", 0) or 0)
            if strike not in strike_data:
                strike_data[strike] = {"ce_oi": 0, "pe_oi": 0, "ce_ltp": 0.0, "pe_ltp": 0.0}
            if opt_type == "CE":
                strike_data[strike]["ce_oi"]  = oi
                strike_data[strike]["ce_ltp"] = ltp
            elif opt_type == "PE":
                strike_data[strike]["pe_oi"]  = oi
                strike_data[strike]["pe_ltp"] = ltp

        if not strike_data:
            return None

        total_call_oi = sum(v["ce_oi"] for v in strike_data.values())
        total_put_oi  = sum(v["pe_oi"] for v in strike_data.values())
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi else 0

        # Max pain: strike minimizing total option buyer P&L at expiry
        strikes_sorted = sorted(strike_data.keys())
        max_pain_vals: dict = {}
        for k in strikes_sorted:
            call_pain = sum(
                max(0, k - s) * strike_data[s]["ce_oi"]
                for s in strikes_sorted if s <= k
            )
            put_pain = sum(
                max(0, s - k) * strike_data[s]["pe_oi"]
                for s in strikes_sorted if s >= k
            )
            max_pain_vals[k] = call_pain + put_pain
        max_pain_strike = max(max_pain_vals, key=max_pain_vals.get)

        top_ce = sorted(strikes_sorted, key=lambda s: strike_data[s]["ce_oi"], reverse=True)[:3]
        top_pe = sorted(strikes_sorted, key=lambda s: strike_data[s]["pe_oi"], reverse=True)[:3]

        return {
            "index":             index,
            "expiry":            str(nearest_expiry),
            "spot_price":        round(nifty_price, 2),
            "atm_strike":        atm_strike,
            "pcr":               pcr,
            "max_pain":          max_pain_strike,
            "total_call_oi":     total_call_oi,
            "total_put_oi":      total_put_oi,
            "top_ce_oi_strikes": top_ce,
            "top_pe_oi_strikes": top_pe,
            "strikes": [
                {"strike": s, "call_oi": strike_data[s]["ce_oi"], "put_oi": strike_data[s]["pe_oi"]}
                for s in strikes_sorted
            ],
            "source": "kite",
        }

    except Exception as e:
        print(f"  [Kite option chain] {e}")
        return None
