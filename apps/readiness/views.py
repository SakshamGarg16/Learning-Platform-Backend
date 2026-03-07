from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import MentorReview, PeerReview, ReadinessSnapshot
from .serializers import MentorReviewSerializer, PeerReviewSerializer, ReadinessSnapshotSerializer

class MentorReviewViewSet(viewsets.ModelViewSet):
    queryset = MentorReview.objects.all()
    serializer_class = MentorReviewSerializer


class PeerReviewViewSet(viewsets.ModelViewSet):
    queryset = PeerReview.objects.all()
    serializer_class = PeerReviewSerializer


class ReadinessSnapshotViewSet(viewsets.ModelViewSet):
    queryset = ReadinessSnapshot.objects.all().order_by('-as_of')
    serializer_class = ReadinessSnapshotSerializer

    def get_learner(self, request):
        from apps.accounts.models import Learner
        if request.user.is_authenticated:
            return Learner.objects.filter(email=request.user.email).first()
        return Learner.objects.filter(email="operator@example.com").first()

    def list(self, request, *args, **kwargs):
        learner = self.get_learner(request)
        if learner and not ReadinessSnapshot.objects.filter(learner=learner).exists():
            # Auto-calculate first snapshot
            self._do_calculate(learner)
            
        # Filter for the current learner
        if learner:
            self.queryset = self.queryset.filter(learner=learner)
            
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['post'])
    def calculate(self, request):
        learner = self.get_learner(request)
        if not learner:
            return Response({"error": "No learner identified"}, status=status.HTTP_400_BAD_REQUEST)
        
        snapshot = self._do_calculate(learner)
        return Response(self.get_serializer(snapshot).data)

    def _do_calculate(self, learner):
        from apps.curriculum.models import Module, AssessmentAttempt
        from django.db.models import Avg

        # 1. Knowledge Score (Progress across all tracks)
        total_modules = Module.objects.count()
        completed_count = AssessmentAttempt.objects.filter(
            learner=learner, 
            passed=True
        ).values('assessment__module').distinct().count()
        
        knowledge_score = (completed_count / total_modules * 100) if total_modules > 0 else 0

        # 2. Validated Score (Average precision on assessments)
        validated_score = AssessmentAttempt.objects.filter(
            learner=learner,
            passed=True
        ).aggregate(Avg('score'))['score__avg'] or 0.0

        # 3. Overall Weighted Score (Mastery Focused)
        # Weightage: Knowledge Progress (50%), AI Validation Precision (50%)
        overall = (knowledge_score * 0.5) + (validated_score * 0.5)
        
        return ReadinessSnapshot.objects.create(
            learner=learner,
            knowledge_score=round(knowledge_score, 1),
            validated_score=round(validated_score, 1),
            peer_score=0.0,
            mentor_score=0.0,
            overall_score=round(overall, 1),
            graduation_eligible=(overall >= 80.0),
            notes=f"Mastery-based readiness snapshot for {learner.email}"
        )
