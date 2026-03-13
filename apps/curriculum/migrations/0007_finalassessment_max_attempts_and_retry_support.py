from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('curriculum', '0006_finalassessment_finalassessmentattempt_certificate'),
    ]

    operations = [
        migrations.AddField(
            model_name='finalassessment',
            name='max_attempts',
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AddField(
            model_name='finalassessmentattempt',
            name='attempt_number',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AlterUniqueTogether(
            name='finalassessmentattempt',
            unique_together=set(),
        ),
    ]
