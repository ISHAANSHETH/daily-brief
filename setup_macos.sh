#!/bin/bash
# setup_macos.sh — Install Undeployed Capital Daily Brief as a macOS LaunchAgent
# Runs Mon-Fri at 4:30 PM IST (11:00 UTC)

set -e

WORKING_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.undeployedcapital.brief.plist"
PYTHON="$(which python3)"
LOG_DIR="$WORKING_DIR/logs"

mkdir -p "$LOG_DIR"

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set in the current environment."
    echo "  Run: export ANTHROPIC_API_KEY=sk-ant-..."
    echo "  Then re-run this script."
    exit 1
fi

echo "Installing LaunchAgent to $PLIST_PATH"
echo "  Working directory: $WORKING_DIR"
echo "  Python:            $PYTHON"
echo "  Schedule:          Mon-Fri 11:00 UTC (4:30 PM IST)"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.undeployedcapital.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$WORKING_DIR/run_daily.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>11</integer>
        <key>Minute</key>
        <integer>0</integer>
        <key>Weekday</key>
        <integer>1</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>$ANTHROPIC_API_KEY</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$WORKING_DIR</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

# StartCalendarInterval with a single Weekday key only fires on that day.
# To run Mon-Fri we need 5 separate interval dicts. Rewrite:
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.undeployedcapital.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$WORKING_DIR/run_daily.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>1</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>2</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>3</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>4</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>5</integer></dict>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>$ANTHROPIC_API_KEY</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$WORKING_DIR</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

# Unload existing job if present (ignore errors)
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Load the new job
launchctl load "$PLIST_PATH"

echo ""
echo "LaunchAgent installed and loaded."
echo ""
launchctl list | grep undeployedcapital && echo "Status: LOADED ✓" || echo "Status check: run 'launchctl list | grep undeployedcapital'"
echo ""
echo "Daily workflow:"
echo "  1. Morning: python3 $WORKING_DIR/kite_login.py  (refresh Kite token)"
echo "  2. 4:30 PM IST: LaunchAgent auto-runs run_daily.py"
echo ""
echo "Test run now:  python3 $WORKING_DIR/run_daily.py --no-ai --force"
echo "View logs:     tail -f $LOG_DIR/launchd.log"
echo "Uninstall:     launchctl unload $PLIST_PATH && rm $PLIST_PATH"
