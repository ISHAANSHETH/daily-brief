#!/usr/bin/env python3
"""
brief_generator.py — Undeployed Capital Daily Brief
Phase 1 + Phase 2: HTML article + charts generator

Takes the JSON output from data_fetcher.py and:
  1. Generates all Plotly charts (sector bars, thematic, global, FII/DII trend)
  2. Builds the Zerodha-AMR-style data tables
  3. Calls Claude API to write the prose sections
  4. Assembles the full HTML article
  5. Saves to brief_YYYY-MM-DD.html (ready to paste into Substack)

Requirements:
    pip install anthropic plotly pandas jinja2

Usage:
    python3 brief_generator.py [--data brief_data.json] [--no-ai]
    
    --no-ai: skip Claude API call (useful for testing layout)
"""

import json
import os
import sys
import argparse
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_FILE         = "brief_data.json"
OUTPUT_DIR        = "briefs"

# Visual identity for Undeployed Capital
# Dark financial terminal aesthetic — distinct from DayStarter's white/minimal look
COLORS = {
    "bg":          "#0D0F14",      # near-black background
    "card":        "#161B22",      # card surfaces
    "border":      "#21262D",      # subtle borders
    "accent":      "#58A6FF",      # electric blue — primary accent
    "accent2":     "#3FB950",      # green — gains
    "negative":    "#F85149",      # red — losses
    "neutral":     "#8B949E",      # muted text
    "text":        "#E6EDF3",      # primary text
    "text_dim":    "#7D8590",      # secondary text
    "gold":        "#D29922",      # highlight / special
}

CHART_LAYOUT = dict(
    paper_bgcolor = "rgba(0,0,0,0)",
    plot_bgcolor  = "rgba(0,0,0,0)",
    font          = dict(family="'SF Mono', 'Fira Code', monospace", color=COLORS["text"], size=12),
    margin        = dict(l=10, r=10, t=40, b=10),
    showlegend    = False,
)


# ─────────────────────────────────────────────
# CHART GENERATION — 4 charts total
# ─────────────────────────────────────────────

def chart_sector_performance(indices: dict) -> str:
    """
    Horizontal bar chart of all Nifty sector indices.
    Sorted by performance. Green/red bars. This is the DayStarter
    'Exhibit 2' equivalent but interactive.
    """
    sector_order = [
        "Nifty Metal", "Nifty IT", "Nifty Bank", "Nifty Realty",
        "Nifty Energy", "Nifty FMCG", "Nifty Auto", "Nifty Pharma",
        "Nifty 50", "Sensex"
    ]

    labels, values, colors = [], [], []
    for name in sector_order:
        data = indices.get(name)
        if data:
            labels.append(name.replace("Nifty ", ""))
            pct = data["change_pct"]
            values.append(pct)
            colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])

    if not labels:
        return "<p style='color:#7D8590'>Sector data unavailable</p>"

    # Sort by value
    pairs = sorted(zip(values, labels, colors), key=lambda x: x[0])
    values, labels, colors = zip(*pairs) if pairs else ([], [], [])

    fig = go.Figure(go.Bar(
        x=list(values),
        y=list(labels),
        orientation="h",
        marker=dict(color=list(colors), line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values],
        textposition="outside",
        textfont=dict(size=10, color=COLORS["text"]),
        hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Sector Performance", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(
            zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
            gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"],
        ),
        yaxis=dict(color=COLORS["text"], tickfont=dict(size=11)),
        height=360,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="chart_sectors")


def chart_thematic_baskets(baskets: dict) -> str:
    """
    Grouped bar chart of thematic basket returns.
    Each basket is one bar. Hovering shows constituent breakdown.
    This is the Phase 2 differentiator — DayStarter has nothing like this.
    """
    labels, values, colors, hover_texts = [], [], [], []

    for theme, data in baskets.items():
        if data is None:
            continue
        pct = data["basket_return_pct"]
        top = data["top_performer"]
        worst = data["worst_performer"]
        labels.append(theme)
        values.append(pct)
        colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])

        # Build hover with all constituents
        constituents_str = "<br>".join(
            f"  {sym}: {chg:+.2f}%"
            for sym, chg in sorted(
                data["constituents"].items(),
                key=lambda x: x[1], reverse=True
            )
        )
        hover_texts.append(
            f"<b>{theme}</b><br>"
            f"Basket: {pct:+.2f}%<br>"
            f"Best: {top['symbol']} ({top['change_pct']:+.2f}%)<br>"
            f"Worst: {worst['symbol']} ({worst['change_pct']:+.2f}%)<br>"
            f"<br>{constituents_str}"
        )

    if not labels:
        return "<p style='color:#7D8590'>Thematic data unavailable</p>"

    fig = go.Figure(go.Bar(
        x=labels,
        y=values,
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values],
        textposition="outside",
        textfont=dict(size=11, color=COLORS["text"]),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts,
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Thematic Tracker", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(
            tickangle=-20, color=COLORS["text"],
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
            gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"],
        ),
        height=340,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="chart_thematic")


def chart_global_markets(global_data: dict) -> str:
    """
    Dot + line chart showing global index performance.
    Sorted by change%. Shows which markets are dragging or lifting sentiment.
    """
    labels, values, colors = [], [], []

    for name, data in global_data.items():
        if data:
            labels.append(name)
            pct = data["change_pct"]
            values.append(pct)
            colors.append(COLORS["accent2"] if pct >= 0 else COLORS["negative"])

    if not labels:
        return "<p style='color:#7D8590'>Global data unavailable</p>"

    pairs = sorted(zip(values, labels, colors))
    values, labels, colors = zip(*pairs) if pairs else ([], [], [])

    fig = go.Figure(go.Bar(
        x=list(values),
        y=list(labels),
        orientation="h",
        marker=dict(color=list(colors), line=dict(width=0)),
        text=[f"{v:+.2f}%" for v in values],
        textposition="outside",
        textfont=dict(size=10, color=COLORS["text"]),
        hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Global Markets", font=dict(size=13, color=COLORS["text_dim"]), x=0),
        xaxis=dict(
            zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
            gridcolor=COLORS["border"], ticksuffix="%", color=COLORS["text_dim"],
        ),
        yaxis=dict(color=COLORS["text"], tickfont=dict(size=11)),
        height=320,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="chart_global")


def chart_fii_dii_bars(fii_dii: dict) -> str:
    """
    Simple FII vs DII comparison bar.
    Green = net buyer, Red = net seller.
    Shows today's flow with directional context.
    """
    if not fii_dii:
        return "<p style='color:#7D8590'>FII/DII data unavailable</p>"

    fii = fii_dii.get("fii_net_cr", 0)
    dii = fii_dii.get("dii_net_cr", 0)

    fig = go.Figure(go.Bar(
        x=["FII (Foreign)", "DII (Domestic)"],
        y=[fii, dii],
        marker=dict(
            color=[
                COLORS["accent2"] if fii >= 0 else COLORS["negative"],
                COLORS["accent2"] if dii >= 0 else COLORS["negative"],
            ],
            line=dict(width=0),
        ),
        text=[f"₹{fii:+,.0f} Cr", f"₹{dii:+,.0f} Cr"],
        textposition="outside",
        textfont=dict(size=12, color=COLORS["text"]),
        hovertemplate="%{x}: ₹%{y:,.0f} Cr<extra></extra>",
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"Institutional Flows — Net Today",
            font=dict(size=13, color=COLORS["text_dim"]), x=0
        ),
        xaxis=dict(color=COLORS["text"]),
        yaxis=dict(
            zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1,
            gridcolor=COLORS["border"], tickprefix="₹", ticksuffix=" Cr",
            color=COLORS["text_dim"],
        ),
        height=280,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="chart_fiidii")


def chart_option_chain(oc: dict) -> str:
    """
    Option chain OI chart: put vs call open interest by strike.
    Vertical lines for spot price and max pain.
    """
    if not oc or not oc.get("strikes"):
        return "<p style='color:#7D8590'>Option chain data unavailable (Kite Connect required)</p>"

    strikes_data = oc["strikes"]
    strikes  = [s["strike"] for s in strikes_data]
    call_oi  = [s["call_oi"] / 1_00_000 for s in strikes_data]  # lakhs
    put_oi   = [s["put_oi"]  / 1_00_000 for s in strikes_data]
    spot     = oc.get("spot_price", 0)
    max_pain = oc.get("max_pain", 0)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=strikes, y=call_oi,
        name="Call OI",
        marker=dict(color=COLORS["negative"], opacity=0.75),
        hovertemplate="Strike %{x}: %{y:.1f}L Call OI<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=strikes, y=put_oi,
        name="Put OI",
        marker=dict(color=COLORS["accent2"], opacity=0.75),
        hovertemplate="Strike %{x}: %{y:.1f}L Put OI<extra></extra>",
    ))

    shapes: list = []
    annotations: list = []
    if spot:
        shapes.append(dict(
            type="line", x0=spot, x1=spot, y0=0, y1=1, yref="paper",
            line=dict(color=COLORS["gold"], width=2, dash="dot"),
        ))
        annotations.append(dict(
            x=spot, y=1, yref="paper", text=f"Spot {spot:,.0f}",
            showarrow=False, font=dict(color=COLORS["gold"], size=10),
            xanchor="center", yanchor="bottom",
        ))
    if max_pain and max_pain != spot:
        shapes.append(dict(
            type="line", x0=max_pain, x1=max_pain, y0=0, y1=1, yref="paper",
            line=dict(color=COLORS["accent"], width=2, dash="dash"),
        ))
        annotations.append(dict(
            x=max_pain, y=0.85, yref="paper", text=f"Max Pain {max_pain:,.0f}",
            showarrow=False, font=dict(color=COLORS["accent"], size=10),
            xanchor="center", yanchor="bottom",
        ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"Nifty Option Chain OI — Expiry {oc.get('expiry', '')}",
            font=dict(size=13, color=COLORS["text_dim"]), x=0,
        ),
        barmode="group",
        xaxis=dict(title="Strike", color=COLORS["text"], tickfont=dict(size=10)),
        yaxis=dict(title="OI (Lakhs)", gridcolor=COLORS["border"], color=COLORS["text_dim"]),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=COLORS["text"])),
        shapes=shapes,
        annotations=annotations,
        height=320,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="chart_optchain")


# ─────────────────────────────────────────────
# CLAUDE API — PROSE GENERATION
# ─────────────────────────────────────────────

def call_claude(prompt: str, system: str, max_tokens: int = 1800) -> str:
    """
    Call Claude claude-sonnet-4-6 to generate prose sections.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"  [Claude API error] {e}")
        return f"[AI prose unavailable: {e}]"


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
    """
    Generate all prose sections via Claude.
    Returns a dict of section_name -> html_string.
    """
    if not ANTHROPIC_API_KEY:
        print("  [AI] No API key set. Skipping prose generation.")
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
    option_chain = data.get("option_chain")

    nifty = indices.get("Nifty 50", {}) or {}

    # Use news_context as the primary news layer, falling back to AMR/Pulse
    amr_stories   = "\n".join(f"- {s}" for s in (amr.get("top_india_stories", []) or [])[:6])
    pulse_stories = "\n".join(f"- {h}" for h in (pulse or [])[:6])
    global_stories = "\n".join(f"- {s}" for s in (amr.get("global_stories", []) or [])[:5])
    news_layer = news_context or f"{amr_stories}\n{pulse_stories}"

    # ── 0. Auto-headline ───────────────────────────────────────────────────
    print("  [AI] Writing auto-headline...")
    _nifty_chg = nifty.get('change_pct') or 0
    _nifty_dir = "rises" if _nifty_chg >= 0 else "falls"
    sections["auto_headline"] = call_claude(
        prompt=f"""Write ONE punchy Bloomberg-style headline summarising today's Indian market session.
Max 15 words. No quotes. No full stop at end.

Key facts:
- Nifty 50: {nifty.get('last_price', 'N/A')} ({_nifty_chg:+.2f}%, {_nifty_dir})
- India VIX: {vix.get('india_vix', {}).get('last', 'N/A') if vix.get('india_vix') else 'N/A'}
- Top news today (use at most one item, only if number is given):
{news_layer[:400]}

Format: "Nifty [action] [number]%; [one key driver]"
Example: "Nifty Drops 1.2% as Rising Crude Pressures Energy Sector"
Output the headline only — no explanation.""",
        system=SYSTEM_PROMPT,
        max_tokens=40,
    )

    # ── 1. Intraday narrative ──────────────────────────────────────────────
    print("  [AI] Writing intraday narrative...")
    sections["intraday_narrative"] = call_claude(
        prompt=f"""Write the intraday narrative for Nifty 50 today.

Market data:
- Nifty 50 close: {nifty.get('last_price', 'N/A')} ({_nifty_chg:+.2f}% vs prev close {nifty.get('prev_close', 'N/A')})
- Day high: {nifty.get('high', 'N/A')}, Day low: {nifty.get('low', 'N/A')}
- India VIX: {vix.get('india_vix', {}).get('last', 'N/A') if vix.get('india_vix') else 'N/A'} ({vix.get('india_vix', {}).get('change_pct', '') if vix.get('india_vix') else ''}%)
- Advances: {vix.get('nifty_advances', 'N/A')}, Declines: {vix.get('nifty_declines', 'N/A')}
- Nifty Bank: {indices.get('Nifty Bank', {}).get('change_pct', 'N/A') if indices.get('Nifty Bank') else 'N/A'}%
- Nifty IT: {indices.get('Nifty IT', {}).get('change_pct', 'N/A') if indices.get('Nifty IT') else 'N/A'}%
- Nifty Pharma: {indices.get('Nifty Pharma', {}).get('change_pct', 'N/A') if indices.get('Nifty Pharma') else 'N/A'}%
- Nifty Metal: {indices.get('Nifty Metal', {}).get('change_pct', 'N/A') if indices.get('Nifty Metal') else 'N/A'}%

News context (use only what's relevant, no fabrication):
{news_layer[:600]}

Describe the session: how it opened, key turning points, sectors that led or dragged, how it closed.
Use the advance/decline ratio and VIX for breadth context. 90 words max.""",
        system=SYSTEM_PROMPT,
        max_tokens=200,
    )

    # ── 2. Macro section ───────────────────────────────────────────────────
    print("  [AI] Writing macro section...")
    sections["macro_view"] = call_claude(
        prompt=f"""Write the Macro View section. Use ONLY the data and stories provided below.
Do not invent any policy decisions, rates, or numbers not listed here.

News context (use what's relevant, cite source for each fact):
{news_layer[:800]}

FX: USD/INR = {data.get('fx', {}).get('USD/INR', {}).get('last_price', 'N/A') if data.get('fx', {}).get('USD/INR') else 'N/A'} ({data.get('fx', {}).get('USD/INR', {}).get('change_pct', 0) if data.get('fx', {}).get('USD/INR') else 0:+.2f}%)
US 10Y Yield: {data.get('bonds', {}).get('US 10Y Yield', {}).get('last_price', 'N/A') if data.get('bonds', {}).get('US 10Y Yield') else 'N/A'}

Write 3-4 tightly sourced macro stories as prose paragraphs (not bullets).
Each paragraph = one macro story. 120 words total max.
Attribute everything in parentheses: (Source: Mint), (RBI), (ET Economy) etc.""",
        system=SYSTEM_PROMPT,
        max_tokens=300,
    )

    # ── 3. Corporate section ───────────────────────────────────────────────
    print("  [AI] Writing corporate section...")
    sections["corporate"] = call_claude(
        prompt=f"""Write the Corporate Action & Headlines section.

News context (market and company news — use with source attribution):
{news_layer[:800]}

Global context (Zerodha AMR):
{global_stories or 'Not available'}

Upcoming earnings this week:
{json.dumps(data.get('earnings_calendar', [])[:5], indent=2)}

Write 4-6 concise corporate headlines as tight prose paragraphs.
Each sentence = one story + its market implication. 140 words max.
If earnings are due, call them out with company name and date.""",
        system=SYSTEM_PROMPT,
        max_tokens=350,
    )

    # ── 4. Thematic commentary ─────────────────────────────────────────────
    print("  [AI] Writing thematic commentary...")
    thematic_summary = "\n".join(
        f"- {name}: {d['basket_return_pct']:+.2f}% | "
        f"Best: {d['top_performer']['symbol']} ({d['top_performer']['change_pct']:+.2f}%) | "
        f"Worst: {d['worst_performer']['symbol']} ({d['worst_performer']['change_pct']:+.2f}%)"
        for name, d in (baskets or {}).items() if d
    )
    sections["thematic"] = call_claude(
        prompt=f"""Write the Thematic Tracker commentary for Undeployed Capital.

Thematic basket performance today:
{thematic_summary or 'Data not available'}

For each basket with notable movement, one sentence: what happened (number) + why it matters for the thesis.
Diagnostics is our own coverage area — extra sentence if notable.
80 words max.""",
        system=SYSTEM_PROMPT,
        max_tokens=200,
    )

    # ── 5. Global pulse ────────────────────────────────────────────────────
    print("  [AI] Writing global pulse...")
    global_summary = "\n".join(
        f"- {name}: {d['last_price']:,.0f} ({d['change_pct']:+.2f}%)"
        for name, d in (global_m or {}).items() if d
    )
    sections["global_pulse"] = call_claude(
        prompt=f"""Write the Global Pulse section.

Global market closes:
{global_summary}

Global news context:
{global_stories or news_layer[:400]}

Write 3-4 sentences: key global moves + what they signal for Indian markets tomorrow.
Always explain the India linkage explicitly. 80 words max.""",
        system=SYSTEM_PROMPT,
        max_tokens=200,
    )

    # ── 6. Capital Flows (VC / Startup) ───────────────────────────────────
    print("  [AI] Writing capital flows section...")
    # Extract capital flow items from raw_news
    cf_items = [i for i in raw_news if i.get("category") == "capital_flows"][:8]
    cf_text = "\n".join(
        f"- {i['title']} (Source: {i['source']})"
        + (f"\n  {i['summary'][:120]}" if i.get("summary") else "")
        for i in cf_items
    ) if cf_items else "No capital flow stories today."
    sections["capital_flows"] = call_claude(
        prompt=f"""Write the Capital Flows & Startup Ecosystem section for Undeployed Capital.
Our readers are aspiring founders and early-career VC/finance professionals.

Stories to cover (use these — do not invent):
{cf_text}

Also from news context (pick relevant items only):
{news_context[:500] if news_context else 'Not available'}

Write 3-4 sentences covering notable funding rounds, IPO activity, startup news,
and what it signals for the Indian venture ecosystem.
If there are no capital flow stories today, say so in one sentence.
Attribute all items by source. 100 words max.""",
        system=SYSTEM_PROMPT,
        max_tokens=250,
    )

    # ── 7. Regulatory Watch (SEBI / RBI) ──────────────────────────────────
    print("  [AI] Writing regulatory watch section...")
    reg_items = [i for i in raw_news if i.get("category") == "regulatory"][:8]
    reg_text = "\n".join(
        f"- {i['title']} (Source: {i['source']})"
        + (f"\n  {i['summary'][:120]}" if i.get("summary") else "")
        for i in reg_items
    ) if reg_items else "No SEBI/RBI circulars or announcements today."
    sections["regulatory_watch"] = call_claude(
        prompt=f"""Write the Regulatory Watch section — SEBI and RBI circulars and policy updates.

Regulatory news today (use these with attribution):
{reg_text}

Write 2-4 sentences covering the most market-relevant regulatory developments.
For each item: what was announced + direct implication for investors/founders.
If nothing notable today, say "No significant circulars today."
100 words max.""",
        system=SYSTEM_PROMPT,
        max_tokens=250,
    )

    # ── 8. Management chatter ──────────────────────────────────────────────
    management_quotes = amr.get("management_quotes", [])
    if management_quotes:
        sections["management_chatter"] = management_quotes[0][:300]
    else:
        sections["management_chatter"] = None

    return sections


# ─────────────────────────────────────────────
# HTML ASSEMBLY
# ─────────────────────────────────────────────

def _clean_ai(text: str) -> str:
    """Strip markdown headers and stray ## lines from Claude prose output."""
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
    """Returns (label_text, hex_color) for India VIX value."""
    if vix_val is None:
        return ("N/A", COLORS["neutral"])
    try:
        v = float(vix_val)
    except (TypeError, ValueError):
        return ("N/A", COLORS["neutral"])
    if v < 15:   return ("Low Fear",  COLORS["accent2"])
    if v < 20:   return ("Moderate",  COLORS["gold"])
    if v < 25:   return ("Elevated",  "#FF8C00")
    return ("High Fear", COLORS["negative"])


def fmt_flow(val) -> str:
    """Format FII/DII flow value safely. Returns '—' for None/missing."""
    if val is None:
        return "—"
    try:
        return f"₹{float(val):+,.0f} Cr"
    except (TypeError, ValueError):
        return "—"


def build_html(data: dict, ai_sections: dict, charts: dict) -> str:
    """
    Build the complete HTML article.
    
    Architecture:
    - Single self-contained HTML file
    - Plotly loaded from CDN (one load for all charts)
    - Dark terminal theme throughout
    - Substack-pasteable (copy the <body> content)
    
    Regarding Zerodha AMR scraping and charts:
    DayStarter shows static SVG bar charts (their "Exhibit" visuals).
    We build those same data visualisations as interactive Plotly charts,
    but we compute them from the same underlying data (NSE + yfinance).
    We do NOT copy DayStarter's HTML or images — we generate our own visuals
    from raw data and attribute sources identically to how they do.
    """
    indices        = data.get("indices", {})
    fii_dii        = data.get("fii_dii", {})
    commodities    = data.get("commodities", {})
    mcx_commodities = data.get("mcx_commodities", {})
    fx             = data.get("fx", {})
    bonds          = data.get("bonds", {})
    global_m       = data.get("global_markets", {})
    pivots         = data.get("pivot_points", {})
    baskets        = data.get("thematic_baskets", {})
    corp_acts      = data.get("corporate_actions", [])
    earnings       = data.get("earnings_calendar", [])
    vix_data       = data.get("market_status", {})
    gainers        = data.get("gainers_losers", {})
    amr            = data.get("zerodha_amr", {})
    option_chain   = data.get("option_chain")
    raw_news       = data.get("raw_news", [])
    data_source    = data.get("data_source", "yfinance")
    today_str      = data.get("trading_date", str(date.today()))
    gen_time       = data.get("generated_at", datetime.now().isoformat())

    nifty  = indices.get("Nifty 50") or {}
    sensex = indices.get("Sensex") or {}
    vix    = vix_data.get("india_vix") or {}

    # ── VIX sentiment badge ───────────────────────────────────────────────
    vix_label_text, vix_label_color = vix_sentiment_label(vix.get("last"))

    # ── Advance / Decline ratio ───────────────────────────────────────────
    try:
        adv = int(vix_data.get("nifty_advances") or 0)
        dec = int(vix_data.get("nifty_declines") or 0)
        ad_ratio = f"{adv}/{dec}" if (adv or dec) else "—"
        ad_color = color_class(adv - dec)
    except (ValueError, TypeError):
        ad_ratio, ad_color = "—", "neutral"

    # ── FII 5-day trend sentence ──────────────────────────────────────────
    fii_5d_val = fii_dii.get("fii_5d_cr") if fii_dii else None
    if fii_5d_val is not None:
        if fii_5d_val > 0:
            fii_trend_sentence = (
                f"FIIs have been net buyers over the past 5 sessions "
                f"(₹{fii_5d_val:+,.0f} Cr cumulative)."
            )
        elif fii_5d_val < 0:
            fii_trend_sentence = (
                f"FIIs have been net sellers over the past 5 sessions "
                f"(₹{fii_5d_val:+,.0f} Cr cumulative)."
            )
        else:
            fii_trend_sentence = ""
    else:
        fii_trend_sentence = ""

    # ── Sector rotation signal ────────────────────────────────────────────
    sector_only = {k: v for k, v in indices.items()
                   if v and k not in ("Nifty 50", "Sensex")}
    if sector_only:
        best_s  = max(sector_only, key=lambda k: sector_only[k]["change_pct"])
        worst_s = min(sector_only, key=lambda k: sector_only[k]["change_pct"])
        bp = sector_only[best_s]["change_pct"]
        wp = sector_only[worst_s]["change_pct"]
        bn = best_s.replace("Nifty ", "")
        wn = worst_s.replace("Nifty ", "")
        if wp < 0 and bp > 0:
            rotation_signal = (
                f"{wn} led declines ({wp:+.2f}%) while {bn} was the relative outperformer ({bp:+.2f}%)."
            )
        elif bp > 0:
            rotation_signal = (
                f"Broad gains: {bn} led ({bp:+.2f}%) with {wn} the laggard ({wp:+.2f}%)."
            )
        else:
            rotation_signal = (
                f"Risk-off session: {wn} led losses ({wp:+.2f}%), "
                f"{bn} held up best ({bp:+.2f}%)."
            )
    else:
        rotation_signal = ""

    trade_date = datetime.fromisoformat(today_str).strftime("%A, %B %d, %Y")
    day_of_week = datetime.fromisoformat(today_str).strftime("%A")

    # ── Data source badge text ────────────────────────────────────────────
    if data_source == "kite":
        source_badge_html = (
            f'<span style="background:{COLORS["accent"]}22;color:{COLORS["accent"]};'
            f'font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;'
            f'text-transform:uppercase;letter-spacing:0.5px;vertical-align:middle;margin-left:8px">'
            f'Kite Connect</span>'
        )
    else:
        source_badge_html = (
            f'<span style="background:{COLORS["text_dim"]}22;color:{COLORS["text_dim"]};'
            f'font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;'
            f'text-transform:uppercase;letter-spacing:0.5px;vertical-align:middle;margin-left:8px">'
            f'yfinance</span>'
        )

    # ── Sources Used Today (for footer) ───────────────────────────────────
    sources_set = set()
    sources_set.add("NSE India" if not data.get("_nse_blocked") else "NSE India (mock)")
    sources_set.add("Zerodha AMR" if amr.get("headline") else "")
    if data_source == "kite":
        sources_set.add("Zerodha Kite Connect")
    else:
        sources_set.add("yfinance")
    for item in raw_news:
        sources_set.add(item.get("source", ""))
    sources_list = sorted(s for s in sources_set if s)
    sources_footer_items = " · ".join(sources_list)

    # ── Regulatory watch items table ──────────────────────────────────────
    reg_items  = [i for i in raw_news if i.get("category") == "regulatory"][:6]
    reg_rows = ""
    for item in reg_items:
        reg_rows += f"""
        <tr>
            <td>{item['title'][:80]}</td>
            <td class="dim" style="font-size:11px">{item['source']}</td>
        </tr>"""

    # ── Capital flow items table ──────────────────────────────────────────
    cf_items = [i for i in raw_news if i.get("category") == "capital_flows"][:6]
    cf_rows = ""
    for item in cf_items:
        cf_rows += f"""
        <tr>
            <td>{item['title'][:80]}</td>
            <td class="dim" style="font-size:11px">{item['source']}</td>
        </tr>"""

    # ── Build commodity table rows ────────────────────────────────────────
    commodity_rows = ""
    for name, d in commodities.items():
        if d:
            commodity_rows += f"""
            <tr>
                <td>{name}</td>
                <td class="mono">{fmt_price(d['last_price'])}</td>
                <td class="mono {color_class(d['change_pct'])}">{fmt_pct(d['change_pct'])}</td>
                <td class="mono dim">{fmt_price(d['prev_close'])}</td>
            </tr>"""

    # ── MCX commodity rows (₹, from Kite) ────────────────────────────────
    mcx_rows = ""
    for name, d in (mcx_commodities or {}).items():
        if d:
            mcx_rows += f"""
            <tr>
                <td>{name}</td>
                <td class="mono">₹{d['last_price']:,.0f}</td>
                <td class="mono {color_class(d['change_pct'])}">{fmt_pct(d['change_pct'])}</td>
                <td class="mono dim">₹{d['prev_close']:,.0f}</td>
                <td class="mono dim" style="font-size:11px">{d.get('tradingsymbol','')}</td>
            </tr>"""

    # ── FX + Bond table ───────────────────────────────────────────────────
    fx_rows = ""
    for name, d in fx.items():
        if d:
            fx_rows += f"""
            <tr>
                <td>{name}</td>
                <td class="mono">{d['last_price']:.4f}</td>
                <td class="mono {color_class(d['change_pct'])}">{fmt_pct(d['change_pct'])}</td>
            </tr>"""
    for name, d in bonds.items():
        if d:
            fx_rows += f"""
            <tr>
                <td>{name}</td>
                <td class="mono">{d['last_price']:.2f}%</td>
                <td class="mono {color_class(d['change_pct'])}">{fmt_pct(d['change_pct'])}</td>
            </tr>"""

    # ── Gainers/Losers table ──────────────────────────────────────────────
    gainer_rows = ""
    for g in (gainers.get("gainers") or []):
        gainer_rows += f"""
        <tr>
            <td class="sym">{g['symbol']}</td>
            <td class="mono">{fmt_price(g['ltp'])}</td>
            <td class="mono gain">{fmt_pct(g['change_pct'])}</td>
        </tr>"""

    loser_rows = ""
    for g in (gainers.get("losers") or []):
        loser_rows += f"""
        <tr>
            <td class="sym">{g['symbol']}</td>
            <td class="mono">{fmt_price(g['ltp'])}</td>
            <td class="mono loss">{fmt_pct(g['change_pct'])}</td>
        </tr>"""

    # ── Corporate actions table ───────────────────────────────────────────
    corp_rows = ""
    for ca in corp_acts[:12]:
        corp_rows += f"""
        <tr>
            <td>{ca.get('company','')}</td>
            <td class="dim">{ca.get('purpose','')}</td>
            <td class="mono dim">{ca.get('ex_date','')}</td>
        </tr>"""

    # ── Earnings calendar rows ────────────────────────────────────────────
    earnings_rows = ""
    for e in earnings[:8]:
        earnings_rows += f"""
        <tr>
            <td>{e.get('company','')}</td>
            <td class="sym">{e.get('symbol','')}</td>
            <td class="mono dim">{e.get('date','')}</td>
            <td class="dim">{e.get('purpose','')[:40]}</td>
        </tr>"""

    # ── Thematic basket rows (for the table below the chart) ─────────────
    thematic_rows = ""
    for name, d in baskets.items():
        if d:
            pct = d["basket_return_pct"]
            top = d["top_performer"]
            worst = d["worst_performer"]
            thematic_rows += f"""
            <tr>
                <td>{name}</td>
                <td class="mono {color_class(pct)}">{fmt_pct(pct)}</td>
                <td class="sym gain">{top['symbol']} ({fmt_pct(top['change_pct'])})</td>
                <td class="sym loss">{worst['symbol']} ({fmt_pct(worst['change_pct'])})</td>
                <td class="dim">{d['num_stocks']} stocks</td>
            </tr>"""

    # ── AI prose ─────────────────────────────────────────────────────────
    auto_headline    = _clean_ai(ai_sections.get("auto_headline", ""))
    intraday         = _clean_ai(ai_sections.get("intraday_narrative", "")) or "<em>Intraday narrative unavailable.</em>"
    macro_text       = _clean_ai(ai_sections.get("macro_view", ""))       or "<em>Macro view unavailable.</em>"
    corp_text        = _clean_ai(ai_sections.get("corporate", ""))         or "<em>Corporate section unavailable.</em>"
    thematic_t       = _clean_ai(ai_sections.get("thematic", ""))          or "<em>Thematic commentary unavailable.</em>"
    global_t         = _clean_ai(ai_sections.get("global_pulse", ""))      or "<em>Global pulse unavailable.</em>"
    capital_flows_t  = _clean_ai(ai_sections.get("capital_flows", ""))
    regulatory_t     = _clean_ai(ai_sections.get("regulatory_watch", ""))
    mgmt_quote       = ai_sections.get("management_chatter")

    # ── Day-at-a-glance summary table ────────────────────────────────────
    summary_rows = f"""
        <tr><td>Nifty 50</td><td class="mono {color_class(nifty.get('change_pct'))}">{fmt_price(nifty.get('last_price'))} ({fmt_pct(nifty.get('change_pct'))})</td></tr>
        <tr><td>Sensex</td><td class="mono {color_class(sensex.get('change_pct'))}">{fmt_price(sensex.get('last_price'))} ({fmt_pct(sensex.get('change_pct'))})</td></tr>
        <tr><td>India VIX</td><td class="mono">{vix.get('last', '—')} ({fmt_pct(vix.get('change_pct'))})</td></tr>
        <tr><td>FII Net</td><td class="mono {color_class(fii_dii.get('fii_net_cr'))}">{fmt_flow(fii_dii.get('fii_net_cr'))}</td></tr>
        <tr><td>DII Net</td><td class="mono {color_class(fii_dii.get('dii_net_cr'))}">{fmt_flow(fii_dii.get('dii_net_cr'))}</td></tr>
        <tr><td>USD/INR</td><td class="mono">{fx.get('USD/INR', {}).get('last_price', '—') if fx.get('USD/INR') else '—'}</td></tr>
        <tr><td>Nifty Pivot</td><td class="mono">{pivots.get('pivot', '—')}</td></tr>
        <tr><td>Nifty R1 / S1</td><td class="mono">{pivots.get('R1', '—')} / {pivots.get('S1', '—')}</td></tr>
    """ if fii_dii else ""

    amr_url = amr.get("url", "#")
    amr_headline = amr.get("headline", "Zerodha AfterMarket Report")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Undeployed Capital Brief — {trade_date}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
    <style>
        /* ── Reset & Base ─────────────────────────────────── */
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            background: {COLORS["bg"]};
            color: {COLORS["text"]};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 15px;
            line-height: 1.65;
            max-width: 860px;
            margin: 0 auto;
            padding: 24px 20px 60px;
        }}

        /* ── Typography ──────────────────────────────────── */
        h1 {{ font-size: 28px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }}
        h2 {{ font-size: 13px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; 
              color: {COLORS["accent"]}; margin-bottom: 14px; padding-bottom: 6px;
              border-bottom: 1px solid {COLORS["border"]}; }}
        h3 {{ font-size: 14px; font-weight: 600; color: {COLORS["text_dim"]}; margin-bottom: 8px; }}
        p  {{ color: {COLORS["text"]}; margin-bottom: 14px; }}
        .mono {{ font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace; font-size: 13px; }}
        .dim  {{ color: {COLORS["text_dim"]}; }}
        .gain {{ color: {COLORS["accent2"]}; }}
        .loss {{ color: {COLORS["negative"]}; }}
        .sym  {{ font-family: "SF Mono", monospace; font-size: 12px; font-weight: 600; }}
        .neutral {{ color: {COLORS["neutral"]}; }}

        /* ── Header ──────────────────────────────────────── */
        .brief-header {{
            margin-bottom: 32px;
            padding-bottom: 20px;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .brief-meta {{
            font-size: 12px;
            color: {COLORS["text_dim"]};
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            display: flex;
            gap: 16px;
        }}
        .brand {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: {COLORS["accent"]};
            margin-bottom: 8px;
        }}
        .lede {{
            font-size: 16px;
            color: {COLORS["text_dim"]};
            line-height: 1.5;
            margin-top: 8px;
        }}

        /* ── KPI Hero Numbers ────────────────────────────── */
        .kpi-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 28px;
        }}
        .vix-badge {{
            display: inline-block; font-size: 10px; font-weight: 700;
            letter-spacing: 0.5px; padding: 2px 7px; border-radius: 3px;
            text-transform: uppercase; vertical-align: middle; margin-left: 5px;
        }}
        .kpi-card {{
            background: {COLORS["card"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 6px;
            padding: 16px;
        }}
        .kpi-label {{ font-size: 11px; color: {COLORS["text_dim"]}; text-transform: uppercase; 
                      letter-spacing: 0.8px; margin-bottom: 4px; }}
        .kpi-value {{ font-size: 26px; font-weight: 700; font-family: "SF Mono", monospace; line-height: 1; }}
        .kpi-sub   {{ font-size: 12px; margin-top: 4px; }}

        /* ── Sections ────────────────────────────────────── */
        .section {{ margin-bottom: 36px; }}

        /* ── Tables ──────────────────────────────────────── */
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
        th {{
            text-align: left;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            color: {COLORS["text_dim"]};
            padding: 6px 8px;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        td {{
            padding: 7px 8px;
            border-bottom: 1px solid {COLORS["border"]}22;
            vertical-align: middle;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: {COLORS["card"]}; }}

        /* ── Two-column layout (gainers/losers) ──────────── */
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}

        /* ── Chart containers ────────────────────────────── */
        .chart-wrap {{
            background: {COLORS["card"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 6px;
            padding: 16px;
            margin: 16px 0;
        }}

        /* ── Pivot levels ────────────────────────────────── */
        .pivot-row {{
            display: flex; gap: 8px; flex-wrap: wrap;
            margin: 12px 0; font-family: monospace; font-size: 12px;
        }}
        .pivot-tag {{
            padding: 4px 10px; border-radius: 4px; font-weight: 600;
        }}
        .pivot-r  {{ background: {COLORS["negative"]}22; color: {COLORS["negative"]}; }}
        .pivot-p  {{ background: {COLORS["accent"]}22; color: {COLORS["accent"]}; }}
        .pivot-s  {{ background: {COLORS["accent2"]}22; color: {COLORS["accent2"]}; }}

        /* ── Management quote ────────────────────────────── */
        .mgmt-quote {{
            border-left: 3px solid {COLORS["gold"]};
            padding: 12px 16px;
            margin: 16px 0;
            background: {COLORS["card"]};
            border-radius: 0 6px 6px 0;
            font-style: italic;
            color: {COLORS["text_dim"]};
            font-size: 14px;
        }}

        /* ── AMR attribution banner ──────────────────────── */
        .source-banner {{
            background: {COLORS["card"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 6px;
            padding: 10px 14px;
            font-size: 12px;
            color: {COLORS["text_dim"]};
            margin-bottom: 20px;
        }}
        .source-banner a {{ color: {COLORS["accent"]}; text-decoration: none; }}

        /* ── Footer ──────────────────────────────────────── */
        .footer {{
            margin-top: 48px;
            padding-top: 20px;
            border-top: 1px solid {COLORS["border"]};
            font-size: 12px;
            color: {COLORS["text_dim"]};
            line-height: 1.6;
        }}

        @media (max-width: 700px) {{
            .kpi-row {{ grid-template-columns: 1fr 1fr; }}
            .two-col {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>

<!-- ═══════════════════════════════════ HEADER ═══════════════════════════════ -->
<header class="brief-header">
    <div class="brief-meta">
        <span>{trade_date}</span>
        <span>·</span>
        <span>Generated {datetime.fromisoformat(gen_time).strftime('%I:%M %p IST')}</span>
        <span>·</span>
        <span>Data {source_badge_html}</span>
    </div>
    <div class="brand">Undeployed Capital</div>
    {f'<h1>{auto_headline}</h1>' if auto_headline else '<h1>Daily Market Brief</h1>'}
    <p class="lede">
        Nifty 50 at <strong>{fmt_price(nifty.get('last_price'))}</strong>
        <span class="{color_class(nifty.get('change_pct'))}">&nbsp;{fmt_pct(nifty.get('change_pct'))}</span>
        &nbsp;·&nbsp;
        India VIX <strong>{vix.get('last', '—')}</strong>
        <span class="vix-badge" style="background:{vix_label_color}22;color:{vix_label_color}">{vix_label_text}</span>
        &nbsp;·&nbsp;
        FII net <span class="{color_class(fii_dii.get('fii_net_cr'))}">{fmt_flow(fii_dii.get('fii_net_cr'))}</span>
    </p>
</header>

<div class="source-banner">
    Data compiled from NSE India, {data_source},
    <a href="{amr_url}" target="_blank">Zerodha AfterMarket Report</a>,
    and multi-source news pipeline.
    Not investment advice. For informational purposes only.
</div>

<!-- ═══════════════════════════════ KPI SNAPSHOT ═════════════════════════════ -->
<section class="section">
    <h2>Market Snapshot</h2>
    <div class="kpi-row">
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

    <p>{intraday}</p>
</section>

<!-- ═══════════════════════════════ SECTOR CHART ═════════════════════════════ -->
<section class="section">
    <h2>Sectors</h2>
    <div class="chart-wrap">
        {charts.get('sectors', '<p>Chart unavailable</p>')}
    </div>

    {f'<p class="dim" style="font-size:13px;margin-top:10px">{rotation_signal}</p>' if rotation_signal else ''}

    <div class="two-col">
        <div>
            <h3>Top Gainers (F&amp;O)</h3>
            <table>
                <thead><tr><th>Symbol</th><th>LTP</th><th>Chg%</th></tr></thead>
                <tbody>{gainer_rows or '<tr><td colspan="3" class="dim">Data unavailable</td></tr>'}</tbody>
            </table>
        </div>
        <div>
            <h3>Top Losers (F&amp;O)</h3>
            <table>
                <thead><tr><th>Symbol</th><th>LTP</th><th>Chg%</th></tr></thead>
                <tbody>{loser_rows or '<tr><td colspan="3" class="dim">Data unavailable</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</section>

<!-- ═══════════════════════════════ PIVOT LEVELS ═════════════════════════════ -->
<section class="section">
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
        Floor pivot points computed from today's high ({fmt_price(nifty.get('high'))}) · 
        low ({fmt_price(nifty.get('low'))}) · close ({fmt_price(nifty.get('last_price'))}).
        Source: NSE / yfinance.
    </p>
</section>

<!-- ═══════════════════════════════ FII / DII ════════════════════════════════ -->
<section class="section">
    <h2>Institutional Flows</h2>
    <div class="chart-wrap">
        {charts.get('fiidii', '<p>Chart unavailable</p>')}
    </div>
    <table>
        <thead><tr><th>Metric</th><th>Today</th><th>5-Day Rolling</th></tr></thead>
        <tbody>
            <tr>
                <td>FII Net</td>
                <td class="mono {color_class(fii_dii.get('fii_net_cr'))}">{fmt_flow(fii_dii.get('fii_net_cr'))}</td>
                <td class="mono {color_class(fii_dii.get('fii_5d_cr'))}">{fmt_flow(fii_dii.get('fii_5d_cr'))}</td>
            </tr>
            <tr>
                <td>DII Net</td>
                <td class="mono {color_class(fii_dii.get('dii_net_cr'))}">{fmt_flow(fii_dii.get('dii_net_cr'))}</td>
                <td class="mono {color_class(fii_dii.get('dii_5d_cr'))}">{fmt_flow(fii_dii.get('dii_5d_cr'))}</td>
            </tr>
        </tbody>
    </table>
    {f'<p style="font-size:13px;margin-top:10px">{fii_trend_sentence}</p>' if fii_trend_sentence else ''}
    <p class="dim" style="font-size:12px; margin-top:8px">Source: NSE India provisional institutional data.</p>
</section>

<!-- ═══════════════════════════════ OPTION CHAIN ══════════════════════════════ -->
<section class="section">
    <h2>Nifty Option Chain</h2>
    {f'''<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:16px">
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
            <div class="kpi-label">Key Call OI (Resistance)</div>
            <div class="kpi-value mono" style="font-size:18px">{" · ".join(f"{s:,.0f}" for s in option_chain['top_ce_oi_strikes'])}</div>
            <div class="kpi-sub dim">Top 3 call OI strikes</div>
        </div>
        <div class="kpi-card" style="min-width:140px">
            <div class="kpi-label">Key Put OI (Support)</div>
            <div class="kpi-value mono" style="font-size:18px">{" · ".join(f"{s:,.0f}" for s in option_chain['top_pe_oi_strikes'])}</div>
            <div class="kpi-sub dim">Top 3 put OI strikes</div>
        </div>
    </div>
    <div class="chart-wrap">
        {charts.get('option_chain', '')}
    </div>
    <p class="dim" style="font-size:12px;margin-top:8px">Source: Zerodha Kite Connect (NFO instruments). PCR &gt; 1 = more put writing = bullish signal.</p>''' if option_chain else '<p class="dim">Option chain data requires Kite Connect. Run python3 kite_login.py to enable.</p>'}
</section>

<!-- ═══════════════════════════════ COMMODITIES ══════════════════════════════ -->
<section class="section">
    <h2>Commodities · Currency · Yields</h2>
    {f'''<h3 style="margin-bottom:6px">MCX India (₹) — via Kite Connect</h3>
    <table>
        <thead><tr><th>Instrument</th><th>Last (₹)</th><th>Chg%</th><th>Prev Close</th><th>Contract</th></tr></thead>
        <tbody>{mcx_rows}</tbody>
    </table>
    <p class="dim" style="font-size:11px;margin-top:4px">MCX prices in Indian Rupees (₹). Source: Zerodha Kite Connect.</p>
    <h3 style="margin-top:16px;margin-bottom:6px">Global Futures (USD)</h3>''' if mcx_rows else ''}
    <table>
        <thead><tr><th>Instrument</th><th>Last</th><th>Chg%</th><th>Prev Close</th></tr></thead>
        <tbody>{commodity_rows}</tbody>
    </table>
    <table style="margin-top:12px">
        <thead><tr><th>Pair / Bond</th><th>Level</th><th>Chg%</th></tr></thead>
        <tbody>{fx_rows}</tbody>
    </table>
    <p class="dim" style="font-size:12px; margin-top:8px">Global commodity futures via yfinance. USD prices.</p>
</section>

<!-- ═══════════════════════════════ MACRO VIEW ═══════════════════════════════ -->
<section class="section">
    <h2>Macro View</h2>
    <p>{macro_text}</p>
</section>

<!-- ═══════════════════════════════ THEMATIC ═════════════════════════════════ -->
<section class="section">
    <h2>Thematic Tracker</h2>
    <div class="chart-wrap">
        {charts.get('thematic', '<p>Chart unavailable</p>')}
    </div>
    <table>
        <thead><tr><th>Theme</th><th>Return</th><th>Best</th><th>Worst</th><th>Coverage</th></tr></thead>
        <tbody>{thematic_rows or '<tr><td colspan="5" class="dim">Data unavailable</td></tr>'}</tbody>
    </table>
    <p style="margin-top:14px">{thematic_t}</p>
    <p class="dim" style="font-size:12px">Source: yfinance (NSE). Equal-weighted basket returns.</p>
</section>

<!-- ═══════════════════════════════ CORPORATE ════════════════════════════════ -->
<section class="section">
    <h2>Corporate &amp; Headlines</h2>
    <p>{corp_text}</p>
    {'<h3 style="margin-top:20px">Upcoming Earnings (Next 14 Days)</h3><table><thead><tr><th>Company</th><th>Symbol</th><th>Date</th><th>Purpose</th></tr></thead><tbody>' + earnings_rows + '</tbody></table>' if earnings_rows else ''}
    {'<h3 style="margin-top:20px">Upcoming Corporate Actions</h3><table><thead><tr><th>Company</th><th>Purpose</th><th>Ex-Date</th></tr></thead><tbody>' + corp_rows + '</tbody></table>' if corp_rows else ''}
</section>

<!-- ═══════════════════════════════ GLOBAL ═══════════════════════════════════ -->
<section class="section">
    <h2>Global Pulse</h2>
    <div class="chart-wrap">
        {charts.get('global', '<p>Chart unavailable</p>')}
    </div>
    <p>{global_t}</p>
</section>

<!-- ═══════════════════════════════ MANAGEMENT CHATTER ═══════════════════════ -->
{'<section class="section"><h2>Management Chatter</h2><div class="mgmt-quote">' + str(mgmt_quote) + '</div><p class="dim" style="font-size:12px">Source: <a href="' + amr_url + '" style="color:' + COLORS["accent"] + '">Zerodha AfterMarket Report</a></p></section>' if mgmt_quote else ''}

<!-- ═══════════════════════════════ CAPITAL FLOWS ════════════════════════════ -->
<section class="section">
    <h2>Capital Flows &amp; Startup Ecosystem</h2>
    {f'<p>{capital_flows_t}</p>' if capital_flows_t else '<p class="dim"><em>Capital flows section requires Claude API. Use --no-ai to skip.</em></p>'}
    {f'''<table style="margin-top:10px">
        <thead><tr><th>Story</th><th>Source</th></tr></thead>
        <tbody>{cf_rows}</tbody>
    </table>''' if cf_rows else ''}
</section>

<!-- ═══════════════════════════════ REGULATORY WATCH ════════════════════════ -->
<section class="section">
    <h2>Regulatory Watch — SEBI · RBI</h2>
    {f'<p>{regulatory_t}</p>' if regulatory_t else '<p class="dim"><em>Regulatory section requires Claude API. Use --no-ai to skip.</em></p>'}
    {f'''<table style="margin-top:10px">
        <thead><tr><th>Circular / Announcement</th><th>Source</th></tr></thead>
        <tbody>{reg_rows}</tbody>
    </table>''' if reg_rows else ''}
</section>

<!-- ═══════════════════════════════ DAY AT A GLANCE ════════════════════════ -->
<section class="section">
    <h2>Day at a Glance</h2>
    <table style="max-width:420px">
        <thead><tr><th>Indicator</th><th>Reading</th></tr></thead>
        <tbody>{summary_rows}</tbody>
    </table>
</section>

<!-- ═══════════════════════════════ FOOTER ═══════════════════════════════════ -->
<footer class="footer">
    <p>
        <strong>Undeployed Capital</strong> is a VC and finance briefing for aspiring founders
        and early-career professionals. Published by Ishaan Sheth.
    </p>
    <p style="margin-top:8px">
        Market data reflects the {today_str} close. This is not investment advice.
    </p>
    <p style="margin-top:8px">
        <strong>Sources used today:</strong><br>
        {sources_footer_items or 'NSE India, yfinance, Zerodha AfterMarket Report'}
        · <a href="{amr_url}" style="color:{COLORS['accent']}">Zerodha AfterMarket Report</a>
    </p>
</footer>

</body>
</html>"""

    return html


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Undeployed Capital Brief Generator")
    parser.add_argument("--data",      default=DATA_FILE, help="Path to data JSON")
    parser.add_argument("--no-ai",     action="store_true", help="Skip Claude API call")
    parser.add_argument("--substack",  action="store_true", help="Also output Substack-ready inner HTML")
    args = parser.parse_args()

    print("=" * 60)
    print("  Undeployed Capital — Brief Generator")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p IST')}")
    print("=" * 60)

    # Load data
    print(f"\n[1/4] Loading data from {args.data}...")
    try:
        with open(args.data) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.data} not found. Run data_fetcher.py first.")
        sys.exit(1)

    # Generate charts
    print("[2/4] Generating Plotly charts...")
    charts = {
        "sectors":      chart_sector_performance(data.get("indices", {})),
        "thematic":     chart_thematic_baskets(data.get("thematic_baskets", {})),
        "global":       chart_global_markets(data.get("global_markets", {})),
        "fiidii":       chart_fii_dii_bars(data.get("fii_dii", {})),
        "option_chain": chart_option_chain(data.get("option_chain")),
    }
    print(f"  ✓ {len(charts)} charts generated")

    # Generate AI prose
    ai_sections = {}
    if not args.no_ai:
        if not ANTHROPIC_API_KEY:
            print("[3/4] ⚠️  ANTHROPIC_API_KEY not set. Skipping AI prose.")
            print("       Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
        else:
            print("[3/4] Generating AI prose sections via Claude...")
            ai_sections = generate_ai_sections(data)
            print(f"  ✓ {len(ai_sections)} sections written")
    else:
        print("[3/4] Skipping AI prose (--no-ai flag set)")

    # Build HTML
    print("[4/4] Assembling HTML article...")
    html = build_html(data, ai_sections, charts)

    # Save
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
            substack_html = body_match.group(1).strip()
            sub_path = os.path.join(OUTPUT_DIR, f"brief_{trade_date}_substack.html")
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(substack_html)
            print(f"→ Substack version: {sub_path}")
        else:
            print("→ [Substack] Could not extract body content")


if __name__ == "__main__":
    main()
