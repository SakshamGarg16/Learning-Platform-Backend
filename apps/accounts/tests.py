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

class LearnerProfileTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="profile@test.com", email="profile@test.com")
        self.learner = Learner.objects.create(email="profile@test.com", full_name="Profile Test", auth_user_id="p1")
        self.complete_url = '/api/learners/complete_profile/'

    def test_complete_profile_success(self):
        self.client.force_login(self.user)
        data = {
            "phone_number": "1234567890",
            "full_name": "Updated Name"
        }
        response = self.client.post(self.complete_url, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.phone_number, "1234567890")
        self.assertTrue(self.learner.profile_completed)

    def test_complete_profile_unauthorized(self):
        response = self.client.post(self.complete_url, data={})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

class OIDCBackendTests(TestCase):
    def setUp(self):
        from apps.accounts.auth import AuthentikOIDCBackend
        self.backend = AuthentikOIDCBackend()
        self.user = User.objects.create_user(
            username="oidc_user", 
            email="oidc@test.com",
            first_name="First",
            last_name="Last"
        )

    def test_update_user_info_standard(self):
        claims = {
            'sub': 'auth-id-123',
            'email': 'oidc@test.com',
            'given_name': 'NewFirst',
            'family_name': 'NewLast',
            'groups': ['Users']
        }
        self.backend.update_user_info(self.user, claims)
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'NewFirst')
        self.assertEqual(self.user.last_name, 'NewLast')
        self.assertFalse(self.user.is_staff)
        
        learner = Learner.objects.get(email='oidc@test.com')
        self.assertEqual(learner.auth_user_id, 'auth-id-123')
        self.assertEqual(learner.full_name, 'NewFirst NewLast')

    def test_update_user_info_admin(self):
        claims = {
            'sub': 'admin-id-456',
            'email': 'oidc@test.com',
            'groups': ['Admins']
        }
        self.backend.update_user_info(self.user, claims)
        
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)
        self.assertTrue(self.user.is_superuser)
        
        learner = Learner.objects.get(email='oidc@test.com')
        self.assertTrue(learner.is_admin)

class AuthEdgeCaseTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = '/api/auth/login/'
        self.signup_url = '/api/auth/signup/'
        self.logout_url = '/api/auth/logout/'
        self.user = User.objects.create_user(username="edge@test.com", email="edge@test.com")

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, 200)

    @patch('requests.Session')
    @patch('requests.get')
    def test_login_core_api_failure(self, mock_get, mock_session_class):
        # Authentik flow succeeds, but Core API fails to find the user
        mock_session = mock_session_class.return_value
        mock_session.get.return_value.status_code = 200
        mock_session.post.return_value.status_code = 200
        
        mock_get.return_value.status_code = 500 # Simulating failure
        
        login_data = {"email": "fails@test.com", "password": "any"}
        response = self.client.post(self.login_url, data=json.dumps(login_data), content_type='application/json')
        self.assertEqual(response.status_code, 500)
        self.assertIn("Incorrect Password or Username", response.json()['error'])

    @patch('requests.post')
    def test_signup_authentik_creation_failure(self, mock_post):
        # 1. Mock API Token Check
        with patch('django.conf.settings.AUTHENTIK_API_TOKEN', 'token'):
            mock_post.return_value = MagicMock(status_code=400, json=lambda: {"error": "Conflict"})
            
            data = {"email": "fail@test.com", "password": "any", "full_name": "F", "is_admin": False}
            response = self.client.post(self.signup_url, data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 400)

    @patch('requests.post')
    def test_signup_authentik_password_failure(self, mock_post):
        # 1. Create User succeeds, 2. Set Password fails
        with patch('django.conf.settings.AUTHENTIK_API_TOKEN', 'token'):
            mock_post.side_effect = [
                MagicMock(status_code=201, json=lambda: {"pk": 123}),
                MagicMock(status_code=400, text="Weak password")
            ]
            
            data = {"email": "fail_pw@test.com", "password": "any", "full_name": "F", "is_admin": False}
            response = self.client.post(self.signup_url, data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 400)
            self.assertIn("password set failed", response.json()['error'])
