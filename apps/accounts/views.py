from rest_framework import viewsets
from .models import Learner
from .serializers import LearnerSerializer

class LearnerViewSet(viewsets.ModelViewSet):
    queryset = Learner.objects.all()
    serializer_class = LearnerSerializer
