from rest_framework import serializers
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt, Roadmap, RoadmapStep, RoadmapEnrollment

class LessonSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()
    
    class Meta:
        model = Lesson
        fields = ['id', 'title', 'content', 'order']

    def get_content(self, obj):
        request = self.context.get('request')
        if not request or request.user.is_anonymous:
            return obj.content
            
        from apps.accounts.models import Learner
        from .models import PersonalizedLessonContent
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return obj.content
            
        pers = PersonalizedLessonContent.objects.filter(lesson=obj, learner=learner).first()
        return pers.content if pers else obj.content


class AssessmentAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentAttempt
        fields = ['id', 'learner', 'assessment', 'answers_data', 'score', 'passed', 'ai_feedback', 'remedial_module_generated', 'created_at']
        read_only_fields = ['score', 'passed', 'ai_feedback', 'remedial_module_generated', 'created_at']


class AssessmentSerializer(serializers.ModelSerializer):
    user_latest_attempt = serializers.SerializerMethodField()
    
    class Meta:
        model = Assessment
        fields = ['id', 'title', 'questions_data', 'user_latest_attempt']

    def get_user_latest_attempt(self, obj):
        request = self.context.get('request')
        if not request or request.user.is_anonymous:
            return None
            
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            # Fallback for MVP local environments
            learner = Learner.objects.filter(email="operator@example.com").first()
            
        if not learner:
            return None
            
        attempt = AssessmentAttempt.objects.filter(assessment=obj, learner=learner).order_by('-created_at').first()
        if attempt:
            return AssessmentAttemptSerializer(attempt).data
        return None


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

        # 0. Admins have full access
        if (learner and learner.is_admin) or (request and request.user.is_staff):
            return True

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
    is_enrolled = serializers.SerializerMethodField()
    is_creator = serializers.SerializerMethodField()

    class Meta:
        model = Track
        fields = ['id', 'title', 'description', 'is_ai_generated', 'original_topic', 'created_at', 'modules', 'progress_percentage', 'is_enrolled', 'is_creator']

    def get_is_creator(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.created_by and obj.created_by.email == request.user.email

    def get_is_enrolled(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
            
        from apps.accounts.models import Learner
        from .models import TrackEnrollment
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return False
        
        # If you are the creator or admin, you never need to "enroll"
        if obj.created_by == learner or (request and request.user.is_staff):
            return True
            
        return TrackEnrollment.objects.filter(track=obj, learner=learner).exists()

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


class RoadmapStepSerializer(serializers.ModelSerializer):
    track = TrackSerializer(read_only=True)
    is_unlocked = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()

    class Meta:
        model = RoadmapStep
        fields = ['id', 'title', 'description', 'order', 'track', 'is_unlocked', 'is_completed']

    def get_is_unlocked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return obj.order == 0
        
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            learner = Learner.objects.filter(email="operator@example.com").first()
            
        if (learner and learner.is_admin) or (request and request.user.is_staff):
            return True

        if obj.order == 0:
            return True
        
        # Unlocked if previous step track is completed
        prev_step = RoadmapStep.objects.filter(roadmap=obj.roadmap, order=obj.order - 1).first()
        if not prev_step:
            return True
        
        if not prev_step.track:
            return False
            
        # Check if learner completed all modules in the previous track
        total_modules = prev_step.track.modules.count()
        if total_modules == 0: return True
        
        completed_count = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module__track=prev_step.track,
            passed=True
        ).values('assessment__module').distinct().count()
        
        return completed_count >= total_modules

    def get_is_completed(self, obj):
        if not obj.track: return False
        request = self.context.get('request')
        from apps.accounts.models import Learner
        learner = None
        if request and request.user.is_authenticated:
            learner = Learner.objects.filter(email=request.user.email).first()
        
        if not learner:
            learner = Learner.objects.filter(email="operator@example.com").first()
        
        if not learner: return False
        
        total_modules = obj.track.modules.count()
        if total_modules == 0: return False
        
        completed_count = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module__track=obj.track,
            passed=True
        ).values('assessment__module').distinct().count()
        
        return completed_count >= total_modules


class RoadmapSerializer(serializers.ModelSerializer):
    steps = RoadmapStepSerializer(many=True, read_only=True)
    is_enrolled = serializers.SerializerMethodField()

    class Meta:
        model = Roadmap
        fields = ['id', 'title', 'description', 'created_at', 'steps', 'is_enrolled', 'is_finalized']

    def get_is_enrolled(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
            
        from apps.accounts.models import Learner
        from .models import RoadmapEnrollment
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return False
            
        return RoadmapEnrollment.objects.filter(roadmap=obj, learner=learner).exists()


class RoadmapEnrollmentSerializer(serializers.ModelSerializer):
    roadmap = RoadmapSerializer(read_only=True)

    class Meta:
        model = RoadmapEnrollment
        fields = ['id', 'roadmap', 'enrolled_at']
