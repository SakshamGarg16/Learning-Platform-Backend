from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('curriculum', '0007_finalassessment_max_attempts_and_retry_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='finalassessmentattempt',
            name='questions_snapshot',
            field=models.JSONField(default=list),
        ),
    ]
