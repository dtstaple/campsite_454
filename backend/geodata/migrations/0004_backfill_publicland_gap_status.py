"""
Backfill PublicLand.gap_status from the raw PAD-US payload.

The value was already ingested -- every row's `raw` carries GAP_Sts -- so this reads it
out of the JSON rather than re-fetching 1,574 parcels from the ArcGIS service. This is
exactly the case the `raw` column exists for: a field we did not anticipate, promoted to
a real column locally instead of over the network.

Rows whose raw payload has no GAP_Sts, or a value outside "1".."4", are left blank rather
than guessed at. Blank means "the source did not say", which is not the same as 4.
"""

from django.db import migrations

VALID = {"1", "2", "3", "4"}


def backfill(apps, schema_editor):
    PublicLand = apps.get_model("geodata", "PublicLand")

    updated = []
    for parcel in PublicLand.objects.exclude(raw={}).iterator(chunk_size=500):
        value = (parcel.raw or {}).get("GAP_Sts")
        value = str(value).strip() if value is not None else ""
        if value in VALID and parcel.gap_status != value:
            parcel.gap_status = value
            updated.append(parcel)

    PublicLand.objects.bulk_update(updated, ["gap_status"], batch_size=500)


def clear(apps, schema_editor):
    """Reverse is a straight clear: the source of truth stays in `raw` either way."""
    PublicLand = apps.get_model("geodata", "PublicLand")
    PublicLand.objects.update(gap_status="")


class Migration(migrations.Migration):
    dependencies = [("geodata", "0003_publicland_gap_status_and_more")]

    operations = [migrations.RunPython(backfill, clear)]
