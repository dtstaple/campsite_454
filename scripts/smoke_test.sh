#!/usr/bin/env bash
# Smoke test a CampSite deployment (TM05-113).
#   scripts/smoke_test.sh <backend-url> <frontend-url>
#   scripts/smoke_test.sh https://campsite-api.onrender.com https://campsite-web.onrender.com
# Registers a throwaway user, saves and unsaves one campsite, and logs out. Needs curl and
# python3. A free Render backend sleeps when idle, so the first request can take a minute.
set -uo pipefail

API="${1:?usage: smoke_test.sh <backend-url> <frontend-url>}"
WEB="${2:?usage: smoke_test.sh <backend-url> <frontend-url>}"
API="${API%/}"
WEB="${WEB%/}"
failures=0

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failures=$((failures + 1)); }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# Wakes a sleeping backend, then checks it.
health=$(curl -s --max-time 120 "$API/api/health/")
[[ "$health" == *'"ok"'* ]] && pass "health: $health" || fail "health: ${health:-no response}"

# With DEBUG off an unknown URL gets Django's plain 404 page, not the URL-pattern listing.
notfound=$(curl -s "$API/api/no-such-page/")
[[ "$notfound" != *"URLconf"* ]] && pass "DEBUG off: 404 page lists no URL patterns" ||
  fail "DEBUG looks on: the 404 page lists URL patterns"

page=$(curl -s --max-time 60 "$WEB/")
[[ "$page" == *'<div id="root"'* ]] && pass "frontend serves index.html" || fail "frontend index.html"
deep=$(curl -s -o /dev/null -w '%{http_code}' "$WEB/discover")
[[ "$deep" == 200 ]] && pass "frontend client route /discover -> 200" || fail "frontend /discover -> $deep"

cors=$(curl -s -D - -o /dev/null -H "Origin: $WEB" "$API/api/health/" | tr -d '\r' |
  grep -i '^access-control-allow-origin:' | cut -d' ' -f2)
[[ "$cors" == "$WEB" ]] && pass "CORS allows $WEB" || fail "CORS header: '${cors}'"

# A box in the central Adirondacks, inside the map's opening view.
BBOX="-74.4,43.8,-74.0,44.1"
map=$(curl -s --max-time 90 "$API/api/map-data/?bbox=$BBOX")
counts=$(printf '%s' "$map" |
  json "' '.join(f'{k}={len(v[\"features\"])}' for k, v in d['layers'].items())" 2>/dev/null)
[[ "$counts" =~ =[1-9] ]] && pass "map-data: $counts" || fail "map-data: ${map:0:200}"

site=$(curl -s --max-time 60 "$API/api/campsites/?bbox=$BBOX" | json "d['features'][0]['id']" 2>/dev/null)
[[ -n "$site" ]] && pass "campsite to save: $site" || fail "no campsite in $BBOX"

USER="smoke$(date +%s)"
# Random, so the password validators never see it resemble the username.
PASSWORD="Pw-$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"email\":\"$USER@example.com\",\"password\":\"$PASSWORD\"}" \
  "$API/api/auth/register/")
[[ "$code" == 201 ]] && pass "register $USER -> 201" || fail "register -> $code"

token=$(curl -s -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASSWORD\"}" "$API/api/auth/login/" |
  json "d['token']" 2>/dev/null)
[[ -n "$token" ]] && pass "login -> token" || fail "login returned no token"
AUTH="Authorization: Token $token"

if [[ -n "$site" && -n "$token" ]]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "$AUTH" "$API/api/saved-campsites/$site/")
  [[ "$code" == 201 ]] && pass "save $site -> 201" || fail "save -> $code"
  listed=$(curl -s -H "$AUTH" "$API/api/saved-campsites/")
  [[ "$listed" == *"$site"* ]] && pass "saved list contains $site" || fail "saved list: ${listed:0:200}"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "$AUTH" "$API/api/saved-campsites/$site/")
  [[ "$code" == 204 ]] && pass "unsave $site -> 204" || fail "unsave -> $code"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "$AUTH" "$API/api/auth/logout/")
  [[ "$code" == 204 ]] && pass "logout -> 204" || fail "logout -> $code"
fi

echo
if ((failures)); then echo "$failures check(s) FAILED"; exit 1; fi
echo "All checks passed"
