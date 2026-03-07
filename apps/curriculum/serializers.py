from rest_framework import serializers
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt

class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'title', 'content', 'order']


class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assessment
        fields = ['id', 'title', 'questions_data']


class ModuleSerializer(serializers.ModelSerializer):
    lessons = LessonSerializer(many=True, read_only=True)
    assessment = AssessmentSerializer(read_only=True)
    is_unlocked = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    
    class Meta:
        model = Module
        fields = ['id', 'title', 'description', 'order', 'is_remedial', 'lessons', 'assessment', 'is_unlocked', 'is_completed']

    def get_is_unlocked(self, obj):
        request = self.context.get('request')
        
        # Determine learner fallback (same logic as views)
        from apps.accounts.models import Learner
        learner = None
        if request and request.user.is_authenticated:
            learner = Learner.objects.filter(email=request.user.email).first()
        
        if not learner:
            # Fallback for MVP local environments
            learner = Learner.objects.filter(email="operator@example.com").first()

        # 1. First module always unlocked for everyone
        if obj.order == 0:
            return True

        # 2. Remedial modules only unlocked for the target learner
        if obj.is_remedial:
            if not learner: return False
            return obj.remedial_for_learner == learner

        # 3. Module N is unlocked if Assessment for Module with order N-1 is passed
        previous_module = Module.objects.filter(track=obj.track, order=obj.order - 1).first()
        if not previous_module:
            return True 
            
        return AssessmentAttempt.objects.filter(
            learner=learner, 
            assessment__module=previous_module, 
            passed=True
        ).exists() if learner else False

    def get_is_completed(self, obj):
        request = self.context.get('request')
        from apps.accounts.models import Learner
        learner = None
        if request and request.user.is_authenticated:
            learner = Learner.objects.filter(email=request.user.email).first()
        
        if not learner:
            learner = Learner.objects.filter(email="operator@example.com").first()
            
        if not learner:
            return False
            
        return AssessmentAttempt.objects.filter(
            learner=learner, 
            assessment__module=obj, 
            passed=True
        ).exists()


class TrackSerializer(serializers.ModelSerializer):
    modules = ModuleSerializer(many=True, read_only=True)
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Track
        fields = ['id', 'title', 'description', 'is_ai_generated', 'original_topic', 'created_at', 'modules', 'progress_percentage']

    def get_progress_percentage(self, obj):
        request = self.context.get('request')
        from apps.accounts.models import Learner
        learner = None
        if request and request.user.is_authenticated:
            learner = Learner.objects.filter(email=request.user.email).first()
        
        if not learner:
            learner = Learner.objects.filter(email="operator@example.com").first()

        if not learner:
            return 0
            
        total_modules = obj.modules.count()
        if total_modules == 0:
            return 0
            
        completed_count = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module__track=obj,
            passed=True
        ).values('assessment__module').distinct().count()
        
        return round((completed_count / total_modules) * 100)


class AssessmentAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentAttempt
        fields = ['id', 'learner', 'assessment', 'answers_data', 'score', 'passed', 'ai_feedback', 'remedial_module_generated']
        read_only_fields = ['score', 'passed', 'ai_feedback', 'remedial_module_generated']
