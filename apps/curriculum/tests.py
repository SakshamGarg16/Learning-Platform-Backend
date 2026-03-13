import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework import status
from apps.accounts.models import Learner
from .models import (
    Track,
    Module,
    Lesson,
    Assessment,
    AssessmentAttempt,
    TrackEnrollment,
    Roadmap,
    RoadmapStep,
    RoadmapEnrollment,
    Certificate,
    FinalAssessmentAttempt,
)

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
        self.user = User.objects.create_user(username="student_curric@test.com", email="student_curric@test.com")
        self.learner = Learner.objects.create(email="student_curric@test.com", full_name="Student", auth_user_id="student_curric_ak")
        
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

    def test_submit_multi_select(self):
        self.client.force_login(self.user)
        # Add a multi-select question
        self.assessment.questions_data = [
            {
                "question": "Select A and B",
                "options": ["A", "B", "C"],
                "correct_answer": [0, 1],
                "type": "multi_select"
            }
        ]
        self.assessment.save()
        
        # Perfect match
        data = {"answers": {"0": [0, 1]}}
        response = self.client.post(self.submit_url, data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.json()['score'], 100.0)
        
        # Reset and partial/wrong match
        AssessmentAttempt.objects.all().delete()
        data = {"answers": {"0": [0, 2]}}
        response = self.client.post(self.submit_url, data=json.dumps(data), content_type='application/json')
        # DRF error if not found? No, our logic handles it.
        self.assertEqual(response.json()['score'], 0.0)

class TrackAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username="admin@tracks.com", email="admin@tracks.com", is_staff=True)
        self.track = Track.objects.create(title="Management Track")
        self.user = User.objects.create_user(username="student@tracks.com", email="student@tracks.com")
        self.learner = Learner.objects.create(email="student@tracks.com", full_name="Student", auth_user_id="s1")
        TrackEnrollment.objects.create(learner=self.learner, track=self.track)
        
    def test_enrolled_candidates_list(self):
        self.client.force_login(self.admin)
        url = f'/api/tracks/{self.track.id}/enrolled_candidates/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['email'], "student@tracks.com")

    def test_candidate_dossier(self):
        self.client.force_login(self.admin)
        url = f'/api/tracks/{self.track.id}/candidate_dossier/{self.learner.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['learner']['email'], "student@tracks.com")


class RoadmapAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username="admin@roadmaps.com", email="admin@roadmaps.com", is_staff=True)
        self.learner_user = User.objects.create_user(username="student@roadmaps.com", email="student@roadmaps.com")
        self.learner = Learner.objects.create(email="student@roadmaps.com", full_name="Roadmap Student", auth_user_id="roadmap_student")

        self.roadmap = Roadmap.objects.create(title="Backend Roadmap", description="Plan")
        self.track_1 = Track.objects.create(title="Track 1", description="First")
        self.track_2 = Track.objects.create(title="Track 2", description="Second")

        self.step_1 = RoadmapStep.objects.create(roadmap=self.roadmap, title="Step 1", order=0, track=self.track_1)
        self.step_2 = RoadmapStep.objects.create(roadmap=self.roadmap, title="Step 2", order=1, track=self.track_2)

        self.module_1 = Module.objects.create(track=self.track_1, title="Module 1", order=0)
        self.module_2 = Module.objects.create(track=self.track_2, title="Module 2", order=0)
        self.assessment_1 = Assessment.objects.create(module=self.module_1, title="A1", questions_data=[])
        self.assessment_2 = Assessment.objects.create(module=self.module_2, title="A2", questions_data=[])

        RoadmapEnrollment.objects.create(learner=self.learner, roadmap=self.roadmap)
        AssessmentAttempt.objects.create(
            learner=self.learner,
            assessment=self.assessment_1,
            answers_data={},
            score=100,
            passed=True
        )

    def test_enrolled_candidates_list(self):
        self.client.force_login(self.admin)
        url = f'/api/roadmaps/{self.roadmap.id}/enrolled_candidates/'

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['email'], "student@roadmaps.com")
        self.assertEqual(data[0]['progress'], 50.0)
        self.assertEqual(data[0]['current_focus']['step_id'], str(self.step_2.id))
        self.assertEqual(data[0]['current_focus']['current_module']['id'], str(self.module_2.id))
        self.assertEqual(data[0]['current_focus']['current_module']['title'], "Module 2")
        self.assertEqual(len(data[0]['steps']), 2)
        self.assertEqual(data[0]['steps'][0]['progress'], 100.0)
        self.assertEqual(data[0]['steps'][0]['is_completed'], True)
        self.assertEqual(data[0]['steps'][0]['current_module']['id'], str(self.module_1.id))
        self.assertEqual(data[0]['steps'][1]['progress'], 0.0)
        self.assertEqual(data[0]['steps'][1]['is_completed'], False)
        self.assertEqual(data[0]['steps'][1]['current_module']['id'], str(self.module_2.id))

    def test_enrolled_candidates_requires_admin(self):
        self.client.force_login(self.learner_user)
        url = f'/api/roadmaps/{self.roadmap.id}/enrolled_candidates/'

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)


class FinalAssessmentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="final@test.com", email="final@test.com")
        self.learner = Learner.objects.create(email="final@test.com", full_name="Final User", auth_user_id="final_ak")

        self.track = Track.objects.create(title="Platform Engineering", description="End to end")
        self.module = Module.objects.create(track=self.track, title="Core Module", order=0)
        self.assessment = Assessment.objects.create(
            module=self.module,
            questions_data=[{"question": "Q1", "options": ["A", "B"], "correct_answer": [0], "type": "mcq"}]
        )
        AssessmentAttempt.objects.create(
            learner=self.learner,
            assessment=self.assessment,
            answers_data={"0": 0},
            score=100,
            passed=True
        )

        self.roadmap = Roadmap.objects.create(title="Engineering Roadmap", description="Roadmap")
        self.step = RoadmapStep.objects.create(roadmap=self.roadmap, title="Step 1", order=0, track=self.track)

    @patch('apps.curriculum.views.generate_final_assessment_questions')
    def test_track_final_assessment_pass_issues_certificate(self, mock_generate):
        self.client.force_login(self.user)
        mock_generate.return_value = {
            "title": "Track Final",
            "description": "Hard mode",
            "passing_score": 85,
            "time_limit_minutes": 60,
            "questions": [
                {"question": "Hard Q1", "options": ["A", "B"], "correct_answer": [0], "type": "mcq"},
                {"question": "Hard Q2", "options": ["A", "B"], "correct_answer": [1], "type": "mcq"},
            ]
        }

        response = self.client.get(f'/api/tracks/{self.track.id}/final_assessment/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['available'], True)
        self.assertEqual(response.json()['attempts_remaining'], 3)

        submit_response = self.client.post(
            f'/api/tracks/{self.track.id}/submit_final_assessment/',
            data=json.dumps({"answers": {"0": 0, "1": 1}, "integrity_flags": {}}),
            content_type='application/json'
        )

        self.assertEqual(submit_response.status_code, 200)
        self.assertTrue(submit_response.json()['passed'])
        self.assertEqual(Certificate.objects.count(), 1)
        self.assertEqual(FinalAssessmentAttempt.objects.count(), 1)
        self.assertEqual(submit_response.json()['attempt_number'], 1)

    @patch('apps.curriculum.views.generate_final_assessment_questions')
    def test_roadmap_final_assessment_integrity_failure(self, mock_generate):
        self.client.force_login(self.user)
        mock_generate.side_effect = [
            {
                "title": "Roadmap Final",
                "description": "Hard mode",
                "passing_score": 85,
                "time_limit_minutes": 30,
                "questions": [
                    {"question": "Hard Q1", "options": ["A", "B"], "correct_answer": [0], "type": "mcq"}
                ]
            },
            {
                "title": "Roadmap Final Retry",
                "description": "Harder mode",
                "passing_score": 85,
                "time_limit_minutes": 30,
                "questions": [
                    {"question": "Hard Q2", "options": ["A", "B"], "correct_answer": [1], "type": "mcq"}
                ]
            }
        ]

        response = self.client.get(f'/api/roadmaps/{self.roadmap.id}/final_assessment/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['available'], True)
        self.assertEqual(response.json()['attempts_remaining'], 3)

        submit_response = self.client.post(
            f'/api/roadmaps/{self.roadmap.id}/submit_final_assessment/',
            data=json.dumps({"answers": {"0": 0}, "integrity_flags": {"tab_switch_count": 1}}),
            content_type='application/json'
        )

        self.assertEqual(submit_response.status_code, 200)
        self.assertFalse(submit_response.json()['passed'])
        self.assertEqual(submit_response.json()['terminated_reason'], "Integrity violation detected during proctored final evaluation.")
        self.assertEqual(submit_response.json()['attempt_number'], 1)

        followup_response = self.client.get(f'/api/roadmaps/{self.roadmap.id}/final_assessment/')
        self.assertEqual(followup_response.status_code, 200)
        self.assertEqual(followup_response.json()['available'], True)
        self.assertEqual(followup_response.json()['attempts_remaining'], 2)
        self.assertEqual(followup_response.json()['assessment']['questions_data'][0]['question'], "Hard Q2")
        latest_attempt = FinalAssessmentAttempt.objects.order_by('-attempt_number').first()
        self.assertEqual(latest_attempt.questions_snapshot[0]['question'], "Hard Q1")

class LessonTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="lesson@test.com", email="lesson@test.com")
        self.track = Track.objects.create(title="Track 1")
        self.module = Module.objects.create(track=self.track, title="M1")
        self.lesson = Lesson.objects.create(module=self.module, title="L1")
        self.gen_url = f'/api/lessons/{self.lesson.id}/generate_content/'

    @patch('apps.curriculum.views.generate_lesson_content')
    def test_generate_lesson_content(self, mock_gen):
        self.client.force_login(self.user)
        mock_gen.return_value = "AI generated content"
        
        response = self.client.post(self.gen_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'], "AI generated content")

class CurriculumEdgeCaseTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="edge@curric.com", email="edge@curric.com")
        self.learner = Learner.objects.create(email="edge@curric.com", full_name="Edge", auth_user_id="e1")
        self.admin = User.objects.create_user(username="staff@curric.com", email="staff@curric.com", is_staff=True)

    def test_track_creation_anonymous(self):
        # Should use operator fallback
        data = {"title": "Anon Track", "description": "Anon Desc"}
        response = self.client.post('/api/tracks/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Track.objects.get(title="Anon Track").created_by.email, "operator@example.com")

    def test_dossier_not_enrolled(self):
        self.client.force_login(self.admin)
        track = Track.objects.create(title="T")
        other_learner = Learner.objects.create(email="other@test.com", full_name="Other", auth_user_id="o1")
        url = f'/api/tracks/{track.id}/candidate_dossier/{other_learner.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_submit_attempt_repeat_error(self):
        self.client.force_login(self.user)
        mod = Module.objects.create(track=Track.objects.create(title="T"), title="M")
        ass = Assessment.objects.create(module=mod, title="A", questions_data=[{"question": "Q", "options": ["A"], "correct_index": 0}])
        
        # First attempt
        AssessmentAttempt.objects.create(learner=self.learner, assessment=ass, score=100, passed=True)
        
        # Second attempt should fail
        url = f'/api/assessments/{ass.id}/submit_attempt/'
        response = self.client.post(url, data=json.dumps({"answers": {"0": 0}}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been completed", response.json()['error'])

    @patch('apps.ai_generation.langgraph_workflows.assessment_generator_app.invoke')
    def test_generate_assessment_questions(self, mock_invoke):
        self.client.force_login(self.admin)
        mod = Module.objects.create(track=Track.objects.create(title="T"), title="M")
        ass = Assessment.objects.create(module=mod, title="A")
        mock_invoke.return_value = {"assessment_questions": [{"question": "Q?"}]}
        
        url = f'/api/assessments/{ass.id}/generate_questions/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        ass.refresh_from_db()
        self.assertEqual(len(ass.questions_data), 1)

class CurriculumDeepTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username="u1@test.com", email="u1@test.com")
        self.l1 = Learner.objects.create(email="u1@test.com", full_name="L1", auth_user_id="l1_ak")
        
        self.user2 = User.objects.create_user(username="u2@test.com", email="u2@test.com")
        self.l2 = Learner.objects.create(email="u2@test.com", full_name="L2", auth_user_id="l2_ak")
        
        self.track = Track.objects.create(title="T1", created_by=self.l1)

    def test_track_queryset_visibility(self):
        # User 1 is creator, can see it
        self.client.force_login(self.user1)
        response = self.client.get('/api/tracks/')
        self.assertEqual(len(response.json()), 1)
        
        # User 2 is neither creator nor enrolled, should NOT see it (filtered queryset)
        self.client.force_login(self.user2)
        response = self.client.get('/api/tracks/')
        self.assertEqual(len(response.json()), 0)

    @patch('apps.ai_generation.services.analyze_resume_for_curriculum')
    def test_enroll_with_resume(self, mock_analyze):
        self.client.force_login(self.user2)
        # Give learner a resume
        self.l2.resume = "fake.pdf"
        self.l2.save()
        
        mock_analyze.return_value = "Optimized for L2"
        
        url = f'/api/tracks/{self.track.id}/enroll/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        
        enrollment = TrackEnrollment.objects.get(learner=self.l2, track=self.track)
        self.assertEqual(enrollment.personalized_summary, "Optimized for L2")

    @patch('apps.curriculum.views.generate_lesson_content')
    def test_lesson_generate_content_anonymous(self, mock_gen):
        mock_gen.return_value = "Public info"
        lesson = Lesson.objects.create(module=Module.objects.create(track=self.track, title="M"), title="L")
        url = f'/api/lessons/{lesson.id}/generate_content/'
        
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        lesson.refresh_from_db()
        self.assertEqual(lesson.content, "Public info")
