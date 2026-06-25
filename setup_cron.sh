#!/bin/bash
# setup_cron.sh — Install Undeployed Capital Daily Brief as a cron job (Linux / non-macOS)
# Runs Mon-Fri at 11:00 UTC (4:30 PM IST)

set -e

WORKING_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
LOG_DIR="$WORKING_DIR/logs"

mkdir -p "$LOG_DIR"

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "  Add to ~/.bashrc: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

CRON_LINE="0 11 * * 1-5 ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY cd $WORKING_DIR && $PYTHON $WORKING_DIR/run_daily.py >> $LOG_DIR/\$(date +\%Y-\%m-\%d).log 2>&1"

echo "Adding cron job:"
echo "  $CRON_LINE"
echo ""

# Append without duplicating
(crontab -l 2>/dev/null | grep -v "run_daily.py"; echo "$CRON_LINE") | crontab -

echo "Cron job installed. Verify:"
crontab -l | grep "run_daily.py"
echo ""
echo "Test:   python3 $WORKING_DIR/run_daily.py --no-ai --force"
echo "Logs:   $LOG_DIR/"
echo "Remove: crontab -l | grep -v run_daily.py | crontab -"
