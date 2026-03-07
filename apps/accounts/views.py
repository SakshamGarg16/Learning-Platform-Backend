from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Learner
from .serializers import LearnerSerializer

class LearnerViewSet(viewsets.ModelViewSet):
    queryset = Learner.objects.all()
    serializer_class = LearnerSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
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
        return Response(data)
