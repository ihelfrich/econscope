#!/bin/bash
# ============================================================================
# Open registration pages for all ECONSCOPE API keys
# Usage: ./scripts/register_apis.sh [tier]
#   ./scripts/register_apis.sh       # opens all
#   ./scripts/register_apis.sh p0    # opens P0 only
#   ./scripts/register_apis.sh p1    # opens P0 + P1
#   ./scripts/register_apis.sh p2    # opens P0 + P1 + P2
# ============================================================================

TIER="${1:-all}"

# P0: Core macro
p0_urls=(
  "https://research.stlouisfed.org/useraccount/apikeys"          # FRED
  "https://data.bls.gov/registrationEngine/"                      # BLS
  "https://apps.bea.gov/API/signup/"                              # BEA
)

# P1: Important extensions
p1_urls=(
  "https://api.census.gov/data/key_signup.html"                   # Census
  "https://www.eia.gov/opendata/register.php"                     # EIA
  "https://developer.company-information.service.gov.uk/"         # UK Companies House
  "https://quickstats.nass.usda.gov/api/"                         # USDA NASS
)

# P2: Financial + OSINT
p2_urls=(
  "https://finnhub.io/register"                                   # Finnhub
  "https://site.financialmodelingprep.com/developer/docs"         # FMP
  "https://www.alphavantage.co/support/#api-key"                  # Alpha Vantage
  "https://polygon.io/dashboard/signup"                           # Polygon
  "https://www.tiingo.com/account/api/token"                      # Tiingo
  "https://iexcloud.io/cloud-login#/register"                    # IEX Cloud
  "https://opencorporates.com/api_accounts/new"                   # OpenCorporates
  "https://www.opensanctions.org/api/"                            # OpenSanctions
  "https://www.courtlistener.com/api/rest-info/"                  # CourtListener
  "https://comtradeplus.un.org/"                                  # UN Comtrade
)

# P3: Notifications
p3_urls=(
  "https://pushover.net/"                                         # Pushover
)

open_urls() {
  for url in "$@"; do
    echo "  Opening: $url"
    open "$url"
    sleep 0.5
  done
}

echo "ECONSCOPE — API Registration Helper"
echo "===================================="

case "$TIER" in
  p0)
    echo "Opening P0 (core) registration pages..."
    open_urls "${p0_urls[@]}"
    ;;
  p1)
    echo "Opening P0 + P1 registration pages..."
    open_urls "${p0_urls[@]}"
    open_urls "${p1_urls[@]}"
    ;;
  p2)
    echo "Opening P0 + P1 + P2 registration pages..."
    open_urls "${p0_urls[@]}"
    open_urls "${p1_urls[@]}"
    open_urls "${p2_urls[@]}"
    ;;
  all)
    echo "Opening ALL registration pages..."
    open_urls "${p0_urls[@]}"
    open_urls "${p1_urls[@]}"
    open_urls "${p2_urls[@]}"
    open_urls "${p3_urls[@]}"
    ;;
  *)
    echo "Usage: $0 [p0|p1|p2|all]"
    exit 1
    ;;
esac

echo ""
echo "After registering, paste keys into: ~/Projects/econscope/.env"
echo "Then verify with: python3 scripts/verify_keys.py"
