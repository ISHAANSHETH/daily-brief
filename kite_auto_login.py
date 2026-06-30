#!/usr/bin/env python3
"""
kite_auto_login.py — Headless Zerodha Kite token refresh via TOTP (macOS Keychain)

Refreshes the daily Kite access_token with NO browser and NO manual step, by
performing Zerodha's TOTP login flow programmatically. Lets the scheduled
publish run get full option-chain / MCX / intraday data hands-off.

────────────────────────────────────────────────────────────────────────────
SECURITY — READ THIS
────────────────────────────────────────────────────────────────────────────
This logs into a BROKERAGE account. The three secrets it needs (Zerodha user
id, password, TOTP seed) are read from the macOS **Keychain** at runtime — they
are NEVER stored in this repo, in .env, in code, or printed.

Before relying on this, in the Kite developer console:
  • Keep the app API-only and DO NOT enable any fund-transfer/withdrawal scope.
  • Treat the Mac as a trusted device; anyone with it + your login keychain can
    obtain a trading session. If that's not acceptable, use manual kite_login.py.

One-time setup — YOU run these (the values are typed into a hidden prompt, so
they never appear in shell history or anywhere I can see):

    security add-generic-password -a user_id     -s UndeployedKite -w
    security add-generic-password -a password    -s UndeployedKite -w
    security add-generic-password -a totp_secret -s UndeployedKite -w

  (each prompts for the value; for totp_secret paste the Base32 string Zerodha
   shows when you set up the external TOTP authenticator — NOT a 6-digit code.)

Then test:   python3 kite_auto_login.py
The agent/publish.sh will call it automatically each run.

Usage:
    python3 kite_auto_login.py            # refresh token if stale (default)
    python3 kite_auto_login.py --force    # refresh even if today's token exists
    python3 kite_auto_login.py --setup    # print the Keychain setup commands
"""

import sys
import subprocess
import urllib.parse
from datetime import date

KEYCHAIN_SERVICE = "UndeployedKite"
KEYCHAIN_ACCOUNTS = ("user_id", "password", "totp_secret")


# ─────────────────────────────────────────────
# KEYCHAIN
# ─────────────────────────────────────────────

def _keychain_get(account: str) -> str:
    """Read a secret from the macOS login Keychain. Returns '' if missing.
    Never logs the value."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except Exception:
        return ""


def _print_setup():
    print("One-time Keychain setup — run these yourself (hidden prompts):\n")
    for acc in KEYCHAIN_ACCOUNTS:
        print(f"  security add-generic-password -a {acc} -s {KEYCHAIN_SERVICE} -w")
    print("\n  • user_id     → your Zerodha login ID")
    print("  • password    → your Zerodha login password")
    print("  • totp_secret → the Base32 TOTP seed (set up an external authenticator")
    print("                  in Zerodha → My Profile → Password & Security), NOT a 6-digit code.")
    print("\nUpdate a value later: add `security delete-generic-password -a <acc> "
          f"-s {KEYCHAIN_SERVICE}` first, then re-add.")


# ─────────────────────────────────────────────
# ZERODHA TOTP LOGIN
# ─────────────────────────────────────────────

def _resolve_request_token(session, login_url: str) -> str:
    """
    Follow the /connect/login redirect chain manually until we see
    `request_token=...` in a Location header. We never actually fetch the final
    http://127.0.0.1 redirect (nothing listens there) — we just read the token
    out of the redirect.
    """
    url = login_url
    for _ in range(10):
        r = session.get(url, allow_redirects=False, timeout=20)
        loc = r.headers.get("Location", "")
        if not loc:
            # No redirect — token may be in the resolved URL
            if "request_token=" in r.url:
                loc = r.url
            else:
                return ""
        if "request_token=" in loc:
            q = urllib.parse.urlparse(loc).query
            tok = urllib.parse.parse_qs(q).get("request_token", [""])[0]
            return tok
        url = loc if loc.startswith("http") else "https://kite.zerodha.com" + loc
    return ""


def refresh_token(force: bool = False) -> bool:
    import requests
    import pyotp
    from kiteconnect import KiteConnect
    from kite_client import load_kite_config, save_kite_config, is_token_fresh

    cfg = load_kite_config()
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        print("✗ api_key / api_secret missing in kite_config.json. Run kite_login.py once to set them.")
        return False

    if not force and is_token_fresh(cfg):
        print(f"✅ Kite token already valid for today ({date.today()}).")
        return True

    user_id  = _keychain_get("user_id")
    password = _keychain_get("password")
    totp_sec = _keychain_get("totp_secret")
    missing = [a for a, v in (("user_id", user_id), ("password", password), ("totp_secret", totp_sec)) if not v]
    if missing:
        print(f"✗ Keychain secrets missing: {', '.join(missing)}")
        print("  Run:  python3 kite_auto_login.py --setup")
        return False

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                            "X-Kite-Version": "3"})
    try:
        # Step 1 — password login → request_id
        r1 = session.post("https://kite.zerodha.com/api/login",
                          data={"user_id": user_id, "password": password}, timeout=20)
        j1 = r1.json()
        if j1.get("status") != "success":
            print(f"✗ Login step failed: {j1.get('message', 'unknown error')}")
            return False
        request_id = j1["data"]["request_id"]

        # Step 2 — TOTP 2FA
        otp = pyotp.TOTP(totp_sec).now()
        r2 = session.post("https://kite.zerodha.com/api/twofa",
                          data={"user_id": user_id, "request_id": request_id,
                                "twofa_value": otp, "twofa_type": "totp", "skip_session": ""},
                          timeout=20)
        j2 = r2.json()
        if j2.get("status") != "success":
            print(f"✗ TOTP step failed: {j2.get('message', 'check the TOTP seed / clock skew')}")
            return False

        # Step 3 — request_token from the connect-login redirect
        kite = KiteConnect(api_key=cfg["api_key"])
        request_token = _resolve_request_token(session, kite.login_url())
        if not request_token:
            print("✗ Could not obtain request_token from redirect.")
            return False

        # Step 4 — exchange for access_token
        sess = kite.generate_session(request_token, api_secret=cfg["api_secret"])
        cfg["access_token"] = sess["access_token"]
        cfg["token_date"]   = str(date.today())
        cfg["request_token"] = request_token
        save_kite_config(cfg)

        # Verify
        kite.set_access_token(sess["access_token"])
        prof = kite.profile()
        print(f"✅ Kite token refreshed for {date.today()} — user: {prof.get('user_name')}")
        return True

    except Exception as e:
        print(f"✗ Auto-login error: {e}")
        return False


def main():
    if "--setup" in sys.argv:
        _print_setup()
        return
    ok = refresh_token(force=("--force" in sys.argv))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
