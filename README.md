# Undeployed Capital — Daily Brief System
## Phase 1 + Phase 2 Build

---

## Quick Start (5 minutes)

```bash
# 1. Install dependencies
pip install yfinance requests beautifulsoup4 plotly anthropic pandas jinja2

# 2. Set your Claude API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run the full pipeline
cd undeployed_brief
python3 run_daily.py

# 4. Open your brief
open briefs/brief_YYYY-MM-DD.html
```

---

## Architecture Overview

```
run_daily.py          ← single entry point, chains everything
    │
    ├── data_fetcher.py   ← pulls all raw data → brief_data.json
    │       │
    │       ├── yfinance          [indices, sectors, commodities, FX, bonds, global, thematic]
    │       ├── NSE India API     [FII/DII flows, gainers/losers, VIX, corp actions, earnings]
    │       └── Zerodha AMR       [management quotes, top headlines — scraped + attributed]
    │
    └── brief_generator.py  ← reads brief_data.json → brief_YYYY-MM-DD.html
            │
            ├── Plotly charts    [sector bars, thematic, global, FII/DII]
            ├── HTML tables      [commodities, FX, gainers/losers, corp actions, earnings]
            └── Claude API       [intraday narrative, macro, corporate, thematic, global prose]
```

---

## Data Sources & What They Power

| Source | Data | Cost | How |
|--------|------|------|-----|
| **yfinance** | Nifty 50, Sensex, all sector indices, commodities, FX, global markets, thematic stocks | Free | Python library |
| **NSE India** | FII/DII flows, gainers/losers, India VIX, breadth, corporate actions, earnings calendar | Free | Session-based JSON endpoints |
| **Zerodha AMR** | Management quotes, top headlines, global stories | Free | HTML scrape + attribution |
| **Zerodha Pulse** | Intraday news headlines | Free | HTML scrape |
| **Claude API** | All prose sections (intraday narrative, macro, corporate, thematic, global) | ~₹2–5/day | Anthropic API |

**Total cost per issue: ~₹2–5 (Claude API only). Everything else is free.**

---

## The Zerodha AMR Scraping — How & Why

DayStarter (the briefing you studied) explicitly sources everything from:
- Zerodha AfterMarket Report
- Mint
- Upstox Learning

We do the same thing, just programmatically. The `fetch_zerodha_amr()` function:

1. Reads the Zerodha AMR RSS feed to find the latest post URL
2. Fetches the public HTML of that post (same as opening in a browser)
3. Extracts:
   - Management quotes (`<blockquote>` tags — verbatim with attribution)
   - Top India stories (bullet points from the corporate/macro sections)
   - Global stories (filtered by keyword: Fed, S&P, Nasdaq, etc.)
4. **Always attributes**: every extracted item gets `Source: Zerodha AfterMarket Report`

**Is this legal?** Yes — reading a public web page and attributing it is journalism, 
not redistribution. DayStarter itself does exactly this: reads the AMR and Mint, 
then synthesises + attributes. We automate the reading step.

**Why not just read the AMR manually?** We use the extracted text as *context* for 
Claude's prose generation. Claude writes the synthesis — it doesn't copy AMR text.
The same way DayStarter's human writer reads the AMR and then writes their own 
sentences. We're just doing it with AI.

---

## The 4 Charts & What They Show

### Chart 1: Sector Performance (horizontal bars)
- **What**: All major Nifty sector indices, sorted worst → best
- **Why**: Replaces DayStarter's static "Exhibit 2" SVG with an interactive version
- **Data**: yfinance (sector ETF tickers)
- **Differentiator**: Hover shows exact prices and absolute change

### Chart 2: Thematic Tracker (vertical bars + hover detail)
- **What**: 5 custom baskets — VC/Startup, Defense, Diagnostics, AI/Tech, PLI/Manufacturing
- **Why**: DayStarter has nothing like this. Your readers think in themes, not indices.
- **Data**: yfinance (individual stock tickers per basket)
- **Differentiator**: Hover shows all constituents with individual returns

### Chart 3: Global Markets (horizontal bars)
- **What**: S&P 500, Nasdaq, Dow, Nikkei, FTSE, Shanghai, Hang Seng
- **Why**: Context for Indian market sentiment the next morning
- **Data**: yfinance (global index tickers)
- **Differentiator**: Sorted, colored, interactive

### Chart 4: FII/DII Institutional Flows (vertical bars)
- **What**: Today's net FII and DII figures in ₹ crore
- **Why**: The single most watched institutional signal in Indian markets
- **Data**: NSE India official endpoint (same data DayStarter uses)
- **Differentiator**: Shows both today and 5-day rolling context

---

## Phase 2 Additions (vs Phase 1)

Phase 1 adds:
- ✅ All 4 charts (sectors, FII/DII, global, AMR scrape)
- ✅ Correct Change% calculation (vs prev_close, not vs open)
- ✅ Pivot points (R1/R2/R3, S1/S2/S3)
- ✅ India VIX as sentiment gauge (free, no sentiment API needed)
- ✅ Corporate actions calendar from NSE
- ✅ Gainers/Losers from NSE

Phase 2 adds:
- ✅ **Thematic Tracker** (5 custom baskets — the main differentiator)
- ✅ **Earnings Calendar** (14-day look-ahead from NSE board meetings)
- ✅ **Claude prose for all sections** (intraday, macro, corporate, thematic, global)
- ✅ **Zerodha AMR news layer** (management quotes, top headlines)

---

## Scheduled Automation (macOS)

### Option A: cron (simplest)
```bash
crontab -e
# Add this line (runs Mon-Fri at 4:30 PM IST = 11:00 UTC):
0 11 * * 1-5 cd /Users/ishaansheth/undeployed_brief && python3 run_daily.py >> logs/$(date +\%Y-\%m-\%d).log 2>&1
```

### Option B: macOS LaunchAgent (runs even if Terminal is closed)
Create `~/Library/LaunchAgents/com.undeployedcapital.brief.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.undeployedcapital.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/ishaansheth/undeployed_brief/run_daily.py</string>
        <string>--email</string>
        <string>ishaan@example.com</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>16</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-YOUR_KEY_HERE</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/ishaansheth/undeployed_brief</string>
    <key>StandardOutPath</key>
    <string>/Users/ishaansheth/undeployed_brief/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ishaansheth/undeployed_brief/logs/launchd_err.log</string>
</dict>
</plist>
```
Then: `launchctl load ~/Library/LaunchAgents/com.undeployedcapital.brief.plist`

---

## Customising the Thematic Baskets

Edit `THEMATIC_BASKETS` in `data_fetcher.py`:

```python
THEMATIC_BASKETS = {
    "VC/Startup Ecosystem": [
        "ZOMATO.NS", "NYKAA.NS", "PAYTM.NS", ...
    ],
    "Defense": [...],
    # Add your own:
    "Fintech": ["POLICYBZR.NS", "PAYTM.NS", "CREDITACC.NS"],
    "EV Plays": ["TATAPOWER.NS", "MAHINDRA.NS", "OLECTRA.NS"],
}
```

---

## Substack Publishing

Currently: copy the `<body>` of the HTML into Substack's HTML embed block.

Future (Phase 3): Substack has an undocumented API used by their mobile app.
Several open-source projects have reverse-engineered it. We'll add auto-publishing
in Phase 3 — `POST /api/v1/posts` with your Substack session cookie.

---

## File Structure
```
undeployed_brief/
├── data_fetcher.py      # data pipeline
├── brief_generator.py   # HTML + chart + AI prose generator  
├── run_daily.py         # orchestrator + scheduler
├── README.md            # this file
├── brief_data.json      # latest data snapshot (auto-generated)
├── briefs/              # output HTML files
│   └── brief_2026-06-25.html
└── logs/                # cron/launchd logs
```
