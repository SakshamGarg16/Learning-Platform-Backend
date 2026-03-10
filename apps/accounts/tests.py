import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.conf import settings
from rest_framework import status
from apps.accounts.models import Learner

class AuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.signup_url = '/api/auth/signup/'
        self.login_url = '/api/auth/login/'
        self.me_url = '/api/learners/me/'
        
        self.valid_user_data = {
            "email": "test_auth@example.com",
            "password": "StrongPassword@123",
            "full_name": "Test User",
            "is_admin": False
        }

    @patch('requests.post')
    def test_signup_success(self, mock_post):
        # Mock Authentik user creation
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"pk": 100}
        
        # Second call for password set (mocking 204 No Content)
        mock_post.side_effect = [
            MagicMock(status_code=201, json=lambda: {"pk": 100}),
            MagicMock(status_code=204)
        ]

        response = self.client.post(
            self.signup_url, 
            data=json.dumps(self.valid_user_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email=self.valid_user_data['email']).exists())
        self.assertTrue(Learner.objects.filter(email=self.valid_user_data['email']).exists())

    @patch('requests.Session')
    @patch('requests.get')
    def test_login_success(self, mock_get, mock_session_class):
        # Setup mock user
        User.objects.create_user(username="login_test@example.com", email="login_test@example.com")
        Learner.objects.create(email="login_test@example.com", auth_user_id="101", full_name="Login Test")
        
        # Mock the session flow
        mock_session = mock_session_class.return_value
        mock_session.get.return_value.status_code = 200
        # Identification step
        mock_session.post.side_effect = [
            MagicMock(status_code=200), # Id
            MagicMock(status_code=200)  # Password
        ]
        
        # Mock the Core API user fetch
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "results": [{
                "pk": 101,
                "email": "login_test@example.com",
                "name": "Login Test",
                "is_superuser": False
            }]
        }

        login_data = {
            "email": "login_test@example.com",
            "password": "StrongPassword@123"
        }
        
        response = self.client.post(
            self.login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_login_invalid_payload(self):
        response = self.client.post(
            self.login_url,
            data=json.dumps({"email": "wrong"}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('requests.Session')
    def test_login_invalid_credentials(self, mock_session_class):
        mock_session = mock_session_class.return_value
        mock_session.get.return_value.status_code = 200
        mock_session.post.side_effect = [
            MagicMock(status_code=200), # Id
            MagicMock(status_code=401, text="Invalid password") # Failed Password
        ]

        login_data = {
            "email": "nonexistent@example.com",
            "password": "wrongpassword"
        }
        
        response = self.client.post(
            self.login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

class LearnerMeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="me_test@example.com", email="me_test@example.com", first_name="Me")
        self.learner = Learner.objects.create(email="me_test@example.com", full_name="Me Test", auth_user_id="200")
        self.me_url = '/api/learners/me/'

    def test_me_unauthorized(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_authorized(self):
        self.client.force_login(self.user)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['email'], "me_test@example.com")
        self.assertIn('csrf_token', response.json())
