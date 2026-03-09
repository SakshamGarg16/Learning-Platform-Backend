from django.db import models
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt
from .serializers import TrackSerializer, ModuleSerializer, LessonSerializer, AssessmentSerializer, AssessmentAttemptSerializer
from apps.ai_generation.services import generate_track_curriculum, generate_lesson_content, generate_assessment, analyze_assessment_failure
import threading

def background_generate_content(track_id, learner_id):
    """
    Background worker function (Threaded) to pre-generate all lessons 
    in a track for a specific learner.
    """
    try:
        from .models import Track, Lesson, TrackEnrollment, PersonalizedLessonContent
        from apps.accounts.models import Learner
        
        track = Track.objects.get(id=track_id)
        learner = Learner.objects.get(id=learner_id)
        enrollment = TrackEnrollment.objects.filter(track=track, learner=learner).first()
        
        if not enrollment:
            return
            
        summary = enrollment.personalized_summary
        
        # Traverse all modules and lessons
        for module in track.modules.all():
            for lesson in module.lessons.all():
                # Check if already generated
                if PersonalizedLessonContent.objects.filter(lesson=lesson, learner=learner).exists():
                    continue
                    
                print(f"Background generating: {lesson.title} for {learner.email}")
                
                content = generate_lesson_content(
                    track_title=track.title,
                    module_title=module.title,
                    lesson_title=lesson.title,
                    learner_summary=summary
                )
                
                PersonalizedLessonContent.objects.create(
                    lesson=lesson,
                    learner=learner,
                    content=content
                )
    except Exception as e:
        print(f"Background generation error: {e}")

class ModuleViewSet(viewsets.ModelViewSet):
    queryset = Module.objects.all().prefetch_related('lessons', 'assessment')
    serializer_class = ModuleSerializer

class TrackViewSet(viewsets.ModelViewSet):
    serializer_class = TrackSerializer

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return Track.objects.all().order_by('-created_at')
        
        # Only show tracks where the user is either the creator OR an enrolled learner
        return Track.objects.filter(
            models.Q(created_by__email=self.request.user.email) | 
            models.Q(enrollments__learner__email=self.request.user.email)
        ).distinct().order_by('-created_at')

    def get_object(self):
        # Override to allow retrieving a specific track even if not in the default queryset 
        # (critical for the enrollment landing page)
        queryset = Track.objects.all()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        return Track.objects.get(**filter_kwargs)

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
        
        from apps.accounts.models import Learner
        from apps.ai_generation.services import analyze_resume_for_background
        
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
        
        if not learner:
            learner, _ = Learner.objects.get_or_create(
                email="operator@example.com",
                defaults={"full_name": "MVP Operator", "auth_user_id": "mvp_operator"}
            )

        # 1. Structural Personalization: Use resume to influence the syllabus
        learner_summary = None
        if learner.resume:
            try:
                learner_summary = analyze_resume_for_background(learner.resume.path)
            except Exception as e:
                print(f"Background analysis failed for generation: {e}")

        # 2. Ask Gemini to generate track and modules (with background context)
        curriculum_data = generate_track_curriculum(topic, learner_summary)
        if not curriculum_data:
            return Response({"error": "Failed to generate curriculum"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        # 3. Save to database
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
                
            Assessment.objects.create(module=module, title=f"Assessment: {module.title}")

        # 4. Auto-enroll the creator and store the background summary
        from .models import TrackEnrollment
        enrollment, _ = TrackEnrollment.objects.get_or_create(
            learner=learner,
            track=track,
            defaults={"personalized_summary": learner_summary or ""}
        )

        # 5. Immediate Background Pre-generation for all lessons
        threading.Thread(
            target=background_generate_content, 
            args=(track.id, learner.id),
            daemon=True
        ).start()

        serializer = self.get_serializer(track)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        track = self.get_object()
        from apps.accounts.models import Learner
        from .models import TrackEnrollment
        from apps.ai_generation.services import analyze_resume_for_curriculum
        
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)
            
        enrollment, created = TrackEnrollment.objects.get_or_create(
            learner=learner,
            track=track
        )

        # Trigger Personalized Background Analysis
        if created and learner.resume:
            # Prepare curriculum overview
            modules = track.modules.all().prefetch_related('lessons')
            overview = f"Track: {track.title}\nDescription: {track.description}\n"
            for m in modules:
                overview += f"- Module: {m.title}\n"
                for l in m.lessons.all():
                    overview += f"  - Lesson: {l.title}\n"
            
            try:
                summary = analyze_resume_for_curriculum(learner.resume.path, overview)
                enrollment.personalized_summary = summary
                enrollment.save()
                
                # Start pre-generation in background
                threading.Thread(
                    target=background_generate_content, 
                    args=(track.id, learner.id),
                    daemon=True
                ).start()
                
            except Exception as e:
                print(f"Personalization analysis failed: {e}")

        return Response({"status": "enrolled", "created": created})

    @action(detail=True, methods=['get'])
    def enrolled_candidates(self, request, pk=None):
        # Only admins can see who enrolled
        if not request.user.is_staff:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        track = self.get_object()
        from .models import TrackEnrollment
        enrollments = TrackEnrollment.objects.filter(track=track).select_related('learner')
        
        data = []
        for enc in enrollments:
            # Simple progress calculation: (passed assessments / total modules)
            total_modules = track.modules.count()
            passed_assessments = AssessmentAttempt.objects.filter(
                learner=enc.learner,
                assessment__module__track=track,
                passed=True
            ).values('assessment__module').distinct().count()
            
            progress = (passed_assessments / total_modules * 100) if total_modules > 0 else 0
            
            data.append({
                "id": enc.learner.id,
                "name": enc.learner.full_name,
                "email": enc.learner.email,
                "phone": enc.learner.phone_number,
                "resume": enc.learner.resume.url if enc.learner.resume else None,
                "progress": round(progress, 1),
                "enrolled_at": enc.enrolled_at
            })
            
        return Response(data)

    @action(detail=True, methods=['get'], url_path='candidate_dossier/(?P<learner_id>[^/.]+)')
    def candidate_dossier(self, request, pk=None, learner_id=None):
        if not request.user.is_staff:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        track = self.get_object()
        from apps.accounts.models import Learner
        from django.shortcuts import get_object_or_404
        from .models import TrackEnrollment, AssessmentAttempt, PersonalizedLessonContent
        
        learner = get_object_or_404(Learner, id=learner_id)
        enrollment = TrackEnrollment.objects.filter(track=track, learner=learner).first()
        
        if not enrollment:
            return Response({"error": "Learner not enrolled in this track"}, status=status.HTTP_404_NOT_FOUND)
            
        modules_data = []
        for module in track.modules.all():
            lessons_data = []
            for lesson in module.lessons.all():
                pers_content = PersonalizedLessonContent.objects.filter(lesson=lesson, learner=learner).first()
                lessons_data.append({
                    "id": lesson.id,
                    "title": lesson.title,
                    "has_personalized_content": pers_content is not None,
                    "content": pers_content.content if pers_content else lesson.content
                })
            
            assessment = getattr(module, 'assessment', None)
            attempts_data = []
            if assessment:
                attempts = AssessmentAttempt.objects.filter(assessment=assessment, learner=learner).order_by('-created_at')
                for attempt in attempts:
                    attempts_data.append({
                        "id": attempt.id,
                        "score": attempt.score,
                        "passed": attempt.passed,
                        "ai_feedback": attempt.ai_feedback,
                        "answers": attempt.answers_data,
                        "created_at": attempt.created_at
                    })
            
            modules_data.append({
                "id": module.id,
                "title": module.title,
                "lessons": lessons_data,
                "assessment": {
                    "id": assessment.id if assessment else None,
                    "questions": assessment.questions_data if assessment else [],
                    "attempts": attempts_data
                } if assessment else None
            })
            
        return Response({
            "learner": {
                "id": learner.id,
                "name": learner.full_name,
                "email": learner.email,
                "phone": learner.phone_number,
                "resume": learner.resume.url if learner.resume else None,
            },
            "personalized_summary": enrollment.personalized_summary,
            "modules": modules_data
        })


class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer

    @action(detail=True, methods=['post'])
    def generate_content(self, request, pk=None):
        lesson = self.get_object()
        
        # 1. Identify learner and personal summary for focus
        from .models import TrackEnrollment, PersonalizedLessonContent
        from apps.accounts.models import Learner
        
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
            
        learner_summary = None
        enrollment = None
        if learner:
            enrollment = TrackEnrollment.objects.filter(learner=learner, track=lesson.module.track).first()
            if enrollment:
                learner_summary = enrollment.personalized_summary

        # 2. Check if already exists (Manual retry or parallel gen race)
        if learner:
            existing = PersonalizedLessonContent.objects.filter(lesson=lesson, learner=learner).first()
            if existing:
                return Response({"status": "already_exists", "content": existing.content})

        # 3. Generate rigorous, user-specific details
        content = generate_lesson_content(
            track_title=lesson.module.track.title,
            module_title=lesson.module.title,
            lesson_title=lesson.title,
            learner_summary=learner_summary
        )
        
        if learner:
            PersonalizedLessonContent.objects.update_or_create(
                lesson=lesson, 
                learner=learner,
                defaults={"content": content}
            )
        else:
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
        
        # Check for existing attempt to prevent retakes
        existing_attempt = AssessmentAttempt.objects.filter(assessment=assessment, learner=learner).first()
        if existing_attempt:
            return Response(
                {"error": "This assessment has already been completed.", "attempt": AssessmentAttemptSerializer(existing_attempt).data}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
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
