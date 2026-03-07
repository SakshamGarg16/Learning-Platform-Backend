from rest_framework import serializers
from .models import MentorReview, PeerReview, ReadinessSnapshot

class MentorReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = MentorReview
        fields = '__all__'


class PeerReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeerReview
        fields = '__all__'


class ReadinessSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadinessSnapshot
        fields = '__all__'
