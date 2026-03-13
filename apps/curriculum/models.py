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


class FinalAssessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    track = models.OneToOneField('Track', on_delete=models.CASCADE, null=True, blank=True, related_name='final_assessment')
    roadmap = models.OneToOneField('Roadmap', on_delete=models.CASCADE, null=True, blank=True, related_name='final_assessment')
    title = models.CharField(max_length=255, default="Final Evaluation")
    description = models.TextField(blank=True)
    questions_data = models.JSONField(default=list, help_text="JSON array of advanced final evaluation questions")
    prepared_retry_questions_data = models.JSONField(default=list, blank=True)
    prepared_retry_time_limit_minutes = models.PositiveIntegerField(default=0)
    prepared_retry_attempt_number = models.PositiveIntegerField(default=0)
    passing_score = models.FloatField(default=80.0)
    time_limit_minutes = models.PositiveIntegerField(default=45)
    max_attempts = models.PositiveIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        target = self.track.title if self.track else self.roadmap.title if self.roadmap else "Unknown"
        return f"Final Assessment: {target}"


class FinalAssessmentAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='final_assessment_attempts')
    final_assessment = models.ForeignKey(FinalAssessment, on_delete=models.CASCADE, related_name='attempts')
    questions_snapshot = models.JSONField(default=list)
    answers_data = models.JSONField(default=dict)
    integrity_flags = models.JSONField(default=dict, blank=True)
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(default=False)
    terminated_reason = models.CharField(max_length=255, blank=True)
    attempt_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.learner.email} - {self.final_assessment.title} - {self.score}"


class Certificate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='certificates')
    track = models.ForeignKey('Track', on_delete=models.CASCADE, null=True, blank=True, related_name='certificates')
    roadmap = models.ForeignKey('Roadmap', on_delete=models.CASCADE, null=True, blank=True, related_name='certificates')
    final_assessment_attempt = models.OneToOneField(FinalAssessmentAttempt, on_delete=models.CASCADE, related_name='certificate')
    certificate_code = models.CharField(max_length=32, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.track.title if self.track else self.roadmap.title if self.roadmap else "Unknown"
        return f"Certificate {self.certificate_code} - {target}"


class PersonalizedLessonContent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='personalized_contents')
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='personalized_lessons')
    content = models.TextField(help_text="Personalized AI content for this specific learner")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('lesson', 'learner')

    def __str__(self):
        return f"Personalized: {self.learner.email} - {self.lesson.title}"


class Roadmap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField()
    
    created_by = models.ForeignKey(Learner, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_roadmaps')
    is_finalized = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class RoadmapStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    roadmap = models.ForeignKey(Roadmap, on_delete=models.CASCADE, related_name='steps')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    # Each step maps to a Track once finalized/generated
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True, blank=True, related_name='roadmap_steps')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.roadmap.title} - Step {self.order}: {self.title}"


class RoadmapEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='roadmap_enrollments')
    roadmap = models.ForeignKey(Roadmap, on_delete=models.CASCADE, related_name='enrollments')
    
    enrolled_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('learner', 'roadmap')

    def __str__(self):
        return f"{self.learner.email} enrolled in {self.roadmap.title}"
