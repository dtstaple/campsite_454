"""
The configured regions (TM05-102), for the Discover page's region selector.

    GET /api/regions/

From backend/pipeline/regions.yml, the same config the ingest reads, with how many named
trails each one holds, so the page can show which regions have data yet.
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.layers import envelope
from geodata.models import TrailRoute
from pipeline.regions import load_regions


@api_view(["GET"])
def regions_view(request):
    out = []
    for name, area in load_regions().items():
        trails = TrailRoute.objects.exclude(name="").filter(geom__bboverlaps=envelope(area.bbox))
        out.append(
            {
                "id": name,
                "label": area.label,
                "bbox": list(area.bbox),
                "states": list(area.states),
                "trails": trails.count(),
            }
        )
    return Response(out)
