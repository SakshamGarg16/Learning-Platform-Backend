from rest_framework import serializers
from .models import Learner

class LearnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Learner
        fields = ['id', 'email', 'full_name', 'phone_number', 'resume', 'mode', 'experience_level', 'timezone', 'locale', 'is_admin', 'profile_completed', 'created_at']
        read_only_fields = ['id', 'created_at']

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField()
    is_admin = serializers.BooleanField(default=False)
