import uuid
from django.db import models
from apps.accounts.models import Learner


class Track(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField()
    is_ai_generated = models.BooleanField(default=False)
    original_topic = models.CharField(max_length=255, blank=True, null=True, help_text="The prompt/topic used to generate this track")
    
    # Who created this track (admin or linked to a specific user if custom generated)
    created_by = models.ForeignKey(Learner, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_tracks')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class TrackEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='enrollments')
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    
    # AI generated summary of how this track relates to the learner's specific background (from resume)
    personalized_summary = models.TextField(blank=True, help_text="Summary of how this curriculum relates to the learner's existing background (extracted via AI analysis)")
    
    class Meta:
        unique_together = ('learner', 'track')

    def __str__(self):
        return f"{self.learner.email} enrolled in {self.track.title}"


class Module(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    is_remedial = models.BooleanField(default=False, help_text="True if this module was generated specifically as a remedial lesson")
    remedial_for_learner = models.ForeignKey(Learner, on_delete=models.SET_NULL, null=True, blank=True, related_name='remedial_modules')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.track.title} - {self.title}"


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True, help_text="AI generated detailed explanation")
    order = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.module.title} - {self.title}"


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.OneToOneField(Module, on_delete=models.CASCADE, related_name='assessment')
    title = models.CharField(max_length=255, default="Module Assessment")
    questions_data = models.JSONField(default=list, help_text="JSON array of questions and options")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Assessment for {self.module.title}"


class AssessmentAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='assessment_attempts')
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='attempts')
    
    answers_data = models.JSONField(default=dict, help_text="Learner's submitted answers")
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(default=False)
    
    ai_feedback = models.TextField(blank=True, help_text="AI analysis of why they failed and what they missed")
    remedial_module_generated = models.OneToOneField(Module, on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_from_attempt', help_text="Link to the remedial module if created")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.learner.email} - {self.assessment.title} - {self.score}"
