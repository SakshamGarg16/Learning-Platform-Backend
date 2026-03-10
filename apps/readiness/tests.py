import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework import status
from apps.accounts.models import Learner
from apps.curriculum.models import Track, Module, Assessment, AssessmentAttempt
from .models import ReadinessSnapshot

class ReadinessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="student@test.com", email="student@test.com")
        self.learner = Learner.objects.create(email="student@test.com", full_name="Student", auth_user_id="student_ak")
        self.readiness_url = '/api/readiness/'
        self.calculate_url = '/api/readiness/calculate/'

    def test_auto_calculate_on_list(self):
        self.client.force_login(self.user)
        # Verify no snapshots exist first
        self.assertEqual(ReadinessSnapshot.objects.filter(learner=self.learner).count(), 0)
        
        response = self.client.get(self.readiness_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have auto-created a snapshot
        self.assertEqual(ReadinessSnapshot.objects.filter(learner=self.learner).count(), 1)
        self.assertEqual(response.json()[0]['overall_score'], 0.0)

    def test_calculate_with_progress(self):
        self.client.force_login(self.user)
        
        # Setup progress: 1 passed out of 2 modules
        track = Track.objects.create(title="Testing Track")
        m1 = Module.objects.create(track=track, title="M1", order=0)
        m2 = Module.objects.create(track=track, title="M2", order=1)
        
        a1 = Assessment.objects.create(module=m1, title="A1", questions_data=[{}])
        a2 = Assessment.objects.create(module=m2, title="A2", questions_data=[{}])
        
        # Pass first assessment with 80%
        AssessmentAttempt.objects.create(
            learner=self.learner,
            assessment=a1,
            score=80.0,
            passed=True
        )
        # Fail second (should not count towards knowledge or mastery score average)
        AssessmentAttempt.objects.create(
            learner=self.learner,
            assessment=a2,
            score=20.0,
            passed=False
        )
        
        response = self.client.post(self.calculate_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 1/2 modules = 50% knowledge
        # 1 passed with 80% = 80% validated
        # (50 * 0.5) + (80 * 0.5) = 25 + 40 = 65% overall
        
        snapshot = ReadinessSnapshot.objects.filter(learner=self.learner).latest('as_of')
        self.assertEqual(snapshot.knowledge_score, 50.0)
        self.assertEqual(snapshot.validated_score, 80.0)
        self.assertEqual(snapshot.overall_score, 65.0)
        self.assertFalse(snapshot.graduation_eligible)

    def test_graduation_eligible(self):
        self.client.force_login(self.user)
        # Create a snapshot with high scores
        track = Track.objects.create(title="Track")
        m1 = Module.objects.create(track=track, title="M1")
        a1 = Assessment.objects.create(module=m1, title="A1", questions_data=[{}])
        
        # 100% progress and 100% precision
        AssessmentAttempt.objects.create(
            learner=self.learner,
            assessment=a1,
            score=100.0,
            passed=True
        )
        
        response = self.client.post(self.calculate_url)
        snapshot = response.json()
        self.assertEqual(snapshot['overall_score'], 100.0)
        self.assertTrue(snapshot['graduation_eligible'])
