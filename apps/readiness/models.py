import uuid
from django.db import models
from apps.accounts.models import Learner
from apps.curriculum.models import Track


class MentorReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='received_mentor_reviews')
    mentor = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='given_mentor_reviews')
    track = models.ForeignKey(Track, on_delete=models.CASCADE)
    
    score = models.FloatField(default=0.0)
    notes = models.TextField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review by {self.mentor.email} for {self.learner.email}"


class PeerReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='received_peer_reviews')
    peer = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='given_peer_reviews')
    track = models.ForeignKey(Track, on_delete=models.CASCADE)
    
    score = models.FloatField(default=0.0)
    notes = models.TextField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Peer Review by {self.peer.email} for {self.learner.email}"


class ReadinessSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(Learner, on_delete=models.CASCADE, related_name='readiness_snapshots')
    
    knowledge_score = models.FloatField(default=0.0)
    validated_score = models.FloatField(default=0.0, help_text="AI validated assessment score")
    peer_score = models.FloatField(default=0.0)
    mentor_score = models.FloatField(default=0.0)
    
    overall_score = models.FloatField(default=0.0)
    graduation_eligible = models.BooleanField(default=False)
    
    notes = models.TextField(blank=True)
    as_of = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-as_of']

    def __str__(self):
        return f"Snapshot for {self.learner.email} ({self.overall_score})"
