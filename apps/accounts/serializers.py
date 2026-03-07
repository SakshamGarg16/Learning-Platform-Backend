from rest_framework import serializers
from .models import Learner

class LearnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Learner
        fields = ['id', 'email', 'full_name', 'mode', 'experience_level', 'timezone', 'locale', 'created_at']
        read_only_fields = ['id', 'created_at']
