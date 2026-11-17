# TM05-171: campsite access difficulty from the nearest reachable trailhead.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("enrichment", "0003_stored_factor_results"),
    ]

    operations = [
        migrations.AddField(
            model_name="campsitefacts",
            name="access_class",
            field=models.CharField(blank=True, db_index=True, max_length=16),
        ),
        migrations.AddField(
            model_name="campsitefacts",
            name="access_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="campsitefacts",
            name="access_trailhead",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="campsitefacts",
            name="access_distance_m",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campsitefacts",
            name="access_gain_m",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campsitefacts",
            name="access_time_s",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
