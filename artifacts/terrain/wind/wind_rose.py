"""The Adirondacks' prevailing wind from Open-Meteo's historical archive (ERA5 reanalysis).

For each point: 10 years of hourly 10 m wind, binned into 8 compass sectors by the
direction it blows FROM. Calm hours (under 1 m/s) are left out. Prints JSON.
"""

import json
import math
import sys
import urllib.request

POINTS = {
    "Marcy Dam (High Peaks)": (44.159, -73.951),
    "Lake Placid": (44.279, -73.980),
    "Newcomb (central)": (43.973, -74.164),
    "Old Forge (southwest)": (43.711, -74.974),
}
START, END = "2016-01-01", "2025-12-31"
SECTORS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
    f"&start_date={START}&end_date={END}"
    "&hourly=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms&timezone=UTC"
)


def sector(deg):
    return SECTORS[int(((deg % 360) + 22.5) // 45) % 8]


out = {
    "source": "Open-Meteo Historical Weather API (ERA5 reanalysis), hourly 10 m wind",
    "period": f"{START} to {END}",
    "calm_below_ms": 1.0,
    "url_template": URL,
    "points": {},
}
all_counts = dict.fromkeys(SECTORS, 0)
all_speed = dict.fromkeys(SECTORS, 0.0)
for name, (lat, lon) in POINTS.items():
    req = urllib.request.Request(
        URL.format(lat=lat, lon=lon), headers={"User-Agent": "campsite-terrain-docs"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        hourly = json.load(r)["hourly"]
    counts = dict.fromkeys(SECTORS, 0)
    speed = dict.fromkeys(SECTORS, 0.0)
    x = y = 0.0
    used = total = 0
    for s, d in zip(hourly["wind_speed_10m"], hourly["wind_direction_10m"], strict=True):
        if s is None or d is None:
            continue
        total += 1
        if s < 1.0:
            continue
        used += 1
        counts[sector(d)] += 1
        speed[sector(d)] += s
        x += s * math.sin(math.radians(d))
        y += s * math.cos(math.radians(d))
    for k in SECTORS:
        all_counts[k] += counts[k]
        all_speed[k] += speed[k]
    out["points"][name] = {
        "lat": lat,
        "lon": lon,
        "hours": total,
        "windy_hours": used,
        "share_pct": {k: round(100 * counts[k] / used, 1) for k in SECTORS},
        "speed_weighted_share_pct": {
            k: round(100 * speed[k] / sum(speed.values()), 1) for k in SECTORS
        },
        "resultant_from_deg": round(math.degrees(math.atan2(x, y)) % 360, 1),
    }
n = sum(all_counts.values())
out["all_points"] = {
    "share_pct": {k: round(100 * all_counts[k] / n, 1) for k in SECTORS},
    "speed_weighted_share_pct": {
        k: round(100 * all_speed[k] / sum(all_speed.values()), 1) for k in SECTORS
    },
}
json.dump(out, sys.stdout, indent=2)
