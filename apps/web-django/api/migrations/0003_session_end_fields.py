from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_session"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="ended_reason",
            field=models.CharField(max_length=16, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="session",
            name="ended_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="session",
            name="stats",
            field=models.JSONField(default=dict),
        ),
    ]
