from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, attrs):
        # Run against an unsaved User so UserAttributeSimilarityValidator can compare
        # the password to the username/email being registered, not just check it alone.
        candidate = User(username=attrs["username"], email=attrs["email"])
        validate_password(attrs["password"], user=candidate)
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )


class SavedCampsiteSerializer(serializers.Serializer):
    """One saved campsite, flattened for a list view.

    `id` is the campsite's source_id -- the same string the map API puts in each GeoJSON
    Feature's `id` (docs/api.md#feature-id) and the same string the save/unsave endpoints
    route on. Keeping all three identical is what lets the frontend mark which pins on the
    map are already saved without a second lookup, and it is why the internal primary key
    stays unexposed here as it is everywhere else.

    The properties mirror the map API's campsite layer (name, site_type, reservable,
    capacity) so that a saved row and a map feature describe a campsite the same way.

    Coordinates are flat floats rather than GeoJSON geometry. A campsite is a Point, so
    this is not a payload-size decision -- full geometry would cost a handful of bytes.
    It is that the two things the frontend does with this list are render a row and call
    flyTo(longitude, latitude), and neither wants to unwrap a nested coordinate array.

    reservable and capacity stay null when the source didn't say. DRF writes None straight
    through without calling the field, so a null reservable is not flattened into false --
    "unknown" and "not reservable" are different answers.
    """

    id = serializers.CharField(source="campsite.source_id", read_only=True)
    name = serializers.CharField(source="campsite.name", read_only=True)
    site_type = serializers.CharField(source="campsite.site_type", read_only=True)
    reservable = serializers.BooleanField(source="campsite.reservable", read_only=True)
    capacity = serializers.IntegerField(source="campsite.capacity", read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    saved_at = serializers.DateTimeField(source="created_at", read_only=True)

    def get_latitude(self, saved) -> float:
        return saved.campsite.geom.y

    def get_longitude(self, saved) -> float:
        return saved.campsite.geom.x
