import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework import status
from apps.accounts.models import Learner
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt, TrackEnrollment

class CurriculumTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Admin user
        self.admin_user = User.objects.create_user(username="admin@test.com", email="admin@test.com", is_staff=True)
        self.admin_learner = Learner.objects.create(email="admin@test.com", full_name="Admin", auth_user_id="admin_ak")
        
        # Standard user
        self.user = User.objects.create_user(username="user@test.com", email="user@test.com")
        self.learner = Learner.objects.create(email="user@test.com", full_name="User", auth_user_id="user_ak")
        
        # Test URLs
        self.tracks_url = '/api/tracks/'
        self.generate_url = '/api/tracks/generate/'

    def test_list_tracks_unauthorized(self):
        # Even non-logged in can see tracks if they exist (MVP behavior)
        Track.objects.create(title="Public Track", description="Desc")
        response = self.client.get(self.tracks_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('apps.curriculum.views.generate_track_curriculum')
    def test_generate_track_success(self, mock_gen):
        self.client.force_login(self.admin_user)
        
        # Mocking the AI service response
        mock_gen.return_value = {
            "title": "Python Basics",
            "description": "Learn python",
            "modules": [
                {
                    "title": "Introduction",
                    "description": "Intro module",
                    "lessons": [{"title": "What is Python?"}],
                }
            ]
        }
        
        response = self.client.post(self.generate_url, data={"topic": "Python"}, content_type='application/json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Track.objects.count(), 1)
        self.assertEqual(Module.objects.count(), 1)
        self.assertEqual(Lesson.objects.count(), 1)
        self.assertEqual(Assessment.objects.count(), 1)
        
        track = Track.objects.first()
        self.assertEqual(track.title, "Python Basics")
        self.assertTrue(track.is_ai_generated)

    def test_enroll_track(self):
        self.client.force_login(self.user)
        track = Track.objects.create(title="Django Track", description="Learn Django")
        enroll_url = f'/api/tracks/{track.id}/enroll/'
        
        response = self.client.post(enroll_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(TrackEnrollment.objects.filter(learner=self.learner, track=track).exists())

class AssessmentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="student@test.com", email="student@test.com")
        self.learner = Learner.objects.create(email="student@test.com", full_name="Student", auth_user_id="student_ak")
        
        self.track = Track.objects.create(title="Test Track")
        self.module = Module.objects.create(track=self.track, title="Module 1", order=0)
        self.assessment = Assessment.objects.create(
            module=self.module,
            questions_data=[
                {
                    "question": "What is 1+1?",
                    "options": ["1", "2", "3"],
                    "correct_index": 1,
                    "type": "mcq"
                }
            ]
        )
        self.submit_url = f'/api/assessments/{self.assessment.id}/submit_attempt/'

    def test_submit_pass(self):
        self.client.force_login(self.user)
        data = {"answers": {"0": "1"}} 
        
        response = self.client.post(self.submit_url, data=json.dumps(data), content_type='application/json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        attempt = AssessmentAttempt.objects.first()
        self.assertEqual(attempt.score, 100.0)
        self.assertTrue(attempt.passed)

    @patch('apps.curriculum.views.analyze_assessment_failure')
    def test_submit_fail_remedial(self, mock_analyze):
        self.client.force_login(self.user)
        
        # Mock AI deciding on a remedial module
        mock_analyze.return_value = {
            "feedback": "You need more practice.",
            "remedial_module": {
                "title": "Remedial Basics",
                "description": "Backup module",
                "lessons": [{"title": "Retry Lesson"}]
            }
        }
        
        # Wrong answer
        data = {"answers": {"0": "0"}}
        
        response = self.client.post(self.submit_url, data=json.dumps(data), content_type='application/json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        attempt = AssessmentAttempt.objects.first()
        self.assertFalse(attempt.passed)
        self.assertEqual(attempt.score, 0.0)
        
        # Verify remedial module creation
        self.assertEqual(Module.objects.filter(is_remedial=True).count(), 1)
        remedial = Module.objects.get(is_remedial=True)
        self.assertEqual(remedial.title, "Remedial Basics")
        self.assertEqual(remedial.order, self.module.order + 1)
