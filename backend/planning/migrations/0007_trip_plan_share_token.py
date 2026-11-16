from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0006_trip_plan_planned_route"),
    ]

    operations = [
        migrations.AddField(
            model_name="tripplan",
            name="share_token",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
