from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('curriculum', '0008_finalassessmentattempt_questions_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='finalassessment',
            name='prepared_retry_attempt_number',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='finalassessment',
            name='prepared_retry_questions_data',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='finalassessment',
            name='prepared_retry_time_limit_minutes',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
