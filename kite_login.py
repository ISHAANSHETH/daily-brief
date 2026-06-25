#!/usr/bin/env python3
"""
kite_login.py — Daily Zerodha Kite Connect token refresh

Run each morning before market open to refresh the access token.
Opens the Kite login page in browser, accepts the redirect URL,
exchanges the request_token for an access_token, saves to kite_config.json.

Usage:
    python3 kite_login.py

First run: prompts for API key and secret (one-time setup).
Subsequent runs: just opens browser and asks for redirect URL.
"""

import re
import sys
import webbrowser
from datetime import date

try:
    from kiteconnect import KiteConnect
except ImportError:
    print("ERROR: kiteconnect not installed.")
    print("  Run: pip install kiteconnect")
    sys.exit(1)

from kite_client import load_kite_config, save_kite_config, CONFIG_FILE, is_token_fresh


def main():
    cfg = load_kite_config()

    # First-time setup: collect API credentials
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        print("=" * 60)
        print("  Kite Connect — First-Time Setup")
        print("=" * 60)
        print("\nGet your API credentials from https://developers.kite.trade/apps")
        print("Create an app → set redirect URL to http://127.0.0.1\n")
        api_key = input("API Key: ").strip()
        api_secret = input("API Secret: ").strip()
        if not api_key or not api_secret:
            print("ERROR: Both API key and API secret required.")
            sys.exit(1)
        cfg["api_key"] = api_key
        cfg["api_secret"] = api_secret
        save_kite_config(cfg)
        print(f"\nSaved credentials to {CONFIG_FILE}")

    # Check if token is already fresh today
    if is_token_fresh(cfg):
        print(f"✅ Kite token already valid for today ({date.today()})")
        print("   Use --force to refresh anyway")
        if "--force" not in sys.argv:
            return

    kite = KiteConnect(api_key=cfg["api_key"])
    login_url = kite.login_url()

    print("=" * 60)
    print(f"  Kite Connect — Daily Login  ({date.today()})")
    print("=" * 60)
    print(f"\nOpening Kite login in browser...")
    webbrowser.open(login_url)
    print(f"\nURL: {login_url}")
    print(
        "\nAfter login, you'll be redirected to a URL like:\n"
        "  http://127.0.0.1?request_token=XXXXXXXXXXXX&action=login&status=success"
        "\n\nPaste the full redirect URL below (or just the request_token value):"
    )
    raw = input("> ").strip()

    # Extract request_token from full URL or bare value
    match = re.search(r"request_token=([A-Za-z0-9]+)", raw)
    if match:
        request_token = match.group(1)
    elif len(raw) > 10 and " " not in raw and "=" not in raw:
        request_token = raw
    else:
        print("ERROR: Could not parse request_token from input.")
        print("  Expected: http://127.0.0.1?request_token=XXXXX or just XXXXX")
        sys.exit(1)

    print(f"\nExchanging request_token for access_token...")
    try:
        session = kite.generate_session(request_token, api_secret=cfg["api_secret"])
        access_token = session["access_token"]
    except Exception as e:
        print(f"ERROR: Token exchange failed — {e}")
        sys.exit(1)

    cfg["access_token"]  = access_token
    cfg["request_token"] = request_token
    cfg["token_date"]    = str(date.today())
    save_kite_config(cfg)

    print(f"✅ Access token saved to {CONFIG_FILE}")
    print(f"   Valid for: {date.today()} (expires at midnight IST)")
    print(f"\n→ Run: python3 run_daily.py")


if __name__ == "__main__":
    main()
