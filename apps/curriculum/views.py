from django.db import models
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt
from .serializers import TrackSerializer, ModuleSerializer, LessonSerializer, AssessmentSerializer, AssessmentAttemptSerializer
from apps.ai_generation.services import generate_track_curriculum, generate_lesson_content, generate_assessment, analyze_assessment_failure

class ModuleViewSet(viewsets.ModelViewSet):
    queryset = Module.objects.all().prefetch_related('lessons', 'assessment')
    serializer_class = ModuleSerializer

class TrackViewSet(viewsets.ModelViewSet):
    serializer_class = TrackSerializer

    def get_queryset(self):
        # In MVP, show tracks created by this user or "admin" (shared)
        # For now, since we have the operator fallback logic, we use that email
        if self.request.user.is_anonymous:
            # Fallback for local development/mock
            return Track.objects.all()
        
        # In a real system, we'd filter by user.learner_profile.
        # Let's mirror the fallback logic from Agents for consistency
        return Track.objects.filter(
            models.Q(created_by__email=self.request.user.email) | 
            models.Q(created_by__email="admin@example.com")
        )

    def perform_create(self, serializer):
        from apps.accounts.models import Learner
        
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
            
        if not learner:
            learner, _ = Learner.objects.get_or_create(
                email="operator@example.com",
                defaults={"full_name": "MVP Operator", "auth_user_id": "mvp_operator"}
            )
            
        serializer.save(created_by=learner)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        topic = request.data.get('topic')
        if not topic:
            return Response({"error": "Topic is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 1. Ask Gemini to generate track and modules
        curriculum_data = generate_track_curriculum(topic)
        if not curriculum_data:
            return Response({"error": "Failed to generate curriculum"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        # 2. Save to database
        from apps.accounts.models import Learner
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
        
        if not learner:
            learner, _ = Learner.objects.get_or_create(
                email="operator@example.com",
                defaults={"full_name": "MVP Operator", "auth_user_id": "mvp_operator"}
            )

        track = Track.objects.create(
            title=curriculum_data.get('title', f"{topic} Track"),
            description=curriculum_data.get('description', ""),
            is_ai_generated=True,
            original_topic=topic,
            created_by=learner
        )
        
        for m_idx, module_data in enumerate(curriculum_data.get('modules', [])):
            module = Module.objects.create(
                track=track,
                title=module_data.get('title', f"Module {m_idx+1}"),
                description=module_data.get('description', ""),
                order=m_idx
            )
            
            for l_idx, lesson_data in enumerate(module_data.get('lessons', [])):
                Lesson.objects.create(
                    module=module,
                    title=lesson_data.get('title', f"Lesson {l_idx+1}"),
                    order=l_idx
                )
                
            # Create a stub assessment that can be populated later
            Assessment.objects.create(module=module, title=f"Assessment: {module.title}")
            
        serializer = self.get_serializer(track)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer

    @action(detail=True, methods=['post'])
    def generate_content(self, request, pk=None):
        lesson = self.get_object()
        
        # Generate rigorous details
        content = generate_lesson_content(
            track_title=lesson.module.track.title,
            module_title=lesson.module.title,
            lesson_title=lesson.title
        )
        
        lesson.content = content
        lesson.save()
        return Response({"status": "generated", "content": content})


class AssessmentViewSet(viewsets.ModelViewSet):
    queryset = Assessment.objects.all()
    serializer_class = AssessmentSerializer

    @action(detail=True, methods=['post'])
    def generate_questions(self, request, pk=None):
        assessment = self.get_object()
        
        questions = generate_assessment(
            module_title=assessment.module.title,
            track_title=assessment.module.track.title
        )
        
        assessment.questions_data = questions
        assessment.save()
        return Response(self.get_serializer(assessment).data)

    @action(detail=True, methods=['post'])
    def submit_attempt(self, request, pk=None):
        assessment = self.get_object()
        user_answers = request.data.get('answers', {})
        # Note: In reality, we'd fetch learner from request.user, but mocked for MVP
        from apps.accounts.models import Learner
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
        
        if not learner:
            # Check for passed ID, or use operator fallback
            learner_id = request.data.get('learner_id')
            if learner_id:
                learner = Learner.objects.filter(id=learner_id).first()
            
            if not learner:
                learner, _ = Learner.objects.get_or_create(
                    email="operator@example.com",
                    defaults={"full_name": "MVP Operator", "auth_user_id": "mvp_operator"}
                )
        
        learner_id = learner.id
            
        questions = assessment.questions_data
        correct_count = 0
        total = len(questions)
        
        # Advanced Polymorphic Grading
        for idx, q in enumerate(questions):
            user_val = user_answers.get(str(idx))
            
            # Support legacy 'correct_index' and new 'correct_answer' list
            correct_set = set(map(str, q.get('correct_answer', [q.get('correct_index')])))
            
            if q.get('type') == 'multi_select':
                # For multi-select, user_val should be a list of indices
                user_set = set(map(str, user_val if isinstance(user_val, list) else [user_val] if user_val is not None else []))
                if user_set == correct_set:
                    correct_count += 1
            else:
                # For mcq/boolean, user_val is a single index or a list with one item
                if isinstance(user_val, list):
                    user_val = user_val[0] if user_val else None
                    
                if str(user_val) in correct_set and len(correct_set) == 1:
                    correct_count += 1
                elif str(user_val) == str(q.get('correct_index')): # Legacy fallback
                    correct_count += 1
                
        score = (correct_count / total * 100) if total > 0 else 0
        passed = score >= 70
        
        attempt = AssessmentAttempt.objects.create(
            learner_id=learner_id,
            assessment=assessment,
            answers_data=user_answers,
            score=score,
            passed=passed
        )
        
        if not passed:
            # Shift all subsequent modules up by 1 to make room for remedial
            Module.objects.filter(
                track=assessment.module.track, 
                order__gt=assessment.module.order
            ).update(order=models.F('order') + 1)

            # Generate remedial module natively
            analysis = analyze_assessment_failure(assessment.module.title, questions, user_answers)
            attempt.ai_feedback = analysis.get('feedback', "")
            
            remedial_data = analysis.get('remedial_module')
            if remedial_data:
                rem_module = Module.objects.create(
                    track=assessment.module.track,
                    title=remedial_data.get('title', "Remedial Module"),
                    description=remedial_data.get('description', ""),
                    order=assessment.module.order + 1, # Place immediately after current
                    is_remedial=True,
                    remedial_for_learner=learner
                )
                
                for l_idx, less in enumerate(remedial_data.get('lessons', [])):
                    Lesson.objects.create(
                        module=rem_module,
                        title=less.get('title', "Remedial Lesson"),
                        order=l_idx
                    )
                
                Assessment.objects.create(module=rem_module, title=f"Remedial Assessment: {rem_module.title}")
                attempt.remedial_module_generated = rem_module
            
        attempt.save()
        
        serializer = AssessmentAttemptSerializer(attempt)
        return Response(serializer.data)
