#!/usr/bin/env python3
"""
bulletin_generator.py — Undeployed Capital · Morning Bulletin

A SEPARATE product from the daily financial brief: a short, scannable digest of
the day's most important Indian business stories — each a punchy headline plus a
3-4 sentence detailed summary. Think "morning newsletter", not "market terminal".

Pipeline:
  1. Reads the news already gathered by data_fetcher.py (brief_data.json → raw_news,
     zerodha_amr, pulse_headlines).
  2. Picks the most business-relevant stories (corporate / startup / capital flows /
     regulatory), ranked by the news pipeline's own score.
  3. Asks Claude (Claude-only — never OpenAI) to write N numbered bulletin items as
     strict JSON: {headline, body, sources}.
  4. Renders a standalone, mobile-responsive HTML page (own design, dark/light toggle).
  5. Saves briefs/bulletin_YYYY-MM-DD.html and mirrors to docs/briefs/, then refreshes
     the BULLETINS list on docs/index.html.

Usage:
    python3 bulletin_generator.py [--data brief_data.json] [--n 6] [--no-ai]
"""

import json
import os
import re
import sys
import argparse
from datetime import datetime, date


# ── .env autoload (Claude key) ──────────────────────────────────────────────
def _load_dotenv(path: str = ".env") -> None:
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
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_FILE  = "brief_data.json"
OUTPUT_DIR = "briefs"
DOCS_DIR   = os.path.join("docs", "briefs")
INDEX_FILE = os.path.join("docs", "index.html")

COLORS = {
    "bg": "#0D0F14", "card": "#161B22", "border": "#21262D", "accent": "#58A6FF",
    "gold": "#D29922", "text": "#E6EDF3", "text_dim": "#7D8590", "neutral": "#8B949E",
}

# Categories that belong in a business bulletin (skip pure index/market-level moves)
BULLETIN_CATEGORIES = {"capital_flows", "regulatory", "general", "market"}


# ─────────────────────────────────────────────
# CLAUDE
# ─────────────────────────────────────────────

def call_claude(prompt: str, system: str, max_tokens: int = 2200) -> str:
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
        return ""


BULLETIN_SYSTEM = """You are the editor of the Undeployed Capital Morning Bulletin — a
sharp, scannable digest of the most important Indian business stories of the day,
written for founders and early-career finance/VC professionals.

Voice: crisp business-news desk. Factual, specific, confident. Every story leads with
concrete facts — company names, numbers, ₹/$ figures, dates.

Hard rules:
- Use ONLY the source material provided. Never invent facts, numbers, names, or quotes.
- If a story lacks a number, don't fabricate one.
- Each story: a tight headline (3-6 words, title case) + a body of 3-4 full sentences.
- Body must read like a polished bulletin paragraph, not a list.
- Pick the most consequential, distinct stories — no two items on the same event.
- Prefer corporate moves, fundraises, IPOs, startup/VC, regulatory (SEBI/RBI), big deals.
- Output STRICT JSON only — no prose, no markdown fences."""


def select_news(data: dict, pool: int = 28) -> list:
    """Rank business-relevant news items by the pipeline's score."""
    raw = data.get("raw_news", []) or []
    items = [i for i in raw if i.get("category") in BULLETIN_CATEGORIES and i.get("title")]
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    # de-dupe by title prefix
    seen, out = set(), []
    for i in items:
        key = (i.get("title") or "")[:40].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
        if len(out) >= pool:
            break
    return out


def generate_bulletin_items(data: dict, n: int = 6) -> list:
    """Return list of {headline, body, sources:[...]}. Claude-only."""
    if not ANTHROPIC_API_KEY:
        print("  [Bulletin] ANTHROPIC_API_KEY not set — skipping AI generation.")
        return []

    news = select_news(data)
    if not news:
        print("  [Bulletin] No business news in pipeline today.")
        return []

    source_block = "\n".join(
        f"- [{i.get('source','')}] {i.get('title','')}"
        + (f"\n  {i.get('summary','')[:220]}" if i.get("summary") else "")
        for i in news
    )

    prompt = f"""From the source items below, write the {n} most important business stories
for today's Morning Bulletin.

SOURCE ITEMS (use only these — do not invent):
{source_block}

Return STRICT JSON: an array of exactly {n} objects (or fewer if not enough distinct
stories exist), each:
{{
  "headline": "Tight Title-Case Headline",
  "body": "3-4 full sentences. Lead with concrete facts: company names, ₹/$ figures, dates, percentages drawn ONLY from the source items.",
  "sources": ["Source Name", ...]
}}
Output the JSON array and nothing else."""

    raw = call_claude(prompt, BULLETIN_SYSTEM, max_tokens=2600)
    if not raw:
        return []

    # Strip code fences if present, then locate the JSON array
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        print("  [Bulletin] Could not parse JSON from Claude output.")
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"  [Bulletin] JSON decode error: {e}")
        return []

    clean = []
    for it in items:
        if isinstance(it, dict) and it.get("headline") and it.get("body"):
            clean.append({
                "headline": str(it["headline"]).strip(),
                "body": str(it["body"]).strip(),
                "sources": [str(s).strip() for s in (it.get("sources") or []) if str(s).strip()],
            })
    return clean[:n]


# ─────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_bulletin_html(items: list, data: dict) -> str:
    today_str = data.get("trading_date", str(date.today()))
    gen_time  = data.get("generated_at", datetime.now().isoformat())
    try:
        date_label = datetime.fromisoformat(today_str).strftime("%A, %B %d, %Y")
    except ValueError:
        date_label = today_str
    try:
        gen_time_str = datetime.fromisoformat(gen_time).strftime("%I:%M %p IST")
    except ValueError:
        gen_time_str = ""

    all_sources = []
    for it in items:
        for s in it.get("sources", []):
            if s not in all_sources:
                all_sources.append(s)
    sources_line = " · ".join(all_sources) if all_sources else "Multi-source news pipeline"

    if items:
        cards = "\n".join(
            f"""        <article class="story">
            <div class="story-num">{NUM_EMOJI[idx] if idx < len(NUM_EMOJI) else f'#{idx+1}'}</div>
            <div class="story-body">
                <h2>{_esc(it['headline'])}</h2>
                <p>{_esc(it['body'])}</p>
                {f'<div class="story-src">{_esc(" · ".join(it["sources"]))}</div>' if it.get('sources') else ''}
            </div>
        </article>"""
            for idx, it in enumerate(items)
        )
    else:
        cards = ('<p class="empty"><em>Bulletin requires the Claude API (set ANTHROPIC_API_KEY) '
                 'and fresh news from data_fetcher.py. It auto-generates on every live run.</em></p>')

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Undeployed Capital · Morning Bulletin — {date_label}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg:{COLORS['bg']}; --card:{COLORS['card']}; --border:{COLORS['border']};
            --accent:{COLORS['accent']}; --gold:{COLORS['gold']}; --text:{COLORS['text']};
            --text-dim:{COLORS['text_dim']}; --neutral:{COLORS['neutral']}; --shadow:rgba(0,0,0,0.4);
        }}
        [data-theme="light"] {{
            --bg:#F7F9FC; --card:#FFFFFF; --border:#E2E8F0; --accent:#2563EB; --gold:#B45309;
            --text:#0F172A; --text-dim:#64748B; --neutral:#64748B; --shadow:rgba(15,23,42,0.08);
        }}
        *,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ background:var(--bg); color:var(--text);
            font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif; font-size:15px;
            line-height:1.65; max-width:720px; margin:0 auto; padding:24px 20px 70px;
            transition:background .25s,color .25s; }}
        .topbar {{ display:flex; justify-content:flex-end; gap:8px; margin-bottom:14px; }}
        .topbtn {{ background:var(--card); color:var(--text-dim); border:1px solid var(--border);
            border-radius:7px; padding:7px 12px; font-size:12px; font-weight:500; cursor:pointer;
            font-family:inherit; }}
        .topbtn:hover {{ color:var(--text); border-color:var(--accent); }}
        .wordmark {{ font-family:'Space Grotesk',sans-serif; font-size:22px; font-weight:700;
            letter-spacing:-0.5px; }}
        .wordmark .dot {{ color:var(--accent); }}
        .kicker {{ font-family:'Space Grotesk',sans-serif; font-size:34px; font-weight:700;
            letter-spacing:-1px; margin-top:10px; }}
        .kicker .am {{ color:var(--gold); }}
        .subtitle {{ font-size:12px; color:var(--text-dim); margin-top:6px; display:flex; gap:10px;
            flex-wrap:wrap; }}
        .divider {{ height:1px; background:var(--border); margin:22px 0 8px; }}
        .story {{ display:flex; gap:16px; padding:22px 0; border-bottom:1px solid var(--border); }}
        .story:last-of-type {{ border-bottom:none; }}
        .story-num {{ font-size:22px; line-height:1.2; flex-shrink:0; width:34px; text-align:center; }}
        .story-body {{ flex:1; min-width:0; }}
        .story-body h2 {{ font-family:'Space Grotesk',sans-serif; font-size:20px; font-weight:700;
            letter-spacing:-0.3px; margin-bottom:8px; line-height:1.25; }}
        .story-body p {{ color:var(--text); margin-bottom:8px; }}
        .story-src {{ font-size:11px; text-transform:uppercase; letter-spacing:0.5px;
            color:var(--text-dim); font-weight:600; }}
        .empty {{ color:var(--text-dim); padding:30px 0; }}
        .footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--border);
            font-size:12px; color:var(--text-dim); line-height:1.6; }}
        .footer a {{ color:var(--accent); text-decoration:none; }}
        @media (max-width:600px) {{
            .kicker {{ font-size:27px; }}
            .story {{ gap:12px; }}
            .story-num {{ width:26px; font-size:18px; }}
            .story-body h2 {{ font-size:18px; }}
        }}
        @media print {{
            body {{ background:#fff!important; color:#000!important; }}
            .topbar {{ display:none!important; }}
            .story {{ break-inside:avoid; }}
            a {{ color:#000!important; }}
        }}
    </style>
</head>
<body>
    <div class="topbar">
        <button class="topbtn" onclick="window.print()">⬇ PDF</button>
        <button class="topbtn" id="themeToggle" onclick="toggleTheme()">🌙 Theme</button>
        <a class="topbtn" href="../index.html" style="text-decoration:none">← All issues</a>
    </div>

    <div class="wordmark">Undeployed Capital<span class="dot">.</span></div>
    <div class="kicker"><span class="am">Morning</span> Bulletin</div>
    <div class="subtitle">
        <span>{date_label}</span><span>·</span>
        <span>Compiled {gen_time_str}</span><span>·</span>
        <span>{len(items)} stories</span>
    </div>
    <div class="divider"></div>

{cards}

    <footer class="footer">
        <p><strong>Sources:</strong> {_esc(sources_line)}</p>
        <p style="margin-top:8px">Disclaimer: This bulletin is for general information only and does
           not constitute investment, legal or tax advice.</p>
        <p style="margin-top:8px">Undeployed Capital · Published by Ishaan Sheth ·
           <a href="../index.html">All issues →</a></p>
    </footer>

<script>
(function(){{ var s=localStorage.getItem('uc-theme'); if(s) document.documentElement.setAttribute('data-theme',s); upd(); }})();
function toggleTheme(){{ var c=document.documentElement.getAttribute('data-theme')==='light'?'light':'dark';
    var n=c==='light'?'dark':'light'; document.documentElement.setAttribute('data-theme',n);
    localStorage.setItem('uc-theme',n); upd(); }}
function upd(){{ var b=document.getElementById('themeToggle'); if(!b) return;
    b.innerHTML=document.documentElement.getAttribute('data-theme')==='light'?'☀ Theme':'🌙 Theme'; }}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
# INDEX UPDATE (BULLETINS section)
# ─────────────────────────────────────────────

def update_index(items_today: int) -> None:
    """Refresh the BULLETINS_START/END block on docs/index.html."""
    if not os.path.exists(INDEX_FILE):
        return
    bdir = DOCS_DIR
    files = sorted(
        [f for f in os.listdir(bdir) if re.match(r"bulletin_\d{4}-\d{2}-\d{2}\.html", f)],
        reverse=True,
    ) if os.path.isdir(bdir) else []

    rows = []
    for fn in files:
        m = re.search(r"bulletin_(\d{4}-\d{2}-\d{2})\.html", fn)
        try:
            label = datetime.strptime(m.group(1), "%Y-%m-%d").strftime("%a, %b %d %Y")
        except Exception:
            label = m.group(1)
        rows.append(
            f'''    <a class="brief-item" href="briefs/{fn}">
      <span class="brief-date">{label}</span>
      <span class="brief-title">🗞 Morning Bulletin — top business stories of the day</span>
      <span class="brief-arrow">→</span>
    </a>'''
        )
    block = "\n".join(rows) if rows else '    <div class="empty">No bulletins yet.</div>'

    html = open(INDEX_FILE, encoding="utf-8").read()
    if "<!-- BULLETINS_START -->" in html:
        html = re.sub(
            r"<!-- BULLETINS_START -->.*?<!-- BULLETINS_END -->",
            f"<!-- BULLETINS_START -->\n{block}\n<!-- BULLETINS_END -->",
            html, flags=re.DOTALL,
        )
        open(INDEX_FILE, "w", encoding="utf-8").write(html)
        print(f"  ✓ index updated — {len(files)} bulletin(s) listed")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Undeployed Capital — Morning Bulletin")
    ap.add_argument("--data", default=DATA_FILE)
    ap.add_argument("--n", type=int, default=6, help="number of stories")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    print("=" * 56)
    print("  Undeployed Capital — Morning Bulletin")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p')}")
    print("=" * 56)

    try:
        with open(args.data) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.data} not found. Run data_fetcher.py first.")
        sys.exit(1)

    items = []
    if args.no_ai:
        print("[1/3] Skipping AI (--no-ai)")
    else:
        print("[1/3] Writing bulletin via Claude...")
        items = generate_bulletin_items(data, n=args.n)
        print(f"  ✓ {len(items)} stories")

    print("[2/3] Rendering HTML...")
    html = build_bulletin_html(items, data)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)
    trade_date = data.get("trading_date", str(date.today()))
    fname = f"bulletin_{trade_date}.html"
    src_path = os.path.join(OUTPUT_DIR, fname)
    open(src_path, "w", encoding="utf-8").write(html)
    open(os.path.join(DOCS_DIR, fname), "w", encoding="utf-8").write(html)
    print(f"  ✓ {src_path}  (+ mirrored to {DOCS_DIR}/)")

    print("[3/3] Updating home index...")
    update_index(len(items))

    print(f"\n✅ Bulletin complete: {src_path}")
    print(f"   Stories: {len(items)} | Size: {os.path.getsize(src_path)/1024:.1f} KB")


if __name__ == "__main__":
    main()
