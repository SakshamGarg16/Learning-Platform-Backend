import requests
from django.conf import settings
from django.contrib.auth import login as django_login, logout as django_logout
from django.contrib.auth.models import User
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Learner
from .serializers import LearnerSerializer, LoginSerializer, SignupSerializer

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class LearnerViewSet(viewsets.ModelViewSet):
    queryset = Learner.objects.all()
    serializer_class = LearnerSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        from django.middleware.csrf import get_token
        # Ensure the CSRF cookie is set
        get_token(request)
        
        if not request.user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)
            
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            learner = Learner.objects.create(
                email=request.user.email,
                full_name=request.user.get_full_name() or request.user.email
            )
            
        data = LearnerSerializer(learner).data
        data['is_admin'] = request.user.is_staff
        data['profile_completed'] = learner.profile_completed
        data['csrf_token'] = get_token(request)
        return Response(data)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def complete_profile(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
            
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return Response({"error": "Learner not found"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = LearnerSerializer(learner, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(profile_completed=True)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AuthViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        
        # Flow-based Authentication (The most reliable way for headless Authentik)
        authentik_url = settings.AUTHENTIK_BASE_URL.rstrip('/')
        session = requests.Session()
        flow_url = f"{authentik_url}/api/v3/flows/executor/default-authentication-flow/"
        
        try:
            print(f"DEBUG: Starting Authentik Flow Auth for {email}")
            
            # 1. Initialize Flow
            session.get(flow_url)
            
            # 2. Identification Stage
            id_resp = session.post(flow_url, json={"uid_field": email})
            if id_resp.status_code != 200:
                print(f"DEBUG: Identification Failed: {id_resp.text}")
                return Response({"error": "User not found or identification failed"}, status=status.HTTP_401_UNAUTHORIZED)
            
            # 3. Password Stage
            pw_resp = session.post(flow_url, json={"password": password})
            if pw_resp.status_code != 200:
                print(f"DEBUG: Password Failed: {pw_resp.text}")
                return Response({"error": "Invalid credentials", "details": "Password rejected by Authentik"}, status=status.HTTP_401_UNAUTHORIZED)
            
            print(f"DEBUG: Authentik Flow Success for {email}")
            
            # 4. Successful Auth - Now fetch user details from Core API using Admin Token
            headers = {'Authorization': f"Bearer {settings.AUTHENTIK_API_TOKEN}"}
            user_api_url = f"{authentik_url}/api/v3/core/users/?email={email}"
            user_data_resp = requests.get(user_api_url, headers=headers)
            
            if user_data_resp.status_code != 200 or not user_data_resp.json().get('results'):
                return Response({"error": "Incorrect Password or Username! Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            ak_user = user_data_resp.json()['results'][0]
            
            # Step 5: Sync to Django
            user, created = User.objects.get_or_create(email=email, defaults={'username': email})
            user.first_name = ak_user.get('name', '').split(' ')[0] if ak_user.get('name') else ''
            user.last_name = ' '.join(ak_user.get('name', '').split(' ')[1:]) if ak_user.get('name') and ' ' in ak_user.get('name') else ''
            
            learner, l_created = Learner.objects.get_or_create(email=email)
            
            # Handle Groups/Admin status
            # We can use our existing is_admin field or fetch groups from Authentik
            if ak_user.get('is_superuser') or learner.is_admin:
                user.is_staff = True
                user.is_superuser = True
                learner.is_admin = True
            
            user.save()
            learner.auth_user_id = str(ak_user.get('pk'))
            learner.full_name = ak_user.get('name') or user.email
            learner.save()
            
            # Log into Django session
            django_login(request, user, backend='apps.accounts.auth.AuthentikOIDCBackend')
            
            return Response({"status": "success", "user": email})
            
        except Exception as e:
            print(f"DEBUG: Login Exception: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def signup(self, request):
        serializer = SignupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        full_name = serializer.validated_data['full_name']
        is_admin = serializer.validated_data['is_admin']
        
        # Create user in Authentik via Core API
        api_token = getattr(settings, 'AUTHENTIK_API_TOKEN', None)
        if not api_token:
            return Response({"error": "Authentik API token not configured in backend settings"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        create_user_url = f"{settings.AUTHENTIK_BASE_URL}/api/v3/core/users/"
        headers = {
            'Authorization': f"Bearer {api_token}",
            'Content-Type': 'application/json'
        }
        
        user_data = {
            'username': email,
            'name': full_name,
            'email': email,
            'path': 'users',
        }
        
        try:
            # 1. Create User
            response = requests.post(create_user_url, headers=headers, json=user_data)
            if response.status_code != 201:
                return Response(response.json(), status=response.status_code)
                
            authentik_user = response.json()
            user_pk = authentik_user['pk']
            
            # 2. Set Password
            password_url = f"{settings.AUTHENTIK_BASE_URL}/api/v3/core/users/{user_pk}/set_password/"
            pw_response = requests.post(password_url, headers=headers, json={'password': password})
            if pw_response.status_code != 204:
                return Response({"error": f"User created but password set failed: {pw_response.text}"}, status=400)
            
            # 3. Create locally in Django
            user, created = User.objects.get_or_create(email=email, defaults={'username': email})
            user.is_staff = is_admin
            user.is_superuser = is_admin
            user.save()
            
            # 4. Create Learner profile
            Learner.objects.update_or_create(
                email=email,
                defaults={
                    'full_name': full_name,
                    'auth_user_id': str(user_pk),
                    'is_admin': is_admin
                }
            )
            
            return Response({"message": "Account created successfully. Please log in."}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def logout(self, request):
        django_logout(request)
        return Response({"status": "success"})
