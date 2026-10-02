"""
Compute (or read from cache) a named route's elevation profile, optionally comparing it
with published figures (TM05-59).

    python manage.py route_profile "Van Hoevenberg Trail" \
        --published-mi 7.4 --published-gain-ft 3166

With a published gain it also prints a sensitivity table: gain over a grid of smoothing
windows and thresholds, recomputed from the stored elevations (no extra 3DEP calls), so
it is visible how much the answer depends on those two parameters rather than only on the
pair in use.
"""

from django.core.management.base import BaseCommand, CommandError

from analysis.analyses.elevation import DEFAULTS, RouteProfile, gain_loss, smooth
from geodata.models import TrailRoute

FT_PER_M = 3.28084
M_PER_MI = 1609.344


class Command(BaseCommand):
    help = "Show a named route's elevation profile statistics."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--published-mi", type=float)
        parser.add_argument("--published-gain-ft", type=float)

    def handle(self, *args, name, published_mi, published_gain_ft, **options):
        route = TrailRoute.objects.filter(name=name).order_by("-length_m").first()
        if route is None:
            raise CommandError(f"no route named {name!r}")
        outcome = RouteProfile().run(route.geom)
        value = outcome.value
        stats = value["stats"]
        self.stdout.write(
            f"{route.name} (relation/{route.osm_id}), "
            f"{'cached' if outcome.cached else 'computed'}"
        )
        self.stdout.write(f"  path: {value['path']}")
        self.stdout.write(f"  sources: {outcome.provenance.get('datasets')}")
        self.stdout.write(
            f"  length {stats['length_m'] / M_PER_MI:.2f} mi; "
            f"gain {stats['gain_m'] * FT_PER_M:,.0f} ft "
            f"(naive {stats['naive_gain_m'] * FT_PER_M:,.0f}); "
            f"loss {stats['loss_m'] * FT_PER_M:,.0f} ft; "
            f"start {stats['start_m'] * FT_PER_M:,.0f} ft; "
            f"high {stats['high_m'] * FT_PER_M:,.0f} ft; "
            f"max grade {stats['max_grade_pct']}% at {stats['max_grade_at_m'] / M_PER_MI:.2f} mi"
        )

        if published_mi:
            error = stats["length_m"] / M_PER_MI / published_mi - 1
            self.stdout.write(f"  length vs published {published_mi} mi: {error:+.1%}")
        if not published_gain_ft:
            return
        for label, gain in (("gain", stats["gain_m"]), ("naive gain", stats["naive_gain_m"])):
            error = gain * FT_PER_M / published_gain_ft - 1
            self.stdout.write(f"  {label} vs published {published_gain_ft:,.0f} ft: {error:+.1%}")

        elevations = value["elevation_m"]
        spacing = value["params"]["spacing_m"]
        thresholds = (0, 1, 3, 5, 10)
        self.stdout.write("  sensitivity: gain in ft; rows = smoothing window, cols = threshold m")
        self.stdout.write("    window " + "".join(f"{t:>8}" for t in thresholds))
        for window_m in (25, 50, 100, 200, 400):
            window = max(1, round(window_m / spacing)) | 1
            smoothed = smooth(elevations, window)
            row = "".join(
                f"{gain_loss(smoothed, max(t, 1e-9))[0] * FT_PER_M:>8,.0f}" for t in thresholds
            )
            marker = "  <- default" if window_m == DEFAULTS["smoothing_window_m"] else ""
            self.stdout.write(f"    {window_m:>4} m {row}{marker}")
