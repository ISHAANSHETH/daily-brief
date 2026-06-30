#!/bin/bash
# publish.sh — Run daily brief and push to GitHub Pages
#
# Usage:
#   bash publish.sh              # fetch fresh data + generate + publish
#   bash publish.sh --skip-fetch # use existing brief_data.json, skip API calls
#   bash publish.sh --no-ai      # skip Claude prose (fast layout-only brief)
#
# One-time setup:
#   1. Create GitHub repo (e.g. github.com/you/daily-brief)
#   2. git remote add origin git@github.com:you/daily-brief.git
#   3. git push -u origin main
#   4. GitHub repo → Settings → Pages → Source: Deploy from branch → main → /docs
#   5. Done. Your site: https://you.github.io/daily-brief/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SKIP_FETCH=""
NO_AI=""
for arg in "$@"; do
  case $arg in
    --skip-fetch) SKIP_FETCH="--skip-fetch" ;;
    --no-ai)      NO_AI="--no-ai" ;;
  esac
done

TODAY=$(date +%Y-%m-%d)
BRIEF_SRC="briefs/brief_${TODAY}.html"
BRIEF_DEST="docs/briefs/brief_${TODAY}.html"

# ── Step 1: Generate brief ──────────────────────────────────────────────────
echo ""
echo "=== Undeployed Capital — Publish ==="
echo "Date: $TODAY"
echo ""

if [ -z "$SKIP_FETCH" ] && [ -z "$NO_AI" ]; then
  python3 run_daily.py
elif [ -n "$SKIP_FETCH" ] && [ -n "$NO_AI" ]; then
  python3 run_daily.py --skip-fetch --no-ai
elif [ -n "$SKIP_FETCH" ]; then
  python3 run_daily.py --skip-fetch
elif [ -n "$NO_AI" ]; then
  python3 run_daily.py --no-ai
fi

# ── Step 1b: Morning Bulletin (separate add-on product) ─────────────────────
# Reads the same brief_data.json; mirrors itself to docs/briefs and refreshes
# the BULLETINS list on docs/index.html.
echo ""
echo "--- Morning Bulletin ---"
python3 bulletin_generator.py $NO_AI || echo "(bulletin step skipped/failed — continuing)"

# ── Step 2: Copy to docs/ ───────────────────────────────────────────────────
if [ ! -f "$BRIEF_SRC" ]; then
  echo "✗ Brief not found at $BRIEF_SRC"
  exit 1
fi

mkdir -p docs/briefs
cp "$BRIEF_SRC" "$BRIEF_DEST"
echo "✓ Copied to $BRIEF_DEST"

# ── Step 3: Rebuild docs/index.html ────────────────────────────────────────
python3 - <<'PYEOF'
import os, re
from pathlib import Path
from datetime import datetime

briefs_dir = Path("docs/briefs")
brief_files = sorted(briefs_dir.glob("brief_*.html"), reverse=True)

def parse_date(filename):
    m = re.search(r"brief_(\d{4}-\d{2}-\d{2})\.html", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except Exception:
            pass
    return None

def extract_headline(filepath):
    try:
        content = filepath.read_text(encoding="utf-8")
        # Try to grab the auto-generated h1 headline
        m = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.DOTALL)
        if m:
            headline = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if headline and headline != "Daily Market Brief":
                return headline
    except Exception:
        pass
    return None

rows = []
for bf in brief_files:
    dt = parse_date(bf.name)
    if not dt:
        continue
    date_label = dt.strftime("%a, %b %d %Y")
    headline = extract_headline(bf) or "Daily Market Brief"
    href = f"briefs/{bf.name}"
    rows.append(f'''    <a class="brief-item" href="{href}">
      <span class="brief-date">{date_label}</span>
      <span class="brief-title">{headline}</span>
      <span class="brief-arrow">→</span>
    </a>''')

list_html = "\n".join(rows) if rows else '    <div class="empty">No briefs yet.</div>'

template = Path("docs/index.html").read_text(encoding="utf-8")
new_template = re.sub(
    r'<!-- BRIEFS_START -->.*?<!-- BRIEFS_END -->',
    f'<!-- BRIEFS_START -->\n{list_html}\n<!-- BRIEFS_END -->',
    template,
    flags=re.DOTALL
)
Path("docs/index.html").write_text(new_template, encoding="utf-8")
print(f"✓ Index rebuilt — {len(rows)} brief(s) listed")
PYEOF

# ── Step 4: Commit and push ─────────────────────────────────────────────────
git add docs/
git commit -m "Brief: $TODAY" || echo "(nothing new to commit)"
git push origin main

echo ""
echo "✅ Published!"
# Derive owner/repo from the remote → owner.github.io/repo (lowercased; Pages is case-insensitive).
REPO_PATH="$(git remote get-url origin 2>/dev/null | sed -E 's#.*github.com[:/]([^/]+)/([^/.]+)(\.git)?#\1 \2#')"
OWNER="$(echo "$REPO_PATH" | awk '{print tolower($1)}')"
REPO="$(echo "$REPO_PATH" | awk '{print $2}')"
echo "   Brief:    https://${OWNER}.github.io/${REPO}/briefs/brief_${TODAY}.html"
echo "   Bulletin: https://${OWNER}.github.io/${REPO}/briefs/bulletin_${TODAY}.html"
echo "   Home:     https://${OWNER}.github.io/${REPO}/"
