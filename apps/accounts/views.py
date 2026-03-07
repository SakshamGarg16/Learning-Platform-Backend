from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Learner
from .serializers import LearnerSerializer

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
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return Response({"error": "Learner not found"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = LearnerSerializer(learner, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(profile_completed=True)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
