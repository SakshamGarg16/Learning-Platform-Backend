import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_learner_is_admin'),
        ('curriculum', '0005_roadmap_is_finalized'),
    ]

    operations = [
        migrations.CreateModel(
            name='FinalAssessment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(default='Final Evaluation', max_length=255)),
                ('description', models.TextField(blank=True)),
                ('questions_data', models.JSONField(default=list, help_text='JSON array of advanced final evaluation questions')),
                ('passing_score', models.FloatField(default=80.0)),
                ('time_limit_minutes', models.PositiveIntegerField(default=45)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('roadmap', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='final_assessment', to='curriculum.roadmap')),
                ('track', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='final_assessment', to='curriculum.track')),
            ],
        ),
        migrations.CreateModel(
            name='FinalAssessmentAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('answers_data', models.JSONField(default=dict)),
                ('integrity_flags', models.JSONField(blank=True, default=dict)),
                ('score', models.FloatField(blank=True, null=True)),
                ('passed', models.BooleanField(default=False)),
                ('terminated_reason', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('final_assessment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='curriculum.finalassessment')),
                ('learner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='final_assessment_attempts', to='accounts.learner')),
            ],
            options={
                'unique_together': {('learner', 'final_assessment')},
            },
        ),
        migrations.CreateModel(
            name='Certificate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('certificate_code', models.CharField(max_length=32, unique=True)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('final_assessment_attempt', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='certificate', to='curriculum.finalassessmentattempt')),
                ('learner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='certificates', to='accounts.learner')),
                ('roadmap', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='certificates', to='curriculum.roadmap')),
                ('track', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='certificates', to='curriculum.track')),
            ],
        ),
    ]
