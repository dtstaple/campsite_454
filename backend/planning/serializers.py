from django.contrib.gis.geos import Point
from rest_framework import serializers

from .models import Waypoint


class WaypointSerializer(serializers.ModelSerializer):
    """A waypoint as the API reads and writes it: lon/lat numbers rather than GeoJSON, so
    the map can send back exactly the click it got."""

    # Write-only here; to_representation reads them back from the geometry.
    lon = serializers.FloatField(min_value=-180, max_value=180, write_only=True)
    lat = serializers.FloatField(min_value=-90, max_value=90, write_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Waypoint
        fields = [
            "id",
            "name",
            "kind",
            "kind_label",
            "note",
            "lon",
            "lat",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A waypoint needs a name.")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["lon"] = round(instance.geom.x, 6)
        data["lat"] = round(instance.geom.y, 6)
        return data

    def _with_geom(self, validated):
        lon = validated.pop("lon", None)
        lat = validated.pop("lat", None)
        if lon is not None or lat is not None:
            current = getattr(self.instance, "geom", None)
            lon = lon if lon is not None else current.x
            lat = lat if lat is not None else current.y
            validated["geom"] = Point(lon, lat, srid=4326)
        return validated

    def create(self, validated):
        return super().create(self._with_geom(validated))

    def update(self, instance, validated):
        return super().update(instance, self._with_geom(validated))
