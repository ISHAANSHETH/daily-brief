#!/bin/bash
# setup_macos.sh — Install Undeployed Capital as a macOS LaunchAgent
#
# Runs the FULL pipeline daily Mon–Fri:
#   data_fetcher → brief_generator → bulletin_generator → publish to GitHub Pages
# (this is exactly `publish.sh`).
#
# Schedule time is LOCAL (the Mac's timezone). Default 16:45 — ~75 min after the
# NSE close (15:30 IST) so the brief reflects the day's close. Edit RUN_HOUR /
# RUN_MIN below if your Mac isn't on IST.
#
# Secrets: the API key is read from .env at runtime (auto-loaded by the
# generators) — it is NOT stored in the plist. Make sure .env exists with
# ANTHROPIC_API_KEY=... before the job runs.
#
# Daily Kite step (manual, ~30s): run `python3 kite_login.py` each market
# morning so the scheduled run gets full option-chain / MCX / intraday data.
# Without it the run still publishes via yfinance fallback.

set -e

RUN_HOUR=16        # local hour (24h)
RUN_MIN=45

WORKING_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.undeployedcapital.brief.plist"
LOG_DIR="$WORKING_DIR/logs"
BASH_BIN="$(command -v bash)"

mkdir -p "$LOG_DIR"

if [ ! -f "$WORKING_DIR/.env" ]; then
    echo "WARNING: $WORKING_DIR/.env not found."
    echo "  The scheduled run needs ANTHROPIC_API_KEY in .env for the AI sections."
    echo "  Create it:  cp .env.example .env  then add your key."
fi

echo "Installing LaunchAgent → $PLIST_PATH"
echo "  Command:   bash publish.sh   (fetch → brief → bulletin → publish)"
echo "  Schedule:  Mon–Fri ${RUN_HOUR}:$(printf '%02d' $RUN_MIN) LOCAL time"
echo "  Dir:       $WORKING_DIR"

# Five StartCalendarInterval entries (one per weekday) — a single dict with a
# lone Weekday key would only fire on that one day.
intervals=""
for wd in 1 2 3 4 5; do
  intervals="${intervals}        <dict><key>Hour</key><integer>${RUN_HOUR}</integer><key>Minute</key><integer>${RUN_MIN}</integer><key>Weekday</key><integer>${wd}</integer></dict>
"
done

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.undeployedcapital.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>${BASH_BIN}</string>
        <string>${WORKING_DIR}/publish.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
${intervals}    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>${WORKING_DIR}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/launchd_err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "LaunchAgent installed and loaded."
launchctl list | grep undeployedcapital && echo "Status: LOADED ✓" || echo "(run 'launchctl list | grep undeployedcapital' to check)"
echo ""
echo "Daily workflow:"
echo "  1. Market morning:  python3 $WORKING_DIR/kite_login.py   (refresh Kite token, ~30s)"
echo "  2. ${RUN_HOUR}:$(printf '%02d' $RUN_MIN) local:      LaunchAgent auto-runs publish.sh"
echo ""
echo "Test the full chain now:  bash $WORKING_DIR/publish.sh"
echo "View logs:                tail -f $LOG_DIR/launchd.log"
echo "Uninstall:                launchctl unload $PLIST_PATH && rm $PLIST_PATH"
