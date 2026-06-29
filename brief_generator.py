#!/usr/bin/env python3
"""
brief_generator.py — Undeployed Capital Daily Brief
Phase 1 (data) + Phase 2 (content) + Phase 3 (intelligence) + Design upgrade

Takes the JSON output from data_fetcher.py and:
  1. Generates all Plotly charts (sectors, thematic, global, FII/DII, option chain,
     intraday price action, fear & greed gauge, FII/DII 30-day history,
     sector-rotation heatmap)
  2. Builds the data tables
  3. Calls Claude API for all prose sections + the Editor's Take
  4. Assembles a fully responsive HTML article with:
       - sticky side navigation (hamburger on mobile)
       - market-mood hero banner
       - dark / light theme toggle (localStorage-persisted)
       - branded wordmark (Google Fonts)
       - PDF export + WhatsApp share buttons
  5. Saves to briefs/brief_YYYY-MM-DD.html

Requirements:
    pip install anthropic plotly pandas

Usage:
    python3 brief_generator.py [--data brief_data.json] [--no-ai]

    --no-ai: skip all Claude API calls (useful for testing layout)
"""

import json
import os
import sys
import argparse
from datetime import datetime, date, timedelta
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd


# ─────────────────────────────────────────────
# .env AUTOLOAD — so the key "just works" once you fill .env
# (no manual `export` needed before each run)
# ─────────────────────────────────────────────

def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no external dep). Existing env vars win."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = path if os.path.isabs(path) else os.path.join(here, path)
    if not os.path.exists(candidate):
        return
    try:
        with open(candidate) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as e:
        print(f"  [.env] could not load {candidate}: {e}")


_load_dotenv()

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_FILE         = "brief_data.json"
OUTPUT_DIR        = "briefs"
DATA_STORE_DIR    = os.path.join("docs", "data")   # flows.json / sectors.json live here

# Public base URL used in the share card
SITE_BASE_URL = "https://ishaansheth.github.io/daily-brief/briefs"

# Visual identity for Undeployed Capital — dark financial terminal aesthetic.
# Light-theme equivalents live in the CSS via [data-theme="light"] overrides.
COLORS = {
    "bg":          "#0D0F14",      # near-black background
    "card":        "#161B22",      # card surfaces
    "border":      "#21262D",      # subtle borders
    "accent":      "#58A6FF",      # electric blue — primary accent
    "accent2":     "#3FB950",      # green — gains
    "negative":    "#F85149",      # red — losses
    "neutral":     "#8B949E",      # muted text (visible on BOTH dark & light)
    "text":        "#E6EDF3",      # primary text
    "text_dim":    "#7D8590",      # secondary text
    "gold":        "#D29922",      # highlight / special
    "amber":       "#FF8C00",      # unusual-volume / caution
}

# Chart fonts use the cross-theme neutral grey so axis labels stay readable
# whether the page is on the dark or the light theme (Plotly paper is transparent).
CHART_LAYOUT = dict(
    paper_bgcolor = "rgba(0,0,0,0)",
    plot_bgcolor  = "rgba(0,0,0,0)",
    font          = dict(family="'SF Mono', 'Fira Code', monospace", color=COLORS["neutral"], size=12),
    margin        = dict(l=10, r=10, t=40, b=10),
    showlegend    = False,
)

# Responsive config applied to every chart so Plotly resizes on small screens.
PLOTLY_CONFIG = {"responsive": True, "displayModeBar": False}

# Section registry — drives the sticky side-nav. (anchor_id, label)
NAV_SECTIONS = [
    ("editors-take",        "Editor's Take"),
    ("market-snapshot",     "Market Snapshot"),
    ("price-action",        "Today's Price Action"),
    ("sectors",             "Sectors"),
    ("technical-levels",    "Technical Levels"),
    ("institutional-flows", "Institutional Flows"),
    ("option-chain",        "Option Chain"),
    ("commodities",         "Commodities"),
    ("global-markets",      "Global Markets"),
    ("macro-view",          "Macro View"),
    ("thematic-tracker",    "Thematic Tracker"),
    ("earnings-calendar",   "Earnings Calendar"),
    ("corporate",           "Corporate Headlines"),
    ("global-pulse",        "Global Pulse"),
    ("management-chatter",  "Management Chatter"),
    ("capital-flows",       "Capital Flows"),
    ("regulatory-watch",    "Regulatory Watch"),
    ("watch-tomorrow",      "What to Watch Tomorrow"),
    ("day-at-a-glance",     "Day at a Glance"),
]


def _to_html(fig, div_id):
    """Render a Plotly figure with the responsive config baked in."""
    return fig.to_html(include_plotlyjs=False, full_html=False,
                       div_id=div_id, config=PLOTLY_CONFIG)


# ─────────────────────────────────────────────
# CHART GENERATION — existing
# ─────────────────────────────────────────────

def chart_sector_performance(indices: dict) -> str:
    sector_order = [
        "Nifty Metal", "Nifty IT", "Nifty Bank", "Nifty Realty",
        "Nifty Energy", "Nifty FMCG", "Nifty Auto", "Nifty Pharma",
        "Nifty 50", "Sensex"
    ]

    labels, values, colors = [], [], []
    for name in sector_order:
        d = indices.get(name)
        if d:
            labels.append(name.replace("Nifty ", ""))
            pct = d["change_pct"]
            values.append(pct)
            colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])

    if not labels:
        return "<p style='color:#7D8590'>Sector data unavailable</p>"

    pairs = sorted(zip(values, labels, colors), key=lambda x: x[0])
    values, labels, colors = zip(*pairs) if pairs else ([], [], [])

    fig = go.Figure(go.Bar(
        x=list(values), y=list(labels), orientation="h",
        marker=dict(color=list(colors), line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values],
        textposition="outside", textfont=dict(size=10, color=COLORS["neutral"]),
        hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Sector Performance", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
                   gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"]),
        yaxis=dict(color=COLORS["neutral"], tickfont=dict(size=11)),
        height=360,
    )
    return _to_html(fig, "chart_sectors")


def chart_thematic_baskets(baskets: dict) -> str:
    labels, values, colors, hover_texts = [], [], [], []
    for theme, d in baskets.items():
        if d is None:
            continue
        pct = d["basket_return_pct"]
        top = d["top_performer"]
        worst = d["worst_performer"]
        labels.append(theme)
        values.append(pct)
        colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])
        constituents_str = "<br>".join(
            f"  {sym}: {chg:+.2f}%"
            for sym, chg in sorted(d["constituents"].items(), key=lambda x: x[1], reverse=True)
        )
        hover_texts.append(
            f"<b>{theme}</b><br>Basket: {pct:+.2f}%<br>"
            f"Best: {top['symbol']} ({top['change_pct']:+.2f}%)<br>"
            f"Worst: {worst['symbol']} ({worst['change_pct']:+.2f}%)<br><br>{constituents_str}"
        )

    if not labels:
        return "<p style='color:#7D8590'>Thematic data unavailable</p>"

    fig = go.Figure(go.Bar(
        x=labels, y=values, marker=dict(color=colors, line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values], textposition="outside",
        textfont=dict(size=11, color=COLORS["neutral"]),
        hovertemplate="%{customdata}<extra></extra>", customdata=hover_texts,
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Thematic Tracker", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(tickangle=-20, color=COLORS["neutral"], tickfont=dict(size=10)),
        yaxis=dict(zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
                   gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"]),
        height=340,
    )
    return _to_html(fig, "chart_thematic")


def chart_global_markets(global_data: dict) -> str:
    labels, values, colors = [], [], []
    for name, d in global_data.items():
        if d:
            labels.append(name)
            pct = d["change_pct"]
            values.append(pct)
            colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])

    if not labels:
        return "<p style='color:#7D8590'>Global data unavailable</p>"

    pairs = sorted(zip(values, labels, colors))
    values, labels, colors = zip(*pairs) if pairs else ([], [], [])

    fig = go.Figure(go.Bar(
        x=list(values), y=list(labels), orientation="h",
        marker=dict(color=list(colors), line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values], textposition="outside",
        textfont=dict(size=10, color=COLORS["neutral"]),
        hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Global Markets", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
                   gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"]),
        yaxis=dict(color=COLORS["neutral"], tickfont=dict(size=11)),
        height=320,
    )
    return _to_html(fig, "chart_global")


def chart_fii_dii_bars(fii_dii: dict) -> str:
    if not fii_dii:
        return "<p style='color:#7D8590'>FII/DII data unavailable</p>"
    fii = fii_dii.get("fii_net_cr", 0)
    dii = fii_dii.get("dii_net_cr", 0)
    fig = go.Figure(go.Bar(
        x=["FII (Foreign)", "DII (Domestic)"], y=[fii, dii],
        marker=dict(color=[COLORS["accent2"] if fii >= 0 else COLORS["negative"],
                           COLORS["accent2"] if dii >= 0 else COLORS["negative"]], line=dict(width=0)),
        text=[f"₹{fii:+,.0f} Cr", f"₹{dii:+,.0f} Cr"], textposition="outside",
        textfont=dict(size=12, color=COLORS["neutral"]),
        hovertemplate="%{x}: ₹%{y:,.0f} Cr<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Institutional Flows — Net Today",
                   font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(color=COLORS["neutral"]),
        yaxis=dict(zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
                   gridcolor=COLORS["border"], tickprefix="₹", ticksuffix=" Cr",
                   color=COLORS["text_dim"]),
        height=280,
    )
    return _to_html(fig, "chart_fiidii")


def chart_option_chain(oc: dict) -> str:
    if not oc or not oc.get("strikes"):
        return "<p style='color:#7D8590'>Option chain data unavailable (Kite Connect required)</p>"

    strikes_data = oc["strikes"]
    strikes  = [s["strike"] for s in strikes_data]
    call_oi  = [s["call_oi"] / 1_00_000 for s in strikes_data]
    put_oi   = [s["put_oi"]  / 1_00_000 for s in strikes_data]
    spot     = oc.get("spot_price", 0)
    max_pain = oc.get("max_pain", 0)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=strikes, y=call_oi, name="Call OI",
                         marker=dict(color=COLORS["negative"], opacity=0.75),
                         hovertemplate="Strike %{x}: %{y:.1f}L Call OI<extra></extra>"))
    fig.add_trace(go.Bar(x=strikes, y=put_oi, name="Put OI",
                         marker=dict(color=COLORS["accent2"], opacity=0.75),
                         hovertemplate="Strike %{x}: %{y:.1f}L Put OI<extra></extra>"))

    shapes, annotations = [], []
    if spot:
        shapes.append(dict(type="line", x0=spot, x1=spot, y0=0, y1=1, yref="paper",
                           line=dict(color=COLORS["gold"], width=2, dash="dot")))
        annotations.append(dict(x=spot, y=1, yref="paper", text=f"Spot {spot:,.0f}",
                                showarrow=False, font=dict(color=COLORS["gold"], size=10),
                                xanchor="center", yanchor="bottom"))
    if max_pain and max_pain != spot:
        shapes.append(dict(type="line", x0=max_pain, x1=max_pain, y0=0, y1=1, yref="paper",
                           line=dict(color=COLORS["accent"], width=2, dash="dash")))
        annotations.append(dict(x=max_pain, y=0.85, yref="paper", text=f"Max Pain {max_pain:,.0f}",
                                showarrow=False, font=dict(color=COLORS["accent"], size=10),
                                xanchor="center", yanchor="bottom"))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"Nifty Option Chain OI — Expiry {oc.get('expiry', '')}",
                   font=dict(size=13, color=COLORS["text_dim"]), x=0),
        barmode="group",
        xaxis=dict(title="Strike", color=COLORS["neutral"], tickfont=dict(size=10)),
        yaxis=dict(title="OI (Lakhs)", gridcolor=COLORS["border"], color=COLORS["text_dim"]),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=COLORS["neutral"])),
        shapes=shapes, annotations=annotations, height=320,
    )
    return _to_html(fig, "chart_optchain")


# ─────────────────────────────────────────────
# CHART GENERATION — Phase 2 / Phase 3 (new)
# ─────────────────────────────────────────────

def chart_intraday(intraday: dict) -> str:
    """
    Today's Price Action — candlestick from Kite 5-min OHLC.
    `intraday` shape: {"candles": [{t, o, h, l, c}, ...]}.
    Falls back to a line if OHLC is incomplete.
    """
    candles = (intraday or {}).get("candles") or []
    if not candles:
        return ("<p style='color:#7D8590'>Intraday price action requires Kite Connect "
                "(NSE:NIFTY 50 historical 5-min data). Will populate automatically on the next "
                "live run.</p>")

    t = [c.get("t") for c in candles]
    o = [c.get("o") for c in candles]
    h = [c.get("h") for c in candles]
    l = [c.get("l") for c in candles]
    cl = [c.get("c") for c in candles]

    have_ohlc = all(x is not None for x in o + h + l)
    if have_ohlc:
        trace = go.Candlestick(
            x=t, open=o, high=h, low=l, close=cl,
            increasing=dict(line=dict(color=COLORS["accent2"])),
            decreasing=dict(line=dict(color=COLORS["negative"])),
            name="Nifty 50",
        )
    else:
        trace = go.Scatter(x=t, y=cl, mode="lines",
                           line=dict(color=COLORS["accent"], width=2), name="Nifty 50")

    fig = go.Figure(trace)
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Nifty 50 — Intraday", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(color=COLORS["neutral"], gridcolor=COLORS["border"], rangeslider=dict(visible=False)),
        yaxis=dict(color=COLORS["text_dim"], gridcolor=COLORS["border"]),
        height=340,
    )
    return _to_html(fig, "chart_intraday")


def compute_fear_greed(data: dict) -> tuple:
    """
    Composite 0–100 sentiment from 4 equally-weighted inputs:
      VIX (lower = greedier), PCR (>1 fear / <0.7 greed),
      Advance-Decline ratio, FII net flow (positive = greed).
    Returns (score:int, label:str, components:dict).
    """
    comps = {}

    vix = (((data.get("market_status") or {}).get("india_vix")) or {}).get("last")
    if vix is not None:
        comps["VIX"] = max(0.0, min(100.0, (30.0 - float(vix)) / (30.0 - 10.0) * 100.0))

    oc = data.get("option_chain") or {}
    pcr = oc.get("pcr")
    if pcr is not None:
        comps["PCR"] = max(0.0, min(100.0, (1.4 - float(pcr)) / (1.4 - 0.6) * 100.0))

    ms = data.get("market_status") or {}
    try:
        adv = float(ms.get("nifty_advances") or 0)
        dec = float(ms.get("nifty_declines") or 0)
        if adv or dec:
            comps["AdvDec"] = max(0.0, min(100.0, adv / (adv + dec) * 100.0))
    except (TypeError, ValueError):
        pass

    fii = (data.get("fii_dii") or {}).get("fii_net_cr")
    if fii is not None:
        comps["FII"] = max(0.0, min(100.0, (float(fii) + 3000.0) / 6000.0 * 100.0))

    if not comps:
        return (50, "Neutral", {})

    score = round(sum(comps.values()) / len(comps))
    if   score <= 25: label = "Extreme Fear"
    elif score <= 45: label = "Fear"
    elif score <= 55: label = "Neutral"
    elif score <= 75: label = "Greed"
    else:             label = "Extreme Greed"
    return (score, label, comps)


def chart_fear_greed(score: int, label: str) -> str:
    """Plotly gauge with the 5 fear/greed zones."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(font=dict(size=34, color=COLORS["neutral"])),
        title=dict(text=f"Fear & Greed — {label}", font=dict(size=13, color=COLORS["text_dim"])),
        gauge=dict(
            axis=dict(range=[0, 100], tickcolor=COLORS["text_dim"], tickfont=dict(size=9)),
            bar=dict(color="rgba(255,255,255,0.0)"),
            borderwidth=0,
            steps=[
                dict(range=[0, 25],   color=COLORS["negative"]),
                dict(range=[25, 45],  color=COLORS["amber"]),
                dict(range=[45, 55],  color=COLORS["neutral"]),
                dict(range=[55, 75],  color="#7DCE82"),
                dict(range=[75, 100], color=COLORS["accent2"]),
            ],
            threshold=dict(line=dict(color=COLORS["text"], width=4), thickness=0.85, value=score),
        ),
    ))
    fig.update_layout(**{k: v for k, v in CHART_LAYOUT.items() if k != "showlegend"},
                      height=240)
    return _to_html(fig, "chart_feargreed")


def chart_fii_dii_history(history: list) -> str:
    """Grouped bar chart — FII vs DII net flow over last 30 stored sessions."""
    if not history:
        return ("<p style='color:#7D8590'>Flow history will build up over the coming "
                "sessions (stored in docs/data/flows.json).</p>")
    rows = history[-30:]
    dates = [r.get("date", "") for r in rows]
    fii   = [r.get("fii_net_cr", 0) for r in rows]
    dii   = [r.get("dii_net_cr", 0) for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=dates, y=fii, name="FII",
                         marker=dict(color=COLORS["accent"]),
                         hovertemplate="%{x}<br>FII: ₹%{y:,.0f} Cr<extra></extra>"))
    fig.add_trace(go.Bar(x=dates, y=dii, name="DII",
                         marker=dict(color=COLORS["gold"]),
                         hovertemplate="%{x}<br>DII: ₹%{y:,.0f} Cr<extra></extra>"))
    fig.update_layout(
        **{k: v for k, v in CHART_LAYOUT.items() if k != "showlegend"},
        title=dict(text="FII vs DII — Net Flow (last 30 sessions)",
                   font=dict(size=13, color=COLORS["text_dim"]), x=0),
        barmode="group",
        legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11, color=COLORS["neutral"])),
        xaxis=dict(color=COLORS["text_dim"], tickfont=dict(size=9), tickangle=-45),
        yaxis=dict(zeroline=True, zerolinecolor=COLORS["border"], gridcolor=COLORS["border"],
                   tickprefix="₹", ticksuffix=" Cr", color=COLORS["text_dim"]),
        height=320,
    )
    return _to_html(fig, "chart_fiidii_hist")


def chart_sector_rotation(history: list) -> str:
    """
    Heatmap — sectors (rows) × dates (cols), cell colour = performance %.
    `history`: list of {"date": str, "sectors": {SectorName: pct}}.
    """
    if not history:
        return ("<p style='color:#7D8590'>Sector-rotation history will build up over the "
                "coming sessions (stored in docs/data/sectors.json).</p>")
    rows = history[-10:]
    sector_names = ["Auto", "Bank", "FMCG", "IT", "Metal", "Pharma", "Realty", "Energy"]
    dates = [r.get("date", "") for r in rows]

    z = []
    for s in sector_names:
        z.append([(r.get("sectors") or {}).get(s) for r in rows])

    fig = go.Figure(go.Heatmap(
        z=z, x=dates, y=sector_names,
        colorscale=[[0.0, COLORS["negative"]], [0.5, "#161B22"], [1.0, COLORS["accent2"]]],
        zmid=0, zmin=-3, zmax=3,
        hovertemplate="%{y} · %{x}: %{z:+.2f}%<extra></extra>",
        colorbar=dict(tickfont=dict(size=9, color=COLORS["text_dim"]), thickness=10,
                      ticksuffix="%", outlinewidth=0),
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Sector Rotation — last 10 sessions",
                   font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(color=COLORS["text_dim"], tickfont=dict(size=9), tickangle=-45),
        yaxis=dict(color=COLORS["neutral"], tickfont=dict(size=11)),
        height=320,
    )
    return _to_html(fig, "chart_rotation")


# ─────────────────────────────────────────────
# PERSISTENCE — flows.json & sectors.json (append-on-run)
# ─────────────────────────────────────────────

def _load_json_list(path: str) -> list:
    try:
        with open(path) as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_json_list(path: str, items: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(items, f, indent=2, default=str)


def update_flows_history(data: dict) -> list:
    """Append today's FII/DII net to docs/data/flows.json (dedup by date). Returns full list."""
    path = os.path.join(DATA_STORE_DIR, "flows.json")
    hist = _load_json_list(path)
    fii_dii = data.get("fii_dii") or {}
    today = data.get("trading_date", str(date.today()))
    entry = {
        "date":       fii_dii.get("date", today),
        "fii_net_cr": fii_dii.get("fii_net_cr"),
        "dii_net_cr": fii_dii.get("dii_net_cr"),
    }
    if entry["fii_net_cr"] is not None or entry["dii_net_cr"] is not None:
        hist = [h for h in hist if h.get("date") != entry["date"]]
        hist.append(entry)
        hist = hist[-90:]   # keep ~quarter of history
        _save_json_list(path, hist)
    return hist


def update_sector_history(data: dict) -> list:
    """Append today's 8-sector performance to docs/data/sectors.json (dedup by date)."""
    path = os.path.join(DATA_STORE_DIR, "sectors.json")
    hist = _load_json_list(path)
    indices = data.get("indices") or {}
    name_map = {
        "Auto": "Nifty Auto", "Bank": "Nifty Bank", "FMCG": "Nifty FMCG",
        "IT": "Nifty IT", "Metal": "Nifty Metal", "Pharma": "Nifty Pharma",
        "Realty": "Nifty Realty", "Energy": "Nifty Energy",
    }
    sectors = {}
    for short, full in name_map.items():
        d = indices.get(full)
        if d and d.get("change_pct") is not None:
            sectors[short] = d["change_pct"]
    today = data.get("trading_date", str(date.today()))
    if sectors:
        hist = [h for h in hist if h.get("date") != today]
        hist.append({"date": today, "sectors": sectors})
        hist = hist[-60:]
        _save_json_list(path, hist)
    return hist


# ─────────────────────────────────────────────
# SENTIMENT BADGES (Phase 3)
# ─────────────────────────────────────────────

def _badge_html(state: str) -> str:
    """state in {BULLISH, BEARISH, NEUTRAL}."""
    colors = {"BULLISH": COLORS["accent2"], "BEARISH": COLORS["negative"], "NEUTRAL": COLORS["neutral"]}
    c = colors.get(state, COLORS["neutral"])
    return (f'<span class="sentiment-badge" style="background:{c}22;color:{c};border:1px solid {c}55">'
            f'{state}</span>')


def badge_institutional(data: dict) -> str:
    f = (data.get("fii_dii") or {})
    fii = f.get("fii_net_cr")
    dii = f.get("dii_net_cr")
    if fii is None or dii is None:
        return _badge_html("NEUTRAL")
    if fii < -2000:
        return _badge_html("BEARISH")
    if dii > 0 and fii > -500:
        return _badge_html("BULLISH")
    return _badge_html("NEUTRAL")


def badge_option_chain(data: dict) -> str:
    pcr = (data.get("option_chain") or {}).get("pcr")
    if pcr is None:
        return _badge_html("NEUTRAL")
    if pcr > 1:   return _badge_html("BULLISH")
    if pcr < 0.7: return _badge_html("BEARISH")
    return _badge_html("NEUTRAL")


def badge_macro(data: dict) -> str:
    # Rupee strengthening (USD/INR down) + US yields down => risk-on bullish.
    usdinr = ((data.get("fx") or {}).get("USD/INR") or {}).get("change_pct")
    us10y  = ((data.get("bonds") or {}).get("US 10Y Yield") or {}).get("change_pct")
    score = 0
    if usdinr is not None:
        score += 1 if usdinr < 0 else -1   # weaker rupee = headwind
    if us10y is not None:
        score += 1 if us10y < 0 else -1     # lower yields = supportive
    if score > 0:  return _badge_html("BULLISH")
    if score < 0:  return _badge_html("BEARISH")
    return _badge_html("NEUTRAL")


def badge_global(data: dict) -> str:
    g = data.get("global_markets") or {}
    sp = (g.get("S&P 500") or {}).get("change_pct")
    nk = (g.get("Nikkei 225") or {}).get("change_pct")
    if sp is None or nk is None:
        return _badge_html("NEUTRAL")
    if sp > 0 and nk > 0:   return _badge_html("BULLISH")
    if sp < 0 and nk < 0:   return _badge_html("BEARISH")
    return _badge_html("NEUTRAL")


# ─────────────────────────────────────────────
# MARKET MOOD (hero)
# ─────────────────────────────────────────────

def compute_market_mood(data: dict) -> tuple:
    """
    Hero mood from Nifty change + VIX. Returns (label, hex_color).
    BULLISH (green) / BEARISH (red) / CAUTIOUS (amber).
    """
    nifty = (data.get("indices") or {}).get("Nifty 50") or {}
    chg = nifty.get("change_pct")
    vix = (((data.get("market_status") or {}).get("india_vix")) or {}).get("last")
    chg = 0.0 if chg is None else float(chg)
    vix = 16.0 if vix is None else float(vix)

    if chg >= 0.3 and vix < 18:
        return ("BULLISH", COLORS["accent2"])
    if chg <= -0.3 or vix > 22:
        return ("BEARISH", COLORS["negative"])
    return ("CAUTIOUS", COLORS["gold"])


# ─────────────────────────────────────────────
# ECONOMIC CALENDAR (hardcoded, editable) — for "What to Watch Tomorrow"
# ─────────────────────────────────────────────

# Edit these as the schedule firms up. Dates are ISO (YYYY-MM-DD).
ECONOMIC_CALENDAR = [
    ("2026-07-01", "India Manufacturing PMI (Jun)"),
    ("2026-07-04", "US Non-Farm Payrolls (Jun)"),
    ("2026-07-11", "India CPI inflation (Jun)"),
    ("2026-07-15", "US CPI inflation (Jun)"),
    ("2026-07-29", "US FOMC rate decision"),
    ("2026-08-06", "RBI MPC rate decision"),
    ("2026-08-12", "India CPI inflation (Jul)"),
    ("2026-08-13", "US CPI inflation (Jul)"),
    ("2026-09-11", "India CPI inflation (Aug)"),
    ("2026-09-16", "US FOMC rate decision"),
]


def upcoming_econ_events(from_date: date, days: int = 4) -> list:
    """Events within `days` calendar days of from_date (covers ~2 trading days)."""
    horizon = from_date + timedelta(days=days)
    out = []
    for iso, label in ECONOMIC_CALENDAR:
        try:
            d = datetime.fromisoformat(iso).date()
        except ValueError:
            continue
        if from_date <= d <= horizon:
            out.append((d.strftime("%a, %b %d"), label))
    return out


# ─────────────────────────────────────────────
# CLAUDE API — PROSE GENERATION
# ─────────────────────────────────────────────

def call_claude(prompt: str, system: str, max_tokens: int = 1800) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"  [Claude API error] {e}")
        return f"[AI prose unavailable: {e}]"


# ─────────────────────────────────────────────
# CLAUDE API — EDITOR'S TAKE (Phase 3)
# ─────────────────────────────────────────────

def generate_editors_take(data: dict) -> str:
    """
    Opinionated synthesis of the day via Claude. Returns "" if unavailable
    (no key) so the section renders a graceful placeholder.
    """
    if not ANTHROPIC_API_KEY:
        print("  [Editor's Take] ANTHROPIC_API_KEY not set — skipping.")
        return ""

    indices = data.get("indices") or {}
    nifty   = indices.get("Nifty 50") or {}
    vix     = (((data.get("market_status") or {}).get("india_vix")) or {}).get("last")
    fii_dii = data.get("fii_dii") or {}
    pcr     = (data.get("option_chain") or {}).get("pcr")

    sector_only = {k.replace("Nifty ", ""): v["change_pct"]
                   for k, v in indices.items()
                   if v and k not in ("Nifty 50", "Sensex") and v.get("change_pct") is not None}
    top_sectors = sorted(sector_only.items(), key=lambda x: x[1], reverse=True)
    top_gainers = ", ".join(f"{n} {p:+.2f}%" for n, p in top_sectors[:2]) or "n/a"
    top_losers  = ", ".join(f"{n} {p:+.2f}%" for n, p in top_sectors[-2:]) or "n/a"

    headlines = []
    for item in (data.get("raw_news") or [])[:3]:
        if item.get("title"):
            headlines.append(item["title"])
    if not headlines:
        headlines = (data.get("pulse_headlines") or [])[:3]
    headlines_txt = "\n".join(f"- {h}" for h in headlines) or "- (no major headlines captured)"

    prompt = f"""Write the "Editor's Take" for today's Indian market brief — 4 to 5 sentences.
Write like a sharp, experienced Indian market analyst: direct, opinionated, actionable.
This is an INTERPRETATION, not a summary. Take a view. Tell the reader what actually matters
and what to do with it.

Today's data:
- Nifty 50: {nifty.get('last_price', 'N/A')} ({nifty.get('change_pct', 0):+.2f}%)
- India VIX: {vix if vix is not None else 'N/A'}
- FII net: ₹{fii_dii.get('fii_net_cr', 'N/A')} Cr | DII net: ₹{fii_dii.get('dii_net_cr', 'N/A')} Cr
- Put-Call Ratio: {pcr if pcr is not None else 'N/A'}
- Top sectors: {top_gainers}
- Weakest sectors: {top_losers}
- Top headlines:
{headlines_txt}

No markdown, no headers, plain prose. Do not fabricate any numbers not given above."""

    take = call_claude(
        prompt=prompt,
        system="You are a veteran Indian equities strategist writing a punchy daily editor's note. Direct, opinionated, actionable.",
        max_tokens=320,
    )
    # call_claude returns an error string on failure — treat that as unavailable.
    if take.startswith("[AI prose unavailable"):
        return ""
    return take.strip()


SYSTEM_PROMPT = """You are the writer of Undeployed Capital Daily Brief — a sharp,
data-dense Indian financial market briefing written for aspiring founders, early-career
investors, and VC/finance professionals aged 20-30.

Voice: Informed, direct, slightly opinionated. Not corporate. Not casual. Think
Bloomberg Terminal meets someone who actually knows what a term sheet looks like.

Rules:
- Every sentence must carry a number or move the story forward
- No filler phrases ("it is worth noting", "in conclusion", etc.)
- Attribution in parentheses: (Source: Zerodha AMR), (NSE), (Mint) etc.
- Never fabricate data. If a number isn't provided, don't invent it.
- Write in clean paragraphs — no bullet points (we handle bullets in the HTML layout)
- Do NOT use markdown headers (## or ###). Output plain prose only.
- Max 120 words per section unless specified otherwise
- Include "why it matters" framing at least once per section
- Bear cases and risks are always mentioned where relevant"""


def generate_ai_sections(data: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        print("  [AI] No ANTHROPIC_API_KEY set. Skipping Claude prose.")
        return {}

    sections = {}
    indices      = data.get("indices", {})
    fii_dii      = data.get("fii_dii", {})
    amr          = data.get("zerodha_amr", {})
    pulse        = data.get("pulse_headlines", [])
    baskets      = data.get("thematic_baskets", {})
    global_m     = data.get("global_markets", {})
    vix          = data.get("market_status", {})
    news_context = data.get("news_context", "")
    raw_news     = data.get("raw_news", [])

    nifty = indices.get("Nifty 50", {}) or {}
    amr_stories    = "\n".join(f"- {s}" for s in (amr.get("top_india_stories", []) or [])[:6])
    pulse_stories  = "\n".join(f"- {h}" for h in (pulse or [])[:6])
    global_stories = "\n".join(f"- {s}" for s in (amr.get("global_stories", []) or [])[:5])
    news_layer = news_context or f"{amr_stories}\n{pulse_stories}"

    _nifty_chg = nifty.get('change_pct') or 0
    _nifty_dir = "rises" if _nifty_chg >= 0 else "falls"

    print("  [AI] Writing auto-headline...")
    sections["auto_headline"] = call_claude(
        prompt=f"""Write ONE punchy Bloomberg-style headline summarising today's Indian market session.
Max 15 words. No quotes. No full stop at end.

Key facts:
- Nifty 50: {nifty.get('last_price', 'N/A')} ({_nifty_chg:+.2f}%, {_nifty_dir})
- India VIX: {vix.get('india_vix', {}).get('last', 'N/A') if vix.get('india_vix') else 'N/A'}
- Top news today (use at most one item, only if number is given):
{news_layer[:400]}

Format: "Nifty [action] [number]%; [one key driver]"
Output the headline only — no explanation.""",
        system=SYSTEM_PROMPT, max_tokens=40)

    print("  [AI] Writing intraday narrative...")
    sections["intraday_narrative"] = call_claude(
        prompt=f"""Write the intraday narrative for Nifty 50 today.

Market data:
- Nifty 50 close: {nifty.get('last_price', 'N/A')} ({_nifty_chg:+.2f}% vs prev close {nifty.get('prev_close', 'N/A')})
- Day high: {nifty.get('high', 'N/A')}, Day low: {nifty.get('low', 'N/A')}
- India VIX: {vix.get('india_vix', {}).get('last', 'N/A') if vix.get('india_vix') else 'N/A'}
- Advances: {vix.get('nifty_advances', 'N/A')}, Declines: {vix.get('nifty_declines', 'N/A')}
- Nifty Bank: {indices.get('Nifty Bank', {}).get('change_pct', 'N/A') if indices.get('Nifty Bank') else 'N/A'}%
- Nifty IT: {indices.get('Nifty IT', {}).get('change_pct', 'N/A') if indices.get('Nifty IT') else 'N/A'}%

News context (use only what's relevant, no fabrication):
{news_layer[:600]}

Describe the session. Use advance/decline and VIX for breadth. 90 words max.""",
        system=SYSTEM_PROMPT, max_tokens=200)

    print("  [AI] Writing macro section...")
    sections["macro_view"] = call_claude(
        prompt=f"""Write the Macro View section. Use ONLY the data and stories below. Do not invent.

News context:
{news_layer[:800]}

FX: USD/INR = {data.get('fx', {}).get('USD/INR', {}).get('last_price', 'N/A') if data.get('fx', {}).get('USD/INR') else 'N/A'}
US 10Y Yield: {data.get('bonds', {}).get('US 10Y Yield', {}).get('last_price', 'N/A') if data.get('bonds', {}).get('US 10Y Yield') else 'N/A'}

3-4 tightly sourced macro stories as prose. 120 words max. Attribute everything.""",
        system=SYSTEM_PROMPT, max_tokens=300)

    print("  [AI] Writing corporate section...")
    sections["corporate"] = call_claude(
        prompt=f"""Write the Corporate Action & Headlines section.

News context:
{news_layer[:800]}

Global context (Zerodha AMR):
{global_stories or 'Not available'}

Upcoming earnings:
{json.dumps(data.get('earnings_calendar', [])[:5], indent=2)}

4-6 concise corporate headlines as tight prose. 140 words max.""",
        system=SYSTEM_PROMPT, max_tokens=350)

    print("  [AI] Writing thematic commentary...")
    thematic_summary = "\n".join(
        f"- {name}: {d['basket_return_pct']:+.2f}% | Best: {d['top_performer']['symbol']} "
        f"({d['top_performer']['change_pct']:+.2f}%) | Worst: {d['worst_performer']['symbol']} "
        f"({d['worst_performer']['change_pct']:+.2f}%)"
        for name, d in (baskets or {}).items() if d)
    sections["thematic"] = call_claude(
        prompt=f"""Write the Thematic Tracker commentary.

Thematic basket performance today:
{thematic_summary or 'Data not available'}

One sentence per notable basket: what happened (number) + why it matters. 80 words max.""",
        system=SYSTEM_PROMPT, max_tokens=200)

    print("  [AI] Writing global pulse...")
    global_summary = "\n".join(
        f"- {name}: {d['last_price']:,.0f} ({d['change_pct']:+.2f}%)"
        for name, d in (global_m or {}).items() if d)
    sections["global_pulse"] = call_claude(
        prompt=f"""Write the Global Pulse section.

Global market closes:
{global_summary}

Global news context:
{global_stories or news_layer[:400]}

3-4 sentences: key global moves + India linkage. 80 words max.""",
        system=SYSTEM_PROMPT, max_tokens=200)

    print("  [AI] Writing capital flows section...")
    cf_items = [i for i in raw_news if i.get("category") == "capital_flows"][:8]
    cf_text = "\n".join(
        f"- {i['title']} (Source: {i['source']})" + (f"\n  {i['summary'][:120]}" if i.get("summary") else "")
        for i in cf_items) if cf_items else "No capital flow stories today."
    sections["capital_flows"] = call_claude(
        prompt=f"""Write the Capital Flows & Startup Ecosystem section for Undeployed Capital.

Stories to cover (use these — do not invent):
{cf_text}

Also from news context:
{news_context[:500] if news_context else 'Not available'}

3-4 sentences on funding rounds, IPOs, startup news + venture signal. Attribute all. 100 words max.""",
        system=SYSTEM_PROMPT, max_tokens=250)

    print("  [AI] Writing regulatory watch section...")
    reg_items = [i for i in raw_news if i.get("category") == "regulatory"][:8]
    reg_text = "\n".join(
        f"- {i['title']} (Source: {i['source']})" + (f"\n  {i['summary'][:120]}" if i.get("summary") else "")
        for i in reg_items) if reg_items else "No SEBI/RBI circulars today."
    sections["regulatory_watch"] = call_claude(
        prompt=f"""Write the Regulatory Watch section — SEBI and RBI.

Regulatory news today:
{reg_text}

2-4 sentences: what was announced + implication. If nothing, say "No significant circulars today." 100 words max.""",
        system=SYSTEM_PROMPT, max_tokens=250)

    management_quotes = amr.get("management_quotes", [])
    sections["management_chatter"] = management_quotes[0][:300] if management_quotes else None
    return sections


# ─────────────────────────────────────────────
# HTML HELPERS
# ─────────────────────────────────────────────

def _clean_ai(text: str) -> str:
    if not text:
        return text
    lines = [l for l in text.splitlines() if not l.strip().startswith("##")]
    return "\n".join(lines).strip()


def fmt_price(val, prefix="₹", decimals=2) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1_00_000:
        return f"{prefix}{val:,.0f}"
    return f"{prefix}{val:,.{decimals}f}"


def fmt_pct(val, show_sign=True) -> str:
    if val is None:
        return "—"
    sign = "+" if val >= 0 and show_sign else ""
    return f"{sign}{val:.2f}%"


def color_class(val) -> str:
    if val is None:
        return "neutral"
    return "gain" if val >= 0 else "loss"


def vix_sentiment_label(vix_val) -> tuple:
    if vix_val is None:
        return ("N/A", COLORS["neutral"])
    try:
        v = float(vix_val)
    except (TypeError, ValueError):
        return ("N/A", COLORS["neutral"])
    if v < 15:   return ("Low Fear",  COLORS["accent2"])
    if v < 20:   return ("Moderate",  COLORS["gold"])
    if v < 25:   return ("Elevated",  COLORS["amber"])
    return ("High Fear", COLORS["negative"])


def fmt_flow(val) -> str:
    if val is None:
        return "—"
    try:
        return f"₹{float(val):+,.0f} Cr"
    except (TypeError, ValueError):
        return "—"


def _nav_html() -> str:
    items = "\n".join(
        f'        <li><a href="#{anchor}" data-target="{anchor}">{label}</a></li>'
        for anchor, label in NAV_SECTIONS)
    return f"""<nav id="sidenav" class="sidenav">
    <div class="sidenav-title">Sections</div>
    <ul>
{items}
    </ul>
</nav>"""


# ─────────────────────────────────────────────
# HTML ASSEMBLY
# ─────────────────────────────────────────────

def build_html(data: dict, ai_sections: dict, charts: dict,
               mood: tuple, fear_greed: tuple, editors_take: str) -> str:
    indices         = data.get("indices", {})
    fii_dii         = data.get("fii_dii", {})
    commodities     = data.get("commodities", {})
    mcx_commodities = data.get("mcx_commodities", {})
    fx              = data.get("fx", {})
    bonds           = data.get("bonds", {})
    global_m        = data.get("global_markets", {})
    pivots          = data.get("pivot_points", {})
    baskets         = data.get("thematic_baskets", {})
    corp_acts       = data.get("corporate_actions", [])
    earnings        = data.get("earnings_calendar", [])
    vix_data        = data.get("market_status", {})
    gainers         = data.get("gainers_losers", {})
    amr             = data.get("zerodha_amr", {})
    option_chain    = data.get("option_chain")
    raw_news        = data.get("raw_news", [])
    data_source     = data.get("data_source", "yfinance")
    today_str       = data.get("trading_date", str(date.today()))
    gen_time        = data.get("generated_at", datetime.now().isoformat())

    nifty  = indices.get("Nifty 50") or {}
    sensex = indices.get("Sensex") or {}
    vix    = vix_data.get("india_vix") or {}

    mood_label, mood_color = mood
    fg_score, fg_label, _ = fear_greed

    vix_label_text, vix_label_color = vix_sentiment_label(vix.get("last"))

    try:
        adv = int(vix_data.get("nifty_advances") or 0)
        dec = int(vix_data.get("nifty_declines") or 0)
        ad_ratio = f"{adv}/{dec}" if (adv or dec) else "—"
        ad_color = color_class(adv - dec)
    except (ValueError, TypeError):
        ad_ratio, ad_color = "—", "neutral"

    fii_5d_val = fii_dii.get("fii_5d_cr") if fii_dii else None
    if fii_5d_val is not None and fii_5d_val != 0:
        verb = "net buyers" if fii_5d_val > 0 else "net sellers"
        fii_trend_sentence = f"FIIs have been {verb} over the past 5 sessions (₹{fii_5d_val:+,.0f} Cr cumulative)."
    else:
        fii_trend_sentence = ""

    # Sector rotation signal + most-significant theme (for What to Watch)
    sector_only = {k: v for k, v in indices.items() if v and k not in ("Nifty 50", "Sensex")}
    biggest_mover_sentence = ""
    if sector_only:
        best_s  = max(sector_only, key=lambda k: sector_only[k]["change_pct"])
        worst_s = min(sector_only, key=lambda k: sector_only[k]["change_pct"])
        bp = sector_only[best_s]["change_pct"]; wp = sector_only[worst_s]["change_pct"]
        bn = best_s.replace("Nifty ", ""); wn = worst_s.replace("Nifty ", "")
        if wp < 0 and bp > 0:
            rotation_signal = f"{wn} led declines ({wp:+.2f}%) while {bn} was the relative outperformer ({bp:+.2f}%)."
        elif bp > 0:
            rotation_signal = f"Broad gains: {bn} led ({bp:+.2f}%) with {wn} the laggard ({wp:+.2f}%)."
        else:
            rotation_signal = f"Risk-off session: {wn} led losses ({wp:+.2f}%), {bn} held up best ({bp:+.2f}%)."
        # Most significant theme = whichever sector moved most in absolute terms
        top_name, top_move = (bn, bp) if abs(bp) >= abs(wp) else (wn, wp)
        if abs(top_move) < 0.05:
            biggest_mover_sentence = ("Muted, range-bound session — no sector posted a "
                                      "meaningful move. Watch for a breakout catalyst next session.")
        elif top_move > 0:
            biggest_mover_sentence = f"{top_name} was the day's standout, moving {top_move:+.2f}% — watch for follow-through tomorrow."
        else:
            biggest_mover_sentence = f"{top_name} was the day's biggest mover at {top_move:+.2f}% — the key theme to track into the next session."
    else:
        rotation_signal = ""

    trade_date = datetime.fromisoformat(today_str).strftime("%A, %B %d, %Y")

    if data_source == "kite":
        source_badge_html = (f'<span class="data-pill data-pill-kite">Kite Connect</span>')
    else:
        source_badge_html = (f'<span class="data-pill data-pill-yf">yfinance</span>')

    # Sources footer
    sources_set = set()
    sources_set.add("NSE India" if not data.get("_nse_blocked") else "NSE India (mock)")
    if amr.get("headline"):
        sources_set.add("Zerodha AMR")
    sources_set.add("Zerodha Kite Connect" if data_source == "kite" else "yfinance")
    for item in raw_news:
        sources_set.add(item.get("source", ""))
    sources_footer_items = " · ".join(sorted(s for s in sources_set if s))

    # Regulatory + capital-flow tables
    reg_items = [i for i in raw_news if i.get("category") == "regulatory"][:6]
    reg_rows = "".join(
        f'<tr><td>{i["title"][:80]}</td><td class="dim" style="font-size:11px">{i["source"]}</td></tr>'
        for i in reg_items)
    cf_items = [i for i in raw_news if i.get("category") == "capital_flows"][:6]
    cf_rows = "".join(
        f'<tr><td>{i["title"][:80]}</td><td class="dim" style="font-size:11px">{i["source"]}</td></tr>'
        for i in cf_items)

    # Commodity tables
    commodity_rows = "".join(
        f'<tr><td>{name}</td><td class="mono">{fmt_price(d["last_price"])}</td>'
        f'<td class="mono {color_class(d["change_pct"])}">{fmt_pct(d["change_pct"])}</td>'
        f'<td class="mono dim">{fmt_price(d["prev_close"])}</td></tr>'
        for name, d in commodities.items() if d)
    mcx_rows = "".join(
        f'<tr><td>{name}</td><td class="mono">₹{d["last_price"]:,.0f}</td>'
        f'<td class="mono {color_class(d["change_pct"])}">{fmt_pct(d["change_pct"])}</td>'
        f'<td class="mono dim">₹{d["prev_close"]:,.0f}</td>'
        f'<td class="mono dim" style="font-size:11px">{d.get("tradingsymbol","")}</td></tr>'
        for name, d in (mcx_commodities or {}).items() if d)

    # FX + bonds
    fx_rows = ""
    for name, d in fx.items():
        if d:
            fx_rows += (f'<tr><td>{name}</td><td class="mono">{d["last_price"]:.4f}</td>'
                        f'<td class="mono {color_class(d["change_pct"])}">{fmt_pct(d["change_pct"])}</td></tr>')
    for name, d in bonds.items():
        if d:
            fx_rows += (f'<tr><td>{name}</td><td class="mono">{d["last_price"]:.2f}%</td>'
                        f'<td class="mono {color_class(d["change_pct"])}">{fmt_pct(d["change_pct"])}</td></tr>')

    # Global markets table (Phase 2) — explicit ordered set
    global_order = ["S&P 500", "Nasdaq", "Dow Jones", "Nikkei 225", "Hang Seng", "DAX", "FTSE 100"]
    global_alias = {"Nasdaq": ["Nasdaq", "Nasdaq 100"]}
    global_rows = ""
    for name in global_order:
        d = None
        for key in global_alias.get(name, [name]):
            if global_m.get(key):
                d = global_m[key]; break
        if d:
            global_rows += (f'<tr><td>{name}</td><td class="mono">{fmt_price(d["last_price"], prefix="")}</td>'
                            f'<td class="mono {color_class(d["change_pct"])}">{fmt_pct(d["change_pct"])}</td></tr>')

    # Gainers/Losers with HIGH VOL flag (Phase 3)
    def _vol_flag(g):
        v = g.get("volume"); av = g.get("avg_volume_20d")
        if v and av and av > 0 and (v / av) >= 2.5:
            return ' <span class="vol-flag">HIGH VOL</span>'
        return ""
    gainer_rows = "".join(
        f'<tr><td class="sym">{g["symbol"]}{_vol_flag(g)}</td><td class="mono">{fmt_price(g["ltp"])}</td>'
        f'<td class="mono gain">{fmt_pct(g["change_pct"])}</td></tr>'
        for g in (gainers.get("gainers") or []))
    loser_rows = "".join(
        f'<tr><td class="sym">{g["symbol"]}{_vol_flag(g)}</td><td class="mono">{fmt_price(g["ltp"])}</td>'
        f'<td class="mono loss">{fmt_pct(g["change_pct"])}</td></tr>'
        for g in (gainers.get("losers") or []))

    corp_rows = "".join(
        f'<tr><td>{ca.get("company","")}</td><td class="dim">{ca.get("purpose","")}</td>'
        f'<td class="mono dim">{ca.get("ex_date","")}</td></tr>'
        for ca in corp_acts[:12])

    # Earnings calendar table (Phase 2) — Company / Exchange / Result Date / Expected EPS
    earnings_rows = ""
    for e in earnings[:10]:
        exch = e.get("exchange") or ("BSE" if e.get("_source") == "bse" else "NSE")
        eps  = e.get("expected_eps") or "—"
        earnings_rows += (f'<tr><td>{e.get("company","")}</td><td class="sym">{exch}</td>'
                          f'<td class="mono dim">{e.get("date","")}</td><td class="mono dim">{eps}</td></tr>')

    thematic_rows = "".join(
        f'<tr><td>{name}</td><td class="mono {color_class(d["basket_return_pct"])}">{fmt_pct(d["basket_return_pct"])}</td>'
        f'<td class="sym gain">{d["top_performer"]["symbol"]} ({fmt_pct(d["top_performer"]["change_pct"])})</td>'
        f'<td class="sym loss">{d["worst_performer"]["symbol"]} ({fmt_pct(d["worst_performer"]["change_pct"])})</td>'
        f'<td class="dim">{d["num_stocks"]} stocks</td></tr>'
        for name, d in baskets.items() if d)

    # AI prose
    auto_headline   = _clean_ai(ai_sections.get("auto_headline", ""))
    intraday        = _clean_ai(ai_sections.get("intraday_narrative", "")) or "<em>Intraday narrative requires Claude API (set ANTHROPIC_API_KEY).</em>"
    macro_text      = _clean_ai(ai_sections.get("macro_view", ""))         or "<em>Macro view requires Claude API.</em>"
    corp_text       = _clean_ai(ai_sections.get("corporate", ""))          or "<em>Corporate section requires Claude API.</em>"
    thematic_t      = _clean_ai(ai_sections.get("thematic", ""))           or "<em>Thematic commentary requires Claude API.</em>"
    global_t        = _clean_ai(ai_sections.get("global_pulse", ""))       or "<em>Global pulse requires Claude API.</em>"
    capital_flows_t = _clean_ai(ai_sections.get("capital_flows", ""))
    regulatory_t    = _clean_ai(ai_sections.get("regulatory_watch", ""))
    mgmt_quote      = ai_sections.get("management_chatter")
    editors_take_c  = _clean_ai(editors_take)

    # What to Watch Tomorrow
    next_day = datetime.fromisoformat(today_str).date() + timedelta(days=1)
    econ_events = upcoming_econ_events(datetime.fromisoformat(today_str).date(), days=4)
    econ_rows = "".join(f'<tr><td class="mono dim">{d}</td><td>{label}</td></tr>' for d, label in econ_events) \
                or '<tr><td colspan="2" class="dim">No major scheduled events in the next 2 sessions.</td></tr>'

    # Day-at-a-glance
    summary_rows = f"""
        <tr><td>Nifty 50</td><td class="mono {color_class(nifty.get('change_pct'))}">{fmt_price(nifty.get('last_price'))} ({fmt_pct(nifty.get('change_pct'))})</td></tr>
        <tr><td>Sensex</td><td class="mono {color_class(sensex.get('change_pct'))}">{fmt_price(sensex.get('last_price'))} ({fmt_pct(sensex.get('change_pct'))})</td></tr>
        <tr><td>India VIX</td><td class="mono">{vix.get('last', '—')} ({fmt_pct(vix.get('change_pct'))})</td></tr>
        <tr><td>FII Net</td><td class="mono {color_class(fii_dii.get('fii_net_cr'))}">{fmt_flow(fii_dii.get('fii_net_cr'))}</td></tr>
        <tr><td>DII Net</td><td class="mono {color_class(fii_dii.get('dii_net_cr'))}">{fmt_flow(fii_dii.get('dii_net_cr'))}</td></tr>
        <tr><td>USD/INR</td><td class="mono">{fx.get('USD/INR', {}).get('last_price', '—') if fx.get('USD/INR') else '—'}</td></tr>
        <tr><td>Fear & Greed</td><td class="mono">{fg_score} · {fg_label}</td></tr>
        <tr><td>Market Mood</td><td class="mono">{mood_label}</td></tr>
    """ if fii_dii else ""

    amr_url = amr.get("url", "#") or "#"

    # Share-card text (JS uses these data attributes)
    share_nifty = f"{fmt_price(nifty.get('last_price'))} ({fmt_pct(nifty.get('change_pct'))})"
    share_vix   = f"{vix.get('last', '—')}"
    share_fii   = fmt_flow(fii_dii.get('fii_net_cr'))
    share_dii   = fmt_flow(fii_dii.get('dii_net_cr'))
    share_url   = f"{SITE_BASE_URL}/brief_{today_str}.html"

    gen_time_str = datetime.fromisoformat(gen_time).strftime('%I:%M %p IST')

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Undeployed Capital Brief — {trade_date}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
    <style>
        :root {{
            --bg: {COLORS['bg']}; --card: {COLORS['card']}; --border: {COLORS['border']};
            --accent: {COLORS['accent']}; --gain: {COLORS['accent2']}; --loss: {COLORS['negative']};
            --neutral: {COLORS['neutral']}; --text: {COLORS['text']}; --text-dim: {COLORS['text_dim']};
            --gold: {COLORS['gold']}; --amber: {COLORS['amber']};
            --shadow: rgba(0,0,0,0.4);
        }}
        [data-theme="light"] {{
            --bg: #F7F9FC; --card: #FFFFFF; --border: #E2E8F0;
            --accent: #2563EB; --gain: #16A34A; --loss: #DC2626;
            --neutral: #64748B; --text: #0F172A; --text-dim: #64748B;
            --gold: #B45309; --amber: #D97706;
            --shadow: rgba(15,23,42,0.08);
        }}

        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            background: var(--bg); color: var(--text);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 15px; line-height: 1.65;
            transition: background 0.25s ease, color 0.25s ease;
        }}

        /* ── Layout shell: side nav + content ───────────────── */
        .layout {{ display: flex; max-width: 1180px; margin: 0 auto; }}
        .content {{ flex: 1; min-width: 0; max-width: 860px; margin: 0 auto;
                    padding: 24px 20px 80px; scroll-margin-top: 20px; }}

        /* ── Sticky side nav ────────────────────────────────── */
        .sidenav {{
            position: sticky; top: 0; align-self: flex-start;
            width: 210px; height: 100vh; overflow-y: auto;
            padding: 28px 14px; border-right: 1px solid var(--border);
            flex-shrink: 0;
        }}
        .sidenav-title {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px;
                          color: var(--text-dim); margin-bottom: 12px; padding-left: 10px; }}
        .sidenav ul {{ list-style: none; }}
        .sidenav li a {{
            display: block; padding: 6px 10px; font-size: 13px; color: var(--text-dim);
            text-decoration: none; border-radius: 6px; border-left: 2px solid transparent;
            transition: all 0.15s ease;
        }}
        .sidenav li a:hover {{ color: var(--text); background: var(--card); }}
        .sidenav li a.active {{ color: var(--accent); border-left-color: var(--accent);
                                background: color-mix(in srgb, var(--accent) 10%, transparent); font-weight: 600; }}

        /* ── Top bar (theme toggle + buttons) ──────────────── */
        .topbar {{ display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
        .topbtn {{
            background: var(--card); color: var(--text-dim); border: 1px solid var(--border);
            border-radius: 7px; padding: 7px 12px; font-size: 12px; font-weight: 500;
            cursor: pointer; font-family: inherit; display: inline-flex; align-items: center; gap: 6px;
            transition: all 0.15s ease;
        }}
        .topbtn:hover {{ color: var(--text); border-color: var(--accent); }}

        /* ── Hamburger (mobile) ────────────────────────────── */
        .hamburger {{ display: none; background: var(--card); border: 1px solid var(--border);
                      border-radius: 7px; padding: 7px 11px; cursor: pointer; color: var(--text);
                      font-size: 16px; }}

        /* ── Typography ─────────────────────────────────────── */
        h1 {{ font-family: 'Space Grotesk', sans-serif; font-size: 30px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }}
        h2 {{ font-size: 13px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
              color: var(--accent); margin-bottom: 14px; padding-bottom: 6px;
              border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        h3 {{ font-size: 14px; font-weight: 600; color: var(--text-dim); margin-bottom: 8px; }}
        p  {{ color: var(--text); margin-bottom: 14px; }}
        .mono {{ font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace; font-size: 13px; }}
        .dim  {{ color: var(--text-dim); }}
        .gain {{ color: var(--gain); }}
        .loss {{ color: var(--loss); }}
        .sym  {{ font-family: "SF Mono", monospace; font-size: 12px; font-weight: 600; }}
        .neutral {{ color: var(--neutral); }}

        /* ── Brand wordmark ─────────────────────────────────── */
        .wordmark {{ font-family: 'Space Grotesk', sans-serif; font-size: 22px; font-weight: 700;
                     letter-spacing: -0.5px; color: var(--text); }}
        .wordmark .dot {{ color: var(--accent); }}
        .brief-subtitle {{ font-size: 12px; color: var(--text-dim); letter-spacing: 0.3px; margin-top: 4px;
                           display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}

        /* ── Mood hero banner ───────────────────────────────── */
        .hero {{
            background: linear-gradient(135deg, var(--card), color-mix(in srgb, {mood_color} 14%, var(--card)));
            border: 1px solid var(--border); border-left: 5px solid {mood_color};
            border-radius: 14px; padding: 26px 28px; margin: 8px 0 28px;
            box-shadow: 0 4px 20px var(--shadow);
        }}
        .hero-top {{ display: flex; justify-content: space-between; align-items: flex-start;
                     gap: 16px; flex-wrap: wrap; }}
        .mood-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 46px; font-weight: 700;
                       line-height: 1; color: {mood_color}; letter-spacing: -1px; }}
        .mood-sub {{ font-size: 13px; color: var(--text-dim); margin-top: 6px; }}
        .hero-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 22px; }}
        .hero-stat {{ }}
        .hero-stat .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-dim); }}
        .hero-stat .value {{ font-family: "SF Mono", monospace; font-size: 22px; font-weight: 700; margin-top: 3px; }}

        /* ── KPI cards ──────────────────────────────────────── */
        .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }}
        .vix-badge {{ display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
                      padding: 2px 7px; border-radius: 3px; text-transform: uppercase; vertical-align: middle; margin-left: 5px; }}
        .kpi-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
        .kpi-label {{ font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 4px; }}
        .kpi-value {{ font-size: 26px; font-weight: 700; font-family: "SF Mono", monospace; line-height: 1; }}
        .kpi-sub   {{ font-size: 12px; margin-top: 4px; }}

        .section {{ margin-bottom: 40px; scroll-margin-top: 16px; }}

        /* ── Sentiment badge ────────────────────────────────── */
        .sentiment-badge {{ font-size: 10px; font-weight: 700; letter-spacing: 0.5px; padding: 3px 8px;
                            border-radius: 4px; text-transform: uppercase; }}
        .vol-flag {{ font-size: 9px; font-weight: 700; letter-spacing: 0.4px; padding: 1px 5px;
                     border-radius: 3px; background: color-mix(in srgb, var(--amber) 18%, transparent);
                     color: var(--amber); border: 1px solid color-mix(in srgb, var(--amber) 45%, transparent); }}

        /* ── Editor's take ──────────────────────────────────── */
        .editors-take {{ background: var(--card); border: 1px solid var(--border);
                         border-left: 4px solid var(--gold); border-radius: 0 10px 10px 0;
                         padding: 18px 22px; margin-bottom: 28px; }}
        .editors-take .et-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
                                   color: var(--gold); font-weight: 700; margin-bottom: 8px; }}
        .editors-take p {{ font-size: 15.5px; line-height: 1.7; margin-bottom: 0; }}

        /* ── Tables (horizontally scrollable on mobile) ─────── */
        .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
        th {{ text-align: left; font-size: 11px; font-weight: 600; letter-spacing: 0.8px; text-transform: uppercase;
              color: var(--text-dim); padding: 6px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
        td {{ padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: color-mix(in srgb, var(--accent) 6%, transparent); }}

        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .grid-2  {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; align-items: start; }}

        .chart-wrap {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
                       padding: 16px; margin: 16px 0; }}
        .chart-wrap .plotly-graph-div {{ width: 100% !important; }}

        .pivot-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; font-family: monospace; font-size: 12px; }}
        .pivot-tag {{ padding: 4px 10px; border-radius: 4px; font-weight: 600; }}
        .pivot-r  {{ background: color-mix(in srgb, var(--loss) 14%, transparent); color: var(--loss); }}
        .pivot-p  {{ background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); }}
        .pivot-s  {{ background: color-mix(in srgb, var(--gain) 14%, transparent); color: var(--gain); }}

        .mgmt-quote {{ border-left: 3px solid var(--gold); padding: 12px 16px; margin: 16px 0;
                       background: var(--card); border-radius: 0 6px 6px 0; font-style: italic;
                       color: var(--text-dim); font-size: 14px; }}

        .source-banner {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
                          padding: 10px 14px; font-size: 12px; color: var(--text-dim); margin-bottom: 24px; }}
        .source-banner a {{ color: var(--accent); text-decoration: none; }}
        .data-pill {{ font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;
                      text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle; margin-left: 4px; }}
        .data-pill-kite {{ background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }}
        .data-pill-yf {{ background: color-mix(in srgb, var(--text-dim) 18%, transparent); color: var(--text-dim); }}

        .watch-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
                       padding: 16px 18px; margin-bottom: 16px; }}

        .footer {{ margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--border);
                   font-size: 12px; color: var(--text-dim); line-height: 1.6; }}

        /* ── Backdrop for mobile nav ───────────────────────── */
        .nav-backdrop {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 40; }}

        /* ════════ RESPONSIVE (< 768px) ════════ */
        @media (max-width: 900px) {{
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}
        @media (max-width: 768px) {{
            .hamburger {{ display: inline-flex; margin-right: auto; }}
            .topbar {{ justify-content: space-between; }}
            .sidenav {{
                position: fixed; top: 0; left: 0; z-index: 50;
                height: 100vh; width: 250px; background: var(--bg);
                transform: translateX(-100%); transition: transform 0.25s ease;
                box-shadow: 4px 0 24px var(--shadow);
            }}
            .sidenav.open {{ transform: translateX(0); }}
            .nav-backdrop.show {{ display: block; }}
            .content {{ padding: 16px 14px 70px; }}
            .hero {{ padding: 20px; }}
            .mood-label {{ font-size: 36px; }}
            .hero-stats {{ grid-template-columns: 1fr 1fr; }}
            .kpi-row {{ grid-template-columns: 1fr; }}
            .two-col {{ grid-template-columns: 1fr; }}
            h1 {{ font-size: 24px; }}
        }}

        /* ════════ PRINT ════════ */
        @media print {{
            @page {{ margin: 14mm; }}
            body {{ background: #fff !important; color: #000 !important; }}
            .sidenav, .nav-backdrop, .topbar, .hamburger {{ display: none !important; }}
            .layout {{ display: block; }}
            .content {{ max-width: 100%; padding: 0; }}
            .hero, .kpi-card, .chart-wrap, .editors-take, .watch-card, .source-banner {{
                box-shadow: none !important; break-inside: avoid; -webkit-print-color-adjust: exact; print-color-adjust: exact;
            }}
            .section {{ break-inside: avoid-page; }}
            a {{ color: #000 !important; text-decoration: none; }}
        }}
    </style>
</head>
<body>

<div class="nav-backdrop" id="navBackdrop" onclick="closeNav()"></div>

<div class="layout">
{_nav_html()}

<main class="content">

    <!-- ══════════ TOP BAR ══════════ -->
    <div class="topbar">
        <button class="hamburger" id="hamburger" onclick="openNav()" aria-label="Open navigation">☰</button>
        <button class="topbtn" onclick="window.print()" title="Print / Save as PDF">⬇ PDF</button>
        <button class="topbtn" id="shareBtn" onclick="shareSummary()" title="Copy summary for WhatsApp">📋 Share</button>
        <button class="topbtn" id="themeToggle" onclick="toggleTheme()" title="Toggle dark / light">🌙 Theme</button>
    </div>

    <!-- ══════════ BRAND HEADER ══════════ -->
    <div style="margin-bottom:6px">
        <div class="wordmark">Undeployed Capital<span class="dot">.</span></div>
        <div class="brief-subtitle">
            <span>{trade_date}</span><span>·</span>
            <span>Generated {gen_time_str}</span><span>·</span>
            <span>Data {source_badge_html}</span>
        </div>
    </div>

    <!-- ══════════ MOOD HERO ══════════ -->
    <section class="hero">
        <div class="hero-top">
            <div>
                <div class="mood-label">{mood_label}</div>
                <div class="mood-sub">{auto_headline or 'Daily Market Brief'}</div>
            </div>
        </div>
        <div class="hero-stats">
            <div class="hero-stat">
                <div class="label">Nifty 50</div>
                <div class="value {color_class(nifty.get('change_pct'))}">{fmt_price(nifty.get('last_price'), prefix='')}</div>
                <div class="mono {color_class(nifty.get('change_pct'))}" style="font-size:13px">{fmt_pct(nifty.get('change_pct'))}</div>
            </div>
            <div class="hero-stat">
                <div class="label">India VIX</div>
                <div class="value">{vix.get('last', '—')}</div>
                <div class="mono {color_class(vix.get('change_pct')) if vix else 'neutral'}" style="font-size:13px">{fmt_pct(vix.get('change_pct')) if vix else '—'}</div>
            </div>
            <div class="hero-stat">
                <div class="label">FII Net</div>
                <div class="value {color_class(fii_dii.get('fii_net_cr'))}" style="font-size:18px">{fmt_flow(fii_dii.get('fii_net_cr'))}</div>
            </div>
            <div class="hero-stat">
                <div class="label">Fear &amp; Greed</div>
                <div class="value">{fg_score}</div>
                <div class="dim" style="font-size:12px">{fg_label}</div>
            </div>
        </div>
    </section>

    <div class="source-banner">
        Data compiled from NSE India, {data_source},
        <a href="{amr_url}" target="_blank">Zerodha AfterMarket Report</a>, and a multi-source news pipeline.
        Not investment advice. For informational purposes only.
    </div>

    <!-- ══════════ EDITOR'S TAKE ══════════ -->
    <section class="section" id="editors-take">
        <div class="editors-take">
            <div class="et-label">✍ Editor's Take</div>
            {f'<p>{editors_take_c}</p>' if editors_take_c else '<p class="dim"><em>Editor&#39;s Take requires the Claude API (set ANTHROPIC_API_KEY). It will auto-generate a sharp analyst synthesis on every live run.</em></p>'}
        </div>
    </section>

    <!-- ══════════ MARKET SNAPSHOT + FEAR/GREED ══════════ -->
    <section class="section" id="market-snapshot">
        <h2>Market Snapshot</h2>
        <div class="grid-2">
            <div>
                <div class="kpi-row" style="grid-template-columns:1fr 1fr">
                    <div class="kpi-card">
                        <div class="kpi-label">Nifty 50</div>
                        <div class="kpi-value {color_class(nifty.get('change_pct'))}">{fmt_price(nifty.get('last_price'), prefix='')}</div>
                        <div class="kpi-sub {color_class(nifty.get('change_pct'))}">{fmt_pct(nifty.get('change_pct'))}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">India VIX</div>
                        <div class="kpi-value">{vix.get('last', '—')}</div>
                        <div class="kpi-sub" style="display:flex;align-items:center;gap:6px">
                            <span class="{color_class(vix.get('change_pct')) if vix else 'neutral'}">{fmt_pct(vix.get('change_pct')) if vix else '—'}</span>
                            <span class="vix-badge" style="background:{vix_label_color}22;color:{vix_label_color}">{vix_label_text}</span>
                        </div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">USD / INR</div>
                        <div class="kpi-value mono">{fx.get('USD/INR', {}).get('last_price', '—') if fx.get('USD/INR') else '—'}</div>
                        <div class="kpi-sub {color_class(fx.get('USD/INR', {}).get('change_pct') if fx.get('USD/INR') else None)}">{fmt_pct(fx.get('USD/INR', {}).get('change_pct')) if fx.get('USD/INR') else '—'}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Advance / Decline</div>
                        <div class="kpi-value {ad_color}">{ad_ratio}</div>
                        <div class="kpi-sub dim">Nifty 50 breadth</div>
                    </div>
                </div>
            </div>
            <div class="chart-wrap" style="margin-top:0">
                {charts.get('fear_greed', '')}
            </div>
        </div>
        <p style="margin-top:6px">{intraday}</p>
    </section>

    <!-- ══════════ TODAY'S PRICE ACTION ══════════ -->
    <section class="section" id="price-action">
        <h2>Today's Price Action</h2>
        <div class="chart-wrap">
            {charts.get('intraday', '')}
        </div>
    </section>

    <!-- ══════════ SECTORS ══════════ -->
    <section class="section" id="sectors">
        <h2>Sectors</h2>
        <div class="chart-wrap">{charts.get('sectors', '<p>Chart unavailable</p>')}</div>
        {f'<p class="dim" style="font-size:13px;margin-top:10px">{rotation_signal}</p>' if rotation_signal else ''}
        <h3 style="margin-top:18px">Sector Rotation</h3>
        <div class="chart-wrap">{charts.get('rotation', '')}</div>
        <div class="two-col" style="margin-top:8px">
            <div>
                <h3>Top Gainers (F&amp;O)</h3>
                <div class="table-wrap"><table>
                    <thead><tr><th>Symbol</th><th>LTP</th><th>Chg%</th></tr></thead>
                    <tbody>{gainer_rows or '<tr><td colspan="3" class="dim">Data unavailable</td></tr>'}</tbody>
                </table></div>
            </div>
            <div>
                <h3>Top Losers (F&amp;O)</h3>
                <div class="table-wrap"><table>
                    <thead><tr><th>Symbol</th><th>LTP</th><th>Chg%</th></tr></thead>
                    <tbody>{loser_rows or '<tr><td colspan="3" class="dim">Data unavailable</td></tr>'}</tbody>
                </table></div>
            </div>
        </div>
    </section>

    <!-- ══════════ TECHNICAL LEVELS ══════════ -->
    <section class="section" id="technical-levels">
        <h2>Key Technical Levels — Nifty 50</h2>
        <div class="pivot-row">
            <span class="pivot-tag pivot-r">R3 {pivots.get('R3', '—')}</span>
            <span class="pivot-tag pivot-r">R2 {pivots.get('R2', '—')}</span>
            <span class="pivot-tag pivot-r">R1 {pivots.get('R1', '—')}</span>
            <span class="pivot-tag pivot-p">Pivot {pivots.get('pivot', '—')}</span>
            <span class="pivot-tag pivot-s">S1 {pivots.get('S1', '—')}</span>
            <span class="pivot-tag pivot-s">S2 {pivots.get('S2', '—')}</span>
            <span class="pivot-tag pivot-s">S3 {pivots.get('S3', '—')}</span>
        </div>
        <p class="dim" style="font-size:12px">
            Floor pivots from today's high ({fmt_price(nifty.get('high'))}) · low ({fmt_price(nifty.get('low'))}) ·
            close ({fmt_price(nifty.get('last_price'))}). Source: NSE / yfinance.
        </p>
    </section>

    <!-- ══════════ INSTITUTIONAL FLOWS ══════════ -->
    <section class="section" id="institutional-flows">
        <h2>Institutional Flows {badge_institutional(data)}</h2>
        <div class="chart-wrap">{charts.get('fiidii', '<p>Chart unavailable</p>')}</div>
        <div class="table-wrap"><table>
            <thead><tr><th>Metric</th><th>Today</th><th>5-Day Rolling</th></tr></thead>
            <tbody>
                <tr><td>FII Net</td>
                    <td class="mono {color_class(fii_dii.get('fii_net_cr'))}">{fmt_flow(fii_dii.get('fii_net_cr'))}</td>
                    <td class="mono {color_class(fii_dii.get('fii_5d_cr'))}">{fmt_flow(fii_dii.get('fii_5d_cr'))}</td></tr>
                <tr><td>DII Net</td>
                    <td class="mono {color_class(fii_dii.get('dii_net_cr'))}">{fmt_flow(fii_dii.get('dii_net_cr'))}</td>
                    <td class="mono {color_class(fii_dii.get('dii_5d_cr'))}">{fmt_flow(fii_dii.get('dii_5d_cr'))}</td></tr>
            </tbody>
        </table></div>
        {f'<p style="font-size:13px;margin-top:10px">{fii_trend_sentence}</p>' if fii_trend_sentence else ''}
        <h3 style="margin-top:18px">30-Day Flow Trend</h3>
        <div class="chart-wrap">{charts.get('fiidii_hist', '')}</div>
        <p class="dim" style="font-size:12px; margin-top:8px">Source: NSE India provisional institutional data. History stored in docs/data/flows.json.</p>
    </section>

    <!-- ══════════ OPTION CHAIN ══════════ -->
    <section class="section" id="option-chain">
        <h2>Nifty Option Chain {badge_option_chain(data)}</h2>
        {f'''<div class="table-wrap" style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px">
            <div class="kpi-card" style="min-width:140px">
                <div class="kpi-label">Put-Call Ratio</div>
                <div class="kpi-value {'gain' if option_chain['pcr'] > 1 else 'loss'}">{option_chain['pcr']:.3f}</div>
                <div class="kpi-sub dim">{'Bullish bias' if option_chain['pcr'] > 1.2 else 'Bearish bias' if option_chain['pcr'] < 0.8 else 'Neutral'}</div>
            </div>
            <div class="kpi-card" style="min-width:140px">
                <div class="kpi-label">Max Pain</div>
                <div class="kpi-value mono">{option_chain['max_pain']:,.0f}</div>
                <div class="kpi-sub dim">Expiry: {option_chain['expiry']}</div>
            </div>
            <div class="kpi-card" style="min-width:140px">
                <div class="kpi-label">Key Call OI</div>
                <div class="kpi-value mono" style="font-size:18px">{" · ".join(f"{s:,.0f}" for s in option_chain['top_ce_oi_strikes'])}</div>
                <div class="kpi-sub dim">Resistance</div>
            </div>
            <div class="kpi-card" style="min-width:140px">
                <div class="kpi-label">Key Put OI</div>
                <div class="kpi-value mono" style="font-size:18px">{" · ".join(f"{s:,.0f}" for s in option_chain['top_pe_oi_strikes'])}</div>
                <div class="kpi-sub dim">Support</div>
            </div>
        </div>
        <div class="chart-wrap">{charts.get('option_chain', '')}</div>
        <p class="dim" style="font-size:12px;margin-top:8px">Source: Zerodha Kite Connect. PCR &gt; 1 = more put writing = bullish signal.</p>''' if option_chain else '<p class="dim">Option chain data requires Kite Connect. Run python3 kite_login.py to enable.</p>'}
    </section>

    <!-- ══════════ COMMODITIES ══════════ -->
    <section class="section" id="commodities">
        <h2>Commodities · Currency · Yields</h2>
        {f'''<h3 style="margin-bottom:6px">MCX India (₹) — via Kite Connect</h3>
        <div class="table-wrap"><table>
            <thead><tr><th>Instrument</th><th>Last (₹)</th><th>Chg%</th><th>Prev Close</th><th>Contract</th></tr></thead>
            <tbody>{mcx_rows}</tbody>
        </table></div>
        <p class="dim" style="font-size:11px;margin-top:4px">MCX prices in ₹. Source: Zerodha Kite Connect.</p>
        <h3 style="margin-top:16px;margin-bottom:6px">Global Futures (USD)</h3>''' if mcx_rows else ''}
        <div class="table-wrap"><table>
            <thead><tr><th>Instrument</th><th>Last</th><th>Chg%</th><th>Prev Close</th></tr></thead>
            <tbody>{commodity_rows}</tbody>
        </table></div>
        <div class="table-wrap"><table style="margin-top:12px">
            <thead><tr><th>Pair / Bond</th><th>Level</th><th>Chg%</th></tr></thead>
            <tbody>{fx_rows}</tbody>
        </table></div>
        <p class="dim" style="font-size:12px; margin-top:8px">Global commodity futures via yfinance. USD prices.</p>
    </section>

    <!-- ══════════ GLOBAL MARKETS TABLE ══════════ -->
    <section class="section" id="global-markets">
        <h2>Global Markets</h2>
        <div class="table-wrap"><table>
            <thead><tr><th>Index</th><th>Last</th><th>Chg%</th></tr></thead>
            <tbody>{global_rows or '<tr><td colspan="3" class="dim">Global index data unavailable</td></tr>'}</tbody>
        </table></div>
        <p class="dim" style="font-size:12px; margin-top:8px">Source: yfinance. Latest close / live level.</p>
    </section>

    <!-- ══════════ MACRO VIEW ══════════ -->
    <section class="section" id="macro-view">
        <h2>Macro View {badge_macro(data)}</h2>
        <p>{macro_text}</p>
    </section>

    <!-- ══════════ THEMATIC ══════════ -->
    <section class="section" id="thematic-tracker">
        <h2>Thematic Tracker</h2>
        <div class="chart-wrap">{charts.get('thematic', '<p>Chart unavailable</p>')}</div>
        <div class="table-wrap"><table>
            <thead><tr><th>Theme</th><th>Return</th><th>Best</th><th>Worst</th><th>Coverage</th></tr></thead>
            <tbody>{thematic_rows or '<tr><td colspan="5" class="dim">Data unavailable</td></tr>'}</tbody>
        </table></div>
        <p style="margin-top:14px">{thematic_t}</p>
        <p class="dim" style="font-size:12px">Source: yfinance (NSE). Equal-weighted basket returns.</p>
    </section>

    <!-- ══════════ EARNINGS CALENDAR ══════════ -->
    <section class="section" id="earnings-calendar">
        <h2>Earnings Calendar — Next 5 Trading Days</h2>
        <div class="table-wrap"><table>
            <thead><tr><th>Company</th><th>Exchange</th><th>Result Date</th><th>Expected EPS</th></tr></thead>
            <tbody>{earnings_rows or '<tr><td colspan="4" class="dim">No confirmed results in window — update manually in data or ECONOMIC_CALENDAR.</td></tr>'}</tbody>
        </table></div>
        <p class="dim" style="font-size:12px; margin-top:8px">Source: NSE/BSE board-meeting filings. EPS estimates manual where shown.</p>
    </section>

    <!-- ══════════ CORPORATE ══════════ -->
    <section class="section" id="corporate">
        <h2>Corporate &amp; Headlines</h2>
        <p>{corp_text}</p>
        {'<h3 style="margin-top:20px">Upcoming Corporate Actions</h3><div class="table-wrap"><table><thead><tr><th>Company</th><th>Purpose</th><th>Ex-Date</th></tr></thead><tbody>' + corp_rows + '</tbody></table></div>' if corp_rows else ''}
    </section>

    <!-- ══════════ GLOBAL PULSE ══════════ -->
    <section class="section" id="global-pulse">
        <h2>Global Pulse {badge_global(data)}</h2>
        <div class="chart-wrap">{charts.get('global', '<p>Chart unavailable</p>')}</div>
        <p>{global_t}</p>
    </section>

    <!-- ══════════ MANAGEMENT CHATTER ══════════ -->
    <section class="section" id="management-chatter">
        <h2>Management Chatter</h2>
        {'<div class="mgmt-quote">' + str(mgmt_quote) + '</div><p class="dim" style="font-size:12px">Source: <a href="' + amr_url + '" style="color:var(--accent)">Zerodha AfterMarket Report</a></p>' if mgmt_quote else '<p class="dim"><em>No management quotes captured today.</em></p>'}
    </section>

    <!-- ══════════ CAPITAL FLOWS ══════════ -->
    <section class="section" id="capital-flows">
        <h2>Capital Flows &amp; Startup Ecosystem</h2>
        {f'<p>{capital_flows_t}</p>' if capital_flows_t else '<p class="dim"><em>Capital flows section requires Claude API.</em></p>'}
        {f'<div class="table-wrap"><table style="margin-top:10px"><thead><tr><th>Story</th><th>Source</th></tr></thead><tbody>{cf_rows}</tbody></table></div>' if cf_rows else ''}
    </section>

    <!-- ══════════ REGULATORY WATCH ══════════ -->
    <section class="section" id="regulatory-watch">
        <h2>Regulatory Watch — SEBI · RBI</h2>
        {f'<p>{regulatory_t}</p>' if regulatory_t else '<p class="dim"><em>Regulatory section requires Claude API.</em></p>'}
        {f'<div class="table-wrap"><table style="margin-top:10px"><thead><tr><th>Circular / Announcement</th><th>Source</th></tr></thead><tbody>{reg_rows}</tbody></table></div>' if reg_rows else ''}
    </section>

    <!-- ══════════ WHAT TO WATCH TOMORROW ══════════ -->
    <section class="section" id="watch-tomorrow">
        <h2>What to Watch Tomorrow</h2>
        <div class="watch-card">
            <h3>Key Nifty Levels — Next Session</h3>
            <div class="pivot-row">
                <span class="pivot-tag pivot-r">Resistance R1 {pivots.get('R1', '—')}</span>
                <span class="pivot-tag pivot-p">Pivot {pivots.get('pivot', '—')}</span>
                <span class="pivot-tag pivot-s">Support S1 {pivots.get('S1', '—')}</span>
            </div>
            <p class="dim" style="font-size:12px;margin-bottom:0">A close above R1 ({pivots.get('R1', '—')}) keeps momentum; a break of S1 ({pivots.get('S1', '—')}) opens downside.</p>
        </div>
        <div class="watch-card">
            <h3>Scheduled Economic Events (next 2 sessions)</h3>
            <div class="table-wrap"><table>
                <thead><tr><th>Date</th><th>Event</th></tr></thead>
                <tbody>{econ_rows}</tbody>
            </table></div>
        </div>
        <div class="watch-card">
            <h3>Theme of the Day</h3>
            <p style="margin-bottom:0">{biggest_mover_sentence or 'No standout sector theme today.'}</p>
        </div>
    </section>

    <!-- ══════════ DAY AT A GLANCE ══════════ -->
    <section class="section" id="day-at-a-glance">
        <h2>Day at a Glance</h2>
        <div class="table-wrap"><table style="max-width:460px"
            data-date="{trade_date}" data-nifty="{share_nifty}" data-vix="{share_vix}"
            data-fii="{share_fii}" data-dii="{share_dii}" data-mood="{mood_label}" data-url="{share_url}" id="glanceTable">
            <thead><tr><th>Indicator</th><th>Reading</th></tr></thead>
            <tbody>{summary_rows}</tbody>
        </table></div>
    </section>

    <footer class="footer">
        <p><strong>Undeployed Capital</strong> is a VC and finance briefing for aspiring founders
           and early-career professionals. Published by Ishaan Sheth.</p>
        <p style="margin-top:8px">Market data reflects the {today_str} close. This is not investment advice.</p>
        <p style="margin-top:8px"><strong>Sources used today:</strong><br>
           {sources_footer_items or 'NSE India, yfinance, Zerodha AfterMarket Report'}
           · <a href="{amr_url}" style="color:var(--accent)">Zerodha AfterMarket Report</a></p>
    </footer>

</main>
</div>

<script>
// ── Theme toggle (localStorage-persisted) ──────────────────
(function () {{
    const saved = localStorage.getItem('uc-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    updateThemeBtn();
}})();
function toggleTheme() {{
    const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('uc-theme', next);
    updateThemeBtn();
    // Nudge Plotly charts to re-read CSS-driven sizing.
    window.dispatchEvent(new Event('resize'));
}}
function updateThemeBtn() {{
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    btn.innerHTML = isLight ? '☀ Theme' : '🌙 Theme';
}}

// ── Mobile nav ─────────────────────────────────────────────
function openNav() {{
    document.getElementById('sidenav').classList.add('open');
    document.getElementById('navBackdrop').classList.add('show');
}}
function closeNav() {{
    document.getElementById('sidenav').classList.remove('open');
    document.getElementById('navBackdrop').classList.remove('show');
}}
document.querySelectorAll('.sidenav a').forEach(a => a.addEventListener('click', closeNav));

// ── Scroll-spy: highlight active section ───────────────────
const navLinks = Array.from(document.querySelectorAll('.sidenav a'));
const sections = navLinks.map(a => document.getElementById(a.dataset.target)).filter(Boolean);
const spy = new IntersectionObserver((entries) => {{
    entries.forEach(e => {{
        if (e.isIntersecting) {{
            navLinks.forEach(l => l.classList.toggle('active', l.dataset.target === e.target.id));
        }}
    }});
}}, {{ rootMargin: '-20% 0px -70% 0px', threshold: 0 }});
sections.forEach(s => spy.observe(s));

// ── Resize Plotly on window resize (mobile safety) ─────────
window.addEventListener('resize', () => {{
    document.querySelectorAll('.plotly-graph-div').forEach(d => {{
        if (window.Plotly) window.Plotly.Plots.resize(d);
    }});
}});

// ── Share summary (WhatsApp/Telegram-formatted) ────────────
function shareSummary() {{
    const t = document.getElementById('glanceTable');
    const txt =
        '📊 Undeployed Capital — ' + t.dataset.date + '\\n' +
        'Nifty: ' + t.dataset.nifty + '\\n' +
        'VIX: ' + t.dataset.vix + '\\n' +
        'FII: ' + t.dataset.fii + ' | DII: ' + t.dataset.dii + '\\n' +
        'Mood: ' + t.dataset.mood + '\\n' +
        t.dataset.url;
    navigator.clipboard.writeText(txt).then(() => {{
        const b = document.getElementById('shareBtn');
        const old = b.innerHTML; b.innerHTML = '✓ Copied';
        setTimeout(() => b.innerHTML = old, 1800);
    }}).catch(() => {{
        window.prompt('Copy this summary:', txt);
    }});
}}
</script>

</body>
</html>"""
    return html


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Undeployed Capital Brief Generator")
    parser.add_argument("--data",     default=DATA_FILE, help="Path to data JSON")
    parser.add_argument("--no-ai",    action="store_true", help="Skip all Claude API calls")
    parser.add_argument("--substack", action="store_true", help="Also output Substack-ready inner HTML")
    args = parser.parse_args()

    print("=" * 60)
    print("  Undeployed Capital — Brief Generator")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p IST')}")
    print("=" * 60)

    print(f"\n[1/6] Loading data from {args.data}...")
    try:
        with open(args.data) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.data} not found. Run data_fetcher.py first.")
        sys.exit(1)

    # Persist + read rolling history for the new charts
    print("[2/6] Updating rolling history (flows.json / sectors.json)...")
    flows_hist  = update_flows_history(data)
    sector_hist = update_sector_history(data)

    print("[3/6] Computing intelligence layer (mood, fear & greed)...")
    mood       = compute_market_mood(data)
    fear_greed = compute_fear_greed(data)
    print(f"  Mood: {mood[0]} · Fear&Greed: {fear_greed[0]} ({fear_greed[1]})")

    print("[4/6] Generating Plotly charts...")
    charts = {
        "sectors":      chart_sector_performance(data.get("indices", {})),
        "thematic":     chart_thematic_baskets(data.get("thematic_baskets", {})),
        "global":       chart_global_markets(data.get("global_markets", {})),
        "fiidii":       chart_fii_dii_bars(data.get("fii_dii", {})),
        "option_chain": chart_option_chain(data.get("option_chain")),
        "intraday":     chart_intraday(data.get("intraday")),
        "fear_greed":   chart_fear_greed(fear_greed[0], fear_greed[1]),
        "fiidii_hist":  chart_fii_dii_history(flows_hist),
        "rotation":     chart_sector_rotation(sector_hist),
    }
    print(f"  ✓ {len(charts)} charts generated")

    # AI layers
    ai_sections, editors_take = {}, ""
    if not args.no_ai:
        print("[5/6] Generating AI layers...")
        if ANTHROPIC_API_KEY:
            print("  Claude prose sections...")
            ai_sections = generate_ai_sections(data)
        else:
            print("  ⚠️  ANTHROPIC_API_KEY not set — skipping Claude prose.")
        editors_take = generate_editors_take(data)
    else:
        print("[5/6] Skipping AI layers (--no-ai)")

    print("[6/6] Assembling HTML...")
    html = build_html(data, ai_sections, charts, mood, fear_greed, editors_take)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trade_date = data.get("trading_date", str(date.today()))
    out_path = os.path.join(OUTPUT_DIR, f"brief_{trade_date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Brief complete: {out_path}")
    print(f"   File size: {os.path.getsize(out_path) / 1024:.1f} KB")
    print(f"\n→ Open in browser: open {out_path}")

    if args.substack:
        import re as _re
        body_match = _re.search(r"<body[^>]*>(.*?)</body>", html, _re.DOTALL)
        if body_match:
            sub_path = os.path.join(OUTPUT_DIR, f"brief_{trade_date}_substack.html")
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(body_match.group(1).strip())
            print(f"→ Substack version: {sub_path}")


if __name__ == "__main__":
    main()
