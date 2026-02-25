#!/bin/bash
# Deploy Strategy Pipeline
# Usage: ./scripts/deploy_strategy.sh [--skip-test] [--skip-backtest] [--skip-diagrams]
#
# Runs: tests → backtest → commit → push → deploy → health check → diagrams

set -e

DROPLET_IP="107.170.74.154"
DROPLET_USER="root"
APP_DIR="/opt/tradovate-bot"

SKIP_TEST=false
SKIP_BACKTEST=false
SKIP_DIAGRAMS=false

for arg in "$@"; do
    case $arg in
        --skip-test) SKIP_TEST=true ;;
        --skip-backtest) SKIP_BACKTEST=true ;;
        --skip-diagrams) SKIP_DIAGRAMS=true ;;
    esac
done

echo "========================================"
echo "  V10.13 Strategy Deploy Pipeline"
echo "========================================"
echo ""

# Step 1: Run tests
if [ "$SKIP_TEST" = false ]; then
    echo "[1/7] Running tests..."
    python -m pytest tests/ -q
    echo ""
else
    echo "[1/7] Tests skipped (--skip-test)"
fi

# Step 2: Run backtest (ES + NQ 15-day)
if [ "$SKIP_BACKTEST" = false ]; then
    echo "[2/7] Running 15-day backtests..."
    echo "--- ES ---"
    python -m runners.backtest_v10_multiday ES 15 2>&1 | tail -20
    echo ""
    echo "--- NQ ---"
    python -m runners.backtest_v10_multiday NQ 15 2>&1 | tail -20
    echo ""
else
    echo "[2/7] Backtests skipped (--skip-backtest)"
fi

# Step 3: Show changes and confirm
echo "[3/7] Changes to deploy:"
git status --short
echo ""
git diff --stat
echo ""
read -p "Proceed with commit and deploy? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Step 4: Commit
echo "[4/7] Committing..."
read -p "Commit message: " COMMIT_MSG
git add -A
git commit -m "$COMMIT_MSG

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
echo ""

# Step 5: Push
echo "[5/7] Pushing to remote..."
git push
echo ""

# Step 6: Deploy to droplet
echo "[6/7] Deploying to droplet ($DROPLET_IP)..."
ssh ${DROPLET_USER}@${DROPLET_IP} "cd ${APP_DIR} && git pull"
echo ""

# Step 7: Health check on droplet
echo "[7/7] Running health check on droplet..."
ssh ${DROPLET_USER}@${DROPLET_IP} "cd ${APP_DIR} && source venv/bin/activate && python health_check.py"
echo ""

# Optional: Re-render diagrams
if [ "$SKIP_DIAGRAMS" = false ]; then
    echo "[Bonus] Re-rendering flow diagrams..."
    DIAGRAM_DIR="notes/diagrams"
    if [ -d "$DIAGRAM_DIR" ] && ls "$DIAGRAM_DIR"/*.mmd 1>/dev/null 2>&1; then
        for f in "$DIAGRAM_DIR"/*.mmd; do
            echo "  Rendering $(basename $f)..."
            npx --yes @mermaid-js/mermaid-cli -i "$f" -o "${f%.mmd}.png" -b white -w 1600 2>/dev/null
        done
        python -c "
from PIL import Image; import os
d='$DIAGRAM_DIR'
imgs=[Image.open(os.path.join(d,f)).convert('RGB') for f in sorted(os.listdir(d)) if f.endswith('.png')]
imgs[0].save('notes/V10.13_Strategy_Flow_Diagrams.pdf',save_all=True,append_images=imgs[1:],resolution=150)
print('  PDF updated: notes/V10.13_Strategy_Flow_Diagrams.pdf')
"
    else
        echo "  No .mmd files found, skipping"
    fi
fi

echo ""
echo "========================================"
echo "  Deploy complete!"
echo "========================================"
echo ""
echo "Monitor logs:"
echo "  ssh ${DROPLET_USER}@${DROPLET_IP} \"tail -f ${APP_DIR}/logs/paper_trading/service.log\""
