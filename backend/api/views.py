"""
Map data endpoints.

One endpoint per layer so the frontend fetches only what the user has toggled on, plus a
combined endpoint for the initial load so the first paint is a single round trip. The
combined view delegates to the same code, so the two can never drift apart.
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.bbox import InvalidBbox, parse_bbox
from api.layers import LAYERS, MAX_LIMIT, MAX_SIMPLIFY, collect, envelope, limit_for_bbox


class InvalidParameter(ValueError):
    """A query parameter other than bbox is unusable."""


def _int_param(request, name: str, default: int | None, maximum: int) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise InvalidParameter(f"'{name}' must be a whole number, got {raw!r}") from None
    if value < 1:
        raise InvalidParameter(f"'{name}' must be at least 1, got {value}")
    return min(value, maximum)


def _simplify_param(request) -> float | None:
    raw = request.query_params.get("simplify")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        raise InvalidParameter(f"'simplify' must be a number of degrees, got {raw!r}") from None
    if value < 0:
        raise InvalidParameter(f"'simplify' cannot be negative, got {value}")
    if value > MAX_SIMPLIFY:
        raise InvalidParameter(
            f"'simplify' above {MAX_SIMPLIFY} degrees would not resemble the original "
            f"shape, got {value}"
        )
    return value or None


def _layers_param(request):
    """Which layers /api/map-data/ should actually query.

    Defaults to all of them. A client that will not draw a layer at the current zoom
    should exclude it here rather than fetching and discarding it -- below the zoom
    where individual streams are sub-pixel, that is most of the payload.
    """
    raw = request.query_params.get("layers")
    if raw is None or not str(raw).strip():
        return list(LAYERS)

    names = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in names if name not in LAYERS]
    if unknown:
        raise InvalidParameter(
            f"Unknown layer(s): {', '.join(unknown)}. Available: {', '.join(LAYERS)}"
        )
    if not names:
        raise InvalidParameter("'layers' was given but empty")
    return names


def _read_params(request):
    """bbox, limit and simplify. `limit` is None when the caller did not ask for one,
    which means the area-derived default applies."""
    bbox = parse_bbox(request.query_params.get("bbox"))
    limit = _int_param(request, "limit", None, MAX_LIMIT)
    simplify = _simplify_param(request)
    return bbox, limit, simplify


def _bad_request(exc) -> Response:
    return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
def layer_view(request, layer: str):
    """One layer as a GeoJSON FeatureCollection."""
    try:
        bbox, limit, simplify = _read_params(request)
    except (InvalidBbox, InvalidParameter) as exc:
        return _bad_request(exc)

    return Response(collect(LAYERS[layer], bbox, limit=limit, simplify=simplify))


@api_view(["GET"])
def map_data_view(request):
    """Every layer at once, for the initial map load.

    Each layer keeps its own FeatureCollection rather than being merged into one, because
    MapLibre wants a source per layer anyway and merging would throw away which layer a
    feature came from.
    """
    try:
        bbox, limit, simplify = _read_params(request)
        requested = _layers_param(request)
    except (InvalidBbox, InvalidParameter) as exc:
        return _bad_request(exc)

    # Built once and shared across layers rather than rebuilt per layer, and the
    # area-derived cap resolved once so every layer reports the same number.
    bounds = envelope(bbox)
    effective_limit = limit if limit is not None else limit_for_bbox(bbox)

    layers = {
        name: collect(LAYERS[name], bbox, limit=effective_limit, simplify=simplify, bounds=bounds)
        for name in requested
    }
    return Response(
        {
            "bbox": list(bbox),
            "layers": layers,
            "metadata": {
                "truncated": any(c["metadata"]["truncated"] for c in layers.values()),
                "returned": sum(c["metadata"]["returned"] for c in layers.values()),
                "limit": effective_limit,
                "simplify": simplify,
                "layers": requested,
            },
        }
    )
