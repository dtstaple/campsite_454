from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("terrain", "0003_terrainfacts_wind"),
    ]

    operations = [
        migrations.AddField(
            model_name="terrainfacts",
            name="sun_hours",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="terrainfacts",
            name="sun_hours_level",
            field=models.CharField(
                blank=True,
                choices=[("full", "Full sun"), ("partial", "Partial sun"), ("low", "Little sun")],
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="terrainfacts",
            name="sun_hours_reason",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="terrainfacts",
            name="morning_sun",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="terrainfacts",
            name="morning_sun_reason",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
