#!/usr/bin/env python3
"""
run_daily.py — Undeployed Capital Daily Brief Runner

This is the single script you run (or schedule via cron/launchd).
It chains data_fetcher → brief_generator → optional email send.

Usage:
    python3 run_daily.py                    # full run
    python3 run_daily.py --no-ai            # skip Claude, layout only
    python3 run_daily.py --email you@x.com  # send to email after generation

Cron setup (runs Mon–Fri at 4:30 PM IST = 11:00 UTC):
    crontab -e
    0 11 * * 1-5 cd /path/to/undeployed_brief && python3 run_daily.py >> logs/$(date +%%Y-%%m-%%d).log 2>&1

macOS LaunchAgent alternative — see setup_macos.sh
"""

import subprocess
import sys
import os
import json
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG — set these once
# ─────────────────────────────────────────────

# Email settings (optional — only used with --email flag)
EMAIL_SENDER    = os.environ.get("BRIEF_EMAIL_FROM", "")
EMAIL_PASSWORD  = os.environ.get("BRIEF_EMAIL_PASS", "")  # Gmail app password
SMTP_HOST       = "smtp.gmail.com"
SMTP_PORT       = 465

# Substack publish settings (future Phase 3)
# SUBSTACK_TOKEN = os.environ.get("SUBSTACK_TOKEN", "")


def is_market_day() -> bool:
    """Skip weekends and known NSE holidays."""
    today = date.today()
    if today.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # NSE holidays 2026 — update annually
    # Source: https://www.nseindia.com/trade/exchange-traded-derivatives-market-holidays
    NSE_HOLIDAYS_2026 = {
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 2),    # Mahashivratri
        date(2026, 3, 25),   # Holi
        date(2026, 4, 2),    # Ram Navami
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 14),   # Dr. Ambedkar Jayanti
        date(2026, 5, 1),    # Maharashtra Day
        date(2026, 8, 15),   # Independence Day
        date(2026, 10, 2),   # Gandhi Jayanti
        date(2026, 11, 4),   # Diwali Laxmi Pujan (approx)
        date(2026, 12, 25),  # Christmas
    }
    return today not in NSE_HOLIDAYS_2026


def check_kite_token() -> None:
    """Warn (but don't crash) if Kite token is stale."""
    try:
        import kite_client as _kc
        cfg = _kc.load_kite_config()
        if not cfg.get("api_key"):
            print("  [Kite] Not configured — run python3 kite_login.py to set up Kite data")
            return
        if not _kc.is_token_fresh(cfg):
            print("  ⚠️  Kite access token is stale (last refreshed: "
                  f"{cfg.get('token_date', 'never')})")
            print("     Run python3 kite_login.py to get Kite data (option chain, MCX)")
            print("     Continuing with yfinance fallback...")
        else:
            print(f"  [Kite] ✓ Token valid for {cfg.get('token_date')}")
    except ImportError:
        pass  # kite_client not available — fine


def run_data_fetcher() -> bool:
    """Run data_fetcher.py and return True if successful."""
    print("\n" + "─" * 50)
    print("STEP 1: Data Pipeline")
    print("─" * 50)
    check_kite_token()
    result = subprocess.run(
        [sys.executable, "data_fetcher.py"],
        capture_output=False,
    )
    return result.returncode == 0


def run_brief_generator(no_ai: bool = False, substack: bool = False) -> Optional[str]:
    """Run brief_generator.py and return path to output HTML."""
    print("\n" + "─" * 50)
    print("STEP 2: Brief Generator")
    print("─" * 50)
    cmd = [sys.executable, "brief_generator.py"]
    if no_ai:
        cmd.append("--no-ai")
    if substack:
        cmd.append("--substack")

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        return None

    # Find the output file
    today = str(date.today())
    out_path = f"briefs/brief_{today}.html"
    if os.path.exists(out_path):
        return out_path
    return None


def send_email(html_path: str, recipients: list) -> bool:
    """
    Send the brief HTML as an email.
    Uses Gmail SMTP with app password.
    
    For larger audiences, swap this for SendGrid or AWS SES.
    """
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("\n⚠️  EMAIL_SENDER/EMAIL_PASSWORD not set. Skipping email.")
        return False

    today_str = datetime.now().strftime("%A, %B %d, %Y")

    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Undeployed Capital — {today_str}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        print(f"✅ Email sent to: {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"✗ Email failed: {e}")
        return False


def print_data_summary():
    """Print a quick summary of what was fetched."""
    try:
        with open("brief_data.json") as f:
            data = json.load(f)

        nifty = data.get("indices", {}).get("Nifty 50") or {}
        fii   = data.get("fii_dii", {})
        vix   = data.get("market_status", {}).get("india_vix") or {}

        print("\n  ┌─ Quick Market Check ─────────────────┐")
        if nifty:
            sign = "+" if nifty.get("change_pct", 0) >= 0 else ""
            print(f"  │  Nifty 50:   {nifty.get('last_price', '?'):>10,.2f}  ({sign}{nifty.get('change_pct', 0):.2f}%)")
        if vix:
            print(f"  │  India VIX:  {vix.get('last', '?'):>10.2f}  ({vix.get('change_pct', 0):+.2f}%)")
        if fii:
            print(f"  │  FII Net:    ₹{fii.get('fii_net_cr', 0):>+10,.0f} Cr")
            print(f"  │  DII Net:    ₹{fii.get('dii_net_cr', 0):>+10,.0f} Cr")
        print("  └──────────────────────────────────────┘")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Undeployed Capital Daily Brief Runner")
    parser.add_argument("--no-ai",      action="store_true", help="Skip Claude API prose generation")
    parser.add_argument("--email",      nargs="+",           help="Email recipient(s)")
    parser.add_argument("--force",      action="store_true", help="Run even on non-market days")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip data fetch (use existing brief_data.json)")
    parser.add_argument("--substack",   action="store_true", help="Also generate Substack-ready inner HTML")
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  UNDEPLOYED CAPITAL DAILY BRIEF")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p IST')}")
    print("=" * 50)

    # Market day check
    if not args.force and not is_market_day():
        print(f"\n⏸  Today ({date.today()}) is not a trading day. Skipping.")
        print("   Use --force to run anyway.")
        sys.exit(0)

    # Step 1: Fetch data
    if not args.skip_fetch:
        success = run_data_fetcher()
        if not success:
            print("\n✗ Data fetch failed. Check logs.")
            sys.exit(1)
        print_data_summary()
    else:
        print("\n[Skipping data fetch — using existing brief_data.json]")
        print_data_summary()

    # Step 2: Generate brief
    html_path = run_brief_generator(no_ai=args.no_ai, substack=args.substack)
    if not html_path:
        print("\n✗ Brief generation failed.")
        sys.exit(1)

    # Step 3: Email (optional)
    if args.email:
        print("\n" + "─" * 50)
        print("STEP 3: Email Delivery")
        print("─" * 50)
        send_email(html_path, args.email)

    print("\n" + "=" * 50)
    print(f"  ✅ DONE — {html_path}")
    print("=" * 50)
    print(f"\n  Open:          open {html_path}")
    print(f"  Send to self:  python3 run_daily.py --email you@example.com --skip-fetch")
    print(f"  Substack HTML: python3 run_daily.py --substack --skip-fetch")


if __name__ == "__main__":
    main()
