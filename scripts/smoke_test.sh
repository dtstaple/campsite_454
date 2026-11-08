#!/usr/bin/env bash
# Smoke test a CampSite deployment (TM05-113, extended in TM05-161).
#   scripts/smoke_test.sh <backend-url> [<frontend-url>]
#   scripts/smoke_test.sh https://campsite-api.onrender.com https://campsite-web.onrender.com
#   scripts/smoke_test.sh http://localhost:8000          # a backend alone: frontend checks skipped
#
# Checks, in order: health; DEBUG off; the frontend and a client-side route; CORS; map data;
# vector tiles; a trail panel (search, then the route with its elevation profile); Find
# campsites along that trail; route planning on the trail graph; register, sign in, save a
# campsite, list and unsave it, and sign out. Registers one throwaway user (smoke<epoch>)
# and deletes it again at the end.
# Needs curl and python3. A sleeping backend or a cold campsite search can take a minute, so
# the slow calls allow two or more. Exits non-zero if anything failed.
set -uo pipefail

API="${1:?usage: smoke_test.sh <backend-url> [<frontend-url>]}"
WEB="${2:-}"
API="${API%/}"
WEB="${WEB%/}"
failures=0

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failures=$((failures + 1)); }
skip() { printf 'SKIP %s\n' "$1"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# Wakes a sleeping backend, then checks it.
health=$(curl -s --max-time 120 "$API/api/health/")
[[ "$health" == *'"ok"'* ]] && pass "health: $health" || fail "health: ${health:-no response}"

# With DEBUG off an unknown URL gets Django's plain 404 page, not the URL-pattern listing.
notfound=$(curl -s "$API/api/no-such-page/")
[[ "$notfound" != *"URLconf"* ]] && pass "DEBUG off: 404 page lists no URL patterns" ||
  fail "DEBUG looks on: the 404 page lists URL patterns"

if [[ -n "$WEB" ]]; then
  page=$(curl -s --max-time 60 "$WEB/")
  [[ "$page" == *'<div id="root"'* ]] && pass "frontend serves index.html" || fail "frontend index.html"
  deep=$(curl -s -o /dev/null -w '%{http_code}' "$WEB/discover")
  [[ "$deep" == 200 ]] && pass "frontend client route /discover -> 200" || fail "frontend /discover -> $deep"
  cors=$(curl -s -D - -o /dev/null -H "Origin: $WEB" "$API/api/health/" | tr -d '\r' |
    grep -i '^access-control-allow-origin:' | cut -d' ' -f2)
  [[ "$cors" == "$WEB" ]] && pass "CORS allows $WEB" || fail "CORS header: '${cors}'"
else
  skip "frontend and CORS (no frontend URL given)"
fi

# A box in the central Adirondacks, inside the map's opening view.
BBOX="-74.4,43.8,-74.0,44.1"
map=$(curl -s --max-time 90 "$API/api/map-data/?bbox=$BBOX")
counts=$(printf '%s' "$map" |
  json "' '.join(f'{k}={len(v[\"features\"])}' for k, v in d['layers'].items())" 2>/dev/null)
[[ "$counts" =~ =[1-9] ]] && pass "map-data: $counts" || fail "map-data: ${map:0:200}"

# Vector tiles: the z12 trails tile over the High Peaks (Van Hoevenberg Trail, -73.958 44.183).
TILE="12/1206/1486"
read -r code type < <(curl -s -o /dev/null -w '%{http_code} %{content_type}\n' --max-time 60 \
  "$API/api/tiles/trails/$TILE.mvt")
[[ "$code" == 200 && "$type" == application/vnd.mapbox-vector-tile* ]] &&
  pass "vector tile trails/$TILE -> 200 ($type)" || fail "vector tile trails/$TILE -> $code $type"

# A trail panel: find a named route, then open it as the panel does (with its profile).
route=$(curl -s --max-time 60 "$API/api/routes/search/?q=van%20hoevenberg" |
  json "d['results'][0]['osm_id']" 2>/dev/null)
if [[ -n "$route" ]]; then
  pass "route search: Van Hoevenberg -> $route"
  panel=$(curl -s --max-time 120 "$API/api/routes/$route/" |
    json "f\"{d['name']}, {d['length_m']:.0f} m, profile {d['profile']['status']}\"" 2>/dev/null)
  [[ -n "$panel" ]] && pass "trail panel: $panel" || fail "trail panel /api/routes/$route/"
  # Find campsites along this trail. The first search for a trail samples 3DEP: 15-35 s
  # normally, 129 s once on a busy laptop (2026-11-08), so it gets more time than the rest.
  found=$(curl -s --max-time 200 "$API/api/routes/$route/candidates/" |
    json "f\"{d['status']}, {len(d['candidates'])} potential spots, cached={d.get('cached')}\"" 2>/dev/null)
  [[ "$found" == ok,* ]] && pass "find campsites: $found" || fail "find campsites: ${found:-no answer}"
else
  fail "route search found no Van Hoevenberg Trail"
fi

# Route planning on the trail graph (TM05-119): Adirondak Loj trailhead to Marcy Dam.
plan=$(curl -s --max-time 120 -H 'Content-Type: application/json' \
  -d '{"points": [[-73.9581, 44.1832], [-73.9535, 44.1590]], "cost": "naismith"}' \
  "$API/api/routing/plan/" |
  json "f\"{d['planned']['id']}, {d['line']['length_m']:.0f} m\"" 2>/dev/null)
[[ -n "$plan" ]] && pass "route planning: $plan" || fail "route planning returned no route"

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
[[ -n "$token" ]] && pass "sign in -> token" || fail "sign in returned no token"
AUTH="Authorization: Token $token"

if [[ -n "$site" && -n "$token" ]]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "$AUTH" "$API/api/saved-campsites/$site/")
  [[ "$code" == 201 ]] && pass "save $site -> 201" || fail "save -> $code"
  listed=$(curl -s -H "$AUTH" "$API/api/saved-campsites/")
  [[ "$listed" == *"$site"* ]] && pass "saved list contains $site" || fail "saved list: ${listed:0:200}"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "$AUTH" "$API/api/saved-campsites/$site/")
  [[ "$code" == 204 ]] && pass "unsave $site -> 204" || fail "unsave -> $code"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "$AUTH" "$API/api/auth/logout/")
  [[ "$code" == 204 ]] && pass "sign out -> 204" || fail "sign out -> $code"
fi

# Clean up: sign in again and delete the throwaway account (TM05-70), so smoke runs leave no
# users behind in production.
if [[ -n "$token" ]]; then
  token=$(curl -s -H 'Content-Type: application/json' \
    -d "{\"username\":\"$USER\",\"password\":\"$PASSWORD\"}" "$API/api/auth/login/" |
    json "d['token']" 2>/dev/null)
  code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Token $token" \
    "$API/api/auth/me/")
  [[ "$code" == 204 ]] && pass "delete $USER -> 204" || fail "delete $USER -> $code (remove it in the admin)"
fi

echo
if ((failures)); then echo "$failures check(s) FAILED"; exit 1; fi
echo "All checks passed"
