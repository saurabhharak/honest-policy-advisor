#!/bin/bash
# Pre-demo verification: env vars, API connectivity, tests

set -e

echo "=== Policy Decoder Pre-Demo Check ==="
echo ""

# Check env vars
echo "Checking environment variables..."
source .env 2>/dev/null || { echo "FAIL: .env file not found"; exit 1; }

for var in CASPIAN_API_KEY TELEGRAM_BOT_TOKEN OPENAI_API_KEY; do
    if [ -z "${!var}" ]; then
        echo "FAIL: $var is not set"
        exit 1
    fi
    echo "  OK: $var"
done
echo ""

# Check Caspian API
echo "Checking Caspian API..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    https://api.trycaspianai.com/v1/channels \
    -H "Authorization: Bearer $CASPIAN_API_KEY")
if [ "$STATUS" = "200" ]; then
    echo "  OK: Caspian API reachable"
else
    echo "FAIL: Caspian API returned $STATUS"
    exit 1
fi
echo ""

# Check channels
echo "Checking connected channels..."
curl -s https://api.trycaspianai.com/v1/channels \
    -H "Authorization: Bearer $CASPIAN_API_KEY" | python -m json.tool 2>/dev/null || true
echo ""

# Run tests
echo "Running tests..."
uv run pytest --tb=short -q
echo ""

echo "=== All checks passed ==="
