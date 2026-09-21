#!/usr/bin/env bash
# Experiment: does a non-Dutch exit point get the SOFT Cloudflare check instead of
# the HARD block? This decides whether renting a host outside the Netherlands is
# worth it, or whether the site only serves Iranian addresses.
#
# Usage on the server:  bash deploy/probe_egress.sh

set -u
TARGET='https://www.vfsvisaonline.com/'
MARKERS='sorry, you have been blocked|just a moment|performing security verification|attention required|verifies you are not a bot'

echo '== 1. direct from this server =='
direct_code=$(curl -s -m 20 -o /tmp/v_direct.html -w '%{http_code}' "$TARGET")
echo "   status=$direct_code"
grep -o -i -E "$MARKERS" /tmp/v_direct.html | sort -u | sed 's/^/   marker: /'

echo
echo '== 2. hunting a few non-Dutch exit points =='
LIST=$(curl -s -m 25 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&country=DE&timeout=5000&anonymity=all&ssl=all' | tr -d '\r' | grep -E '^[0-9]+\.[0-9.]+:[0-9]+$' | head -8)
if [ -z "$LIST" ]; then
    echo '   (first list empty, trying the alternate one)'
    LIST=$(curl -s -m 25 'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt' | tr -d '\r' | grep -E '^[0-9]+\.[0-9.]+:[0-9]+$' | head -10)
fi
echo "   candidates: $(echo "$LIST" | wc -l)"

tested=0
for proxy in $LIST; do
    country=$(curl -s -m 8 -x "http://$proxy" https://ipinfo.io/country 2>/dev/null | tr -d '\r\n ')
    printf '   %-22s country=%s\n' "$proxy" "${country:-none}"
    case "$country" in
        DE|FR|GB|NL|US|AE|TR) ;;
        *) continue ;;
    esac
    code=$(curl -s -m 25 -x "http://$proxy" -o /tmp/v_proxy.html -w '%{http_code}' "$TARGET" 2>/dev/null)
    printf '      country %s -> vfsvisaonline status=%s\n' "$country" "${code:-failed}"
    grep -o -i -E "$MARKERS" /tmp/v_proxy.html 2>/dev/null | sort -u | sed 's/^/      marker: /'
    tested=$((tested + 1))
done

echo
echo "== done ($tested exit points tested) =="
cat <<'EOF'
How to read this:
  "just a moment" or "performing security verification" -> SOFT check: a real
      browser (what this monitor uses) can usually pass it, so a non-Dutch host
      is worth using.
  "sorry, you have been blocked"                       -> HARD block for that
      country/network as well: then only an address inside Iran will work.
  nothing / different markers                          -> page loaded: even better.
EOF
