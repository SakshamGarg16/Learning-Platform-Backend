from rest_framework import serializers
from .models import Learner
from apps.curriculum.models import Track, Roadmap

class LearnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Learner
        fields = ['id', 'email', 'full_name', 'phone_number', 'resume', 'mode', 'experience_level', 'timezone', 'locale', 'is_admin', 'profile_completed', 'created_at']
        read_only_fields = ['id', 'created_at']


class PlatformTrackSummarySerializer(serializers.ModelSerializer):
    enrollment_count = serializers.SerializerMethodField()

    class Meta:
        model = Track
        fields = ['id', 'title', 'description', 'created_at', 'is_ai_generated', 'enrollment_count']

    def get_enrollment_count(self, obj):
        return obj.enrollments.count()


class PlatformRoadmapSummarySerializer(serializers.ModelSerializer):
    enrollment_count = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = Roadmap
        fields = ['id', 'title', 'description', 'created_at', 'is_finalized', 'enrollment_count', 'step_count']

    def get_enrollment_count(self, obj):
        return obj.enrollments.count()

    def get_step_count(self, obj):
        return obj.steps.count()


class LearnerDirectorySerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    created_track_count = serializers.SerializerMethodField()
    created_roadmap_count = serializers.SerializerMethodField()

    class Meta:
        model = Learner
        fields = [
            'id', 'email', 'full_name', 'phone_number', 'resume', 'is_admin', 'profile_completed',
            'experience_level', 'created_at', 'role', 'created_track_count', 'created_roadmap_count'
        ]

    def get_role(self, obj):
        return 'admin' if obj.is_admin else 'learner'

    def get_created_track_count(self, obj):
        return obj.created_tracks.count()

    def get_created_roadmap_count(self, obj):
        return obj.created_roadmaps.count()


class LearnerPlatformDetailSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    created_tracks = PlatformTrackSummarySerializer(many=True, read_only=True)
    created_roadmaps = PlatformRoadmapSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Learner
        fields = [
            'id', 'email', 'full_name', 'phone_number', 'resume', 'mode', 'experience_level',
            'timezone', 'locale', 'is_admin', 'profile_completed', 'created_at', 'updated_at',
            'role', 'created_tracks', 'created_roadmaps'
        ]

    def get_role(self, obj):
        return 'admin' if obj.is_admin else 'learner'

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField()
    is_admin = serializers.BooleanField(default=False)
