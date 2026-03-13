from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import (
    Track,
    Module,
    Lesson,
    Assessment,
    AssessmentAttempt,
    Roadmap,
    RoadmapStep,
    RoadmapEnrollment,
    FinalAssessment,
    FinalAssessmentAttempt,
    Certificate,
)
from .serializers import (
    TrackSerializer,
    ModuleSerializer,
    LessonSerializer,
    AssessmentSerializer,
    AssessmentAttemptSerializer,
    RoadmapSerializer,
    RoadmapStepSerializer,
    RoadmapEnrollmentSerializer,
    FinalAssessmentSerializer,
    FinalAssessmentAttemptSerializer,
)
from apps.ai_generation.services import (
    generate_track_curriculum,
    generate_lesson_content,
    analyze_assessment_failure,
    generate_final_assessment_questions,
)
import threading
import uuid

SUPER_ADMIN_EMAIL = "admin@remlearner.com"


def _calculate_track_progress(track, learner):
    total_modules = track.modules.count()
    if total_modules == 0:
        return 0.0

    passed_assessments = AssessmentAttempt.objects.filter(
        learner=learner,
        assessment__module__track=track,
        passed=True
    ).values('assessment__module').distinct().count()

    return round((passed_assessments / total_modules) * 100, 1)


def _calculate_roadmap_progress(roadmap, learner):
    finalized_tracks = Track.objects.filter(roadmap_steps__roadmap=roadmap).distinct()
    total_modules = Module.objects.filter(track__in=finalized_tracks).count()
    if total_modules == 0:
        return 0.0

    passed_assessments = AssessmentAttempt.objects.filter(
        learner=learner,
        assessment__module__track__in=finalized_tracks,
        passed=True
    ).values('assessment__module').distinct().count()

    return round((passed_assessments / total_modules) * 100, 1)


def _get_current_module_summary(track, learner):
    modules = list(track.modules.all().order_by('order'))
    if not modules:
        return None

    for module in modules:
        is_completed = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module=module,
            passed=True
        ).exists()

        if not is_completed:
            return {
                "id": module.id,
                "title": module.title,
                "order": module.order,
                "status": "in_progress",
            }

    last_module = modules[-1]
    return {
        "id": last_module.id,
        "title": last_module.title,
        "order": last_module.order,
        "status": "completed",
    }


def _get_roadmap_current_focus(roadmap, learner):
    ordered_steps = roadmap.steps.all().order_by('order')
    last_completed_focus = None

    for step in ordered_steps:
        if not step.track:
            continue

        progress = _calculate_track_progress(step.track, learner)
        current_module = _get_current_module_summary(step.track, learner)
        focus = {
            "step_id": step.id,
            "step_title": step.title,
            "track_id": step.track.id,
            "track_title": step.track.title,
            "progress": progress,
            "current_module": current_module,
        }

        if progress < 100.0:
            return focus

        last_completed_focus = focus

    return last_completed_focus


def _get_request_learner(request):
    from apps.accounts.models import Learner

    learner = None
    if not request.user.is_anonymous:
        learner = Learner.objects.filter(email=request.user.email).first()

    if not learner:
        learner = Learner.objects.filter(email="operator@example.com").first()

    return learner


def _grade_questions(questions, user_answers):
    correct_count = 0
    total = len(questions)

    for idx, q in enumerate(questions):
        user_val = user_answers.get(str(idx))
        correct_set = set(map(str, q.get('correct_answer', [q.get('correct_index')])))

        if q.get('type') == 'multi_select':
            user_set = set(map(str, user_val if isinstance(user_val, list) else [user_val] if user_val is not None else []))
            if user_set == correct_set:
                correct_count += 1
        else:
            if isinstance(user_val, list):
                user_val = user_val[0] if user_val else None

            if str(user_val) in correct_set and len(correct_set) == 1:
                correct_count += 1
            elif str(user_val) == str(q.get('correct_index')):
                correct_count += 1

    score = (correct_count / total * 100) if total > 0 else 0
    return round(score, 1)


def _build_track_final_assessment(track):
    module_titles = list(track.modules.order_by('order').values_list('title', flat=True))
    generated = generate_final_assessment_questions(
        scope_type="track",
        title=track.title,
        description=track.description,
        outline_items=module_titles,
    )
    if not generated:
        return None

    final_assessment, _ = FinalAssessment.objects.update_or_create(
        track=track,
        defaults={
            "title": generated.get("title", f"{track.title} Final Evaluation"),
            "description": generated.get("description", track.description),
            "questions_data": generated.get("questions", []),
            "passing_score": generated.get("passing_score", 85),
            "time_limit_minutes": generated.get("time_limit_minutes", 60),
        }
    )
    return final_assessment


def _build_roadmap_final_assessment(roadmap):
    outline_items = []
    for step in roadmap.steps.all().order_by('order'):
        if step.track:
            outline_items.extend(
                list(step.track.modules.order_by('order').values_list('title', flat=True))
            )
        else:
            outline_items.append(step.title)

    generated = generate_final_assessment_questions(
        scope_type="roadmap",
        title=roadmap.title,
        description=roadmap.description,
        outline_items=outline_items,
    )
    if not generated:
        return None

    final_assessment, _ = FinalAssessment.objects.update_or_create(
        roadmap=roadmap,
        defaults={
            "title": generated.get("title", f"{roadmap.title} Final Evaluation"),
            "description": generated.get("description", roadmap.description),
            "questions_data": generated.get("questions", []),
            "passing_score": generated.get("passing_score", 85),
            "time_limit_minutes": generated.get("time_limit_minutes", 75),
        }
    )
    return final_assessment


def _issue_certificate(learner, final_attempt):
    final_assessment = final_attempt.final_assessment
    defaults = {
        "final_assessment_attempt": final_attempt,
        "certificate_code": uuid.uuid4().hex[:16].upper(),
        "track": final_assessment.track,
        "roadmap": final_assessment.roadmap,
    }
    certificate, _ = Certificate.objects.get_or_create(
        learner=learner,
        track=final_assessment.track,
        roadmap=final_assessment.roadmap,
        defaults=defaults,
    )
    if certificate.final_assessment_attempt_id != final_attempt.id:
        certificate.final_assessment_attempt = final_attempt
        certificate.save(update_fields=["final_assessment_attempt"])
    return certificate

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
        
        # Traverse all modules
        from apps.ai_generation.langgraph_workflows import module_generator_app
        
        for module in track.modules.all():
            lessons_to_generate = []
            for lesson in module.lessons.all():
                # Check if already generated
                if not PersonalizedLessonContent.objects.filter(lesson=lesson, learner=learner).exists():
                    lessons_to_generate.append({"id": str(lesson.id), "title": lesson.title})
                    
            assessment = getattr(module, 'assessment', None)
            needs_assessment = True if assessment and not assessment.questions_data else False
            
            if lessons_to_generate or needs_assessment:
                print(f"Background generating (LangGraph) for module map: {module.title} / {learner.email}")
                
                initial_state = {
                    "learner_id": str(learner.id),
                    "track_id": str(track.id),
                    "module_id": str(module.id),
                    "track_title": track.title,
                    "module_title": module.title,
                    "learner_summary": summary,
                    "needs_assessment": needs_assessment,
                    "lessons_to_generate": lessons_to_generate,
                    "generated_lessons": [],
                    "assessment_questions": []
                }
                
                module_generator_app.invoke(initial_state)
    except Exception as e:
        print(f"Background generation error: {e}")

def background_finalize_roadmap(roadmap_id, learner_id):
    """
    Background worker to generate all tracks/modules for a roadmap.
    Also triggers personalization for any enrolled learners.
    """
    try:
        from .models import Roadmap, RoadmapStep, Track, Module, Lesson, Assessment, TrackEnrollment
        from apps.accounts.models import Learner
        from apps.ai_generation.services import generate_track_curriculum, analyze_resume_for_background

        roadmap = Roadmap.objects.get(id=roadmap_id)
        creator = Learner.objects.get(id=learner_id)
        
        for step in roadmap.steps.filter(track__isnull=True).order_by('order'):
            topic = step.title
            print(f"Background Finalizing Step: {topic}")
            
            curriculum_data = generate_track_curriculum(topic, None)
            if curriculum_data:
                track = Track.objects.create(
                    title=curriculum_data.get('title', topic),
                    description=curriculum_data.get('description', step.description),
                    is_ai_generated=True,
                    original_topic=topic,
                    created_by=creator
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
                
                step.track = track
                step.save()
                
                # Now trigger personalization for all people enrolled in this roadmap
                for rd_enroll in roadmap.enrollments.all():
                    # Create track enrollment if not exists
                    learner = rd_enroll.learner
                    learner_summary = None
                    if learner.resume:
                        try:
                            # Try to get existing summary or analyze
                            existing_enroll = TrackEnrollment.objects.filter(learner=learner).exclude(personalized_summary__isnull=True).first()
                            if existing_enroll:
                                learner_summary = existing_enroll.personalized_summary
                            else:
                                learner_summary = analyze_resume_for_background(learner.resume.path)
                        except: pass

                    TrackEnrollment.objects.get_or_create(
                        learner=learner,
                        track=track,
                        defaults={'personalized_summary': learner_summary}
                    )
                    # Pre-generate content
                    threading.Thread(
                        target=background_generate_content, 
                        args=(track.id, learner.id),
                        daemon=True
                    ).start()

                # Also trigger for the creator (Admin review mode)
                TrackEnrollment.objects.get_or_create(
                    learner=creator,
                    track=track,
                    defaults={'personalized_summary': "Administrator review mode. Generate comprehensive technical content for the general audience."}
                )
                threading.Thread(
                    target=background_generate_content, 
                    args=(track.id, creator.id),
                    daemon=True
                ).start()
                    
                print(f"Finalized Step: {topic} -> Track: {track.id}")
                
    except Exception as e:
        print(f"Error in background_finalize_roadmap: {e}")

class ModuleViewSet(viewsets.ModelViewSet):
    queryset = Module.objects.all().prefetch_related('lessons', 'assessment')
    serializer_class = ModuleSerializer

class TrackViewSet(viewsets.ModelViewSet):
    serializer_class = TrackSerializer

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return Track.objects.all().order_by('-created_at')
        
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=self.request.user.email).first()

        if self.request.user.email == SUPER_ADMIN_EMAIL:
            return Track.objects.all().order_by('-created_at')

        # Tracks are private to their creator and enrolled learners.
        return Track.objects.filter(
            models.Q(created_by=learner) | 
            models.Q(enrollments__learner=learner) |
            models.Q(created_by__email=SUPER_ADMIN_EMAIL)
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
    def final_assessment(self, request, pk=None):
        track = self.get_object()
        learner = _get_request_learner(request)
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        total_modules = track.modules.count()
        completed_modules = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module__track=track,
            passed=True
        ).values('assessment__module').distinct().count()

        if total_modules == 0 or completed_modules < total_modules:
            return Response({
                "available": False,
                "completed_modules": completed_modules,
                "total_modules": total_modules,
                "error": "Complete every module assessment before attempting the final evaluation."
            }, status=status.HTTP_200_OK)

        final_assessment = getattr(track, 'final_assessment', None)
        if not final_assessment or not final_assessment.questions_data:
            final_assessment = _build_track_final_assessment(track)

        if not final_assessment:
            return Response({"error": "Failed to prepare final assessment"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "available": True,
            "assessment": FinalAssessmentSerializer(final_assessment, context={"request": request}).data
        })

    @action(detail=True, methods=['post'])
    def submit_final_assessment(self, request, pk=None):
        track = self.get_object()
        learner = _get_request_learner(request)
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        final_assessment = getattr(track, 'final_assessment', None)
        if not final_assessment:
            return Response({"error": "Final assessment not ready"}, status=status.HTTP_400_BAD_REQUEST)

        existing_attempt = FinalAssessmentAttempt.objects.filter(
            final_assessment=final_assessment,
            learner=learner
        ).first()
        if existing_attempt:
            return Response(
                {
                    "error": "This final assessment has already been completed.",
                    "attempt": FinalAssessmentAttemptSerializer(existing_attempt).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        answers = request.data.get('answers', {})
        integrity_flags = request.data.get('integrity_flags', {}) or {}
        violation_detected = any([
            integrity_flags.get('tab_switch_count', 0) > 0,
            integrity_flags.get('fullscreen_exit_count', 0) > 0,
            integrity_flags.get('context_menu_count', 0) > 0,
        ])

        score = 0.0 if violation_detected else _grade_questions(final_assessment.questions_data, answers)
        passed = (not violation_detected) and score >= final_assessment.passing_score
        terminated_reason = "Integrity violation detected during proctored final evaluation." if violation_detected else ""

        attempt = FinalAssessmentAttempt.objects.create(
            learner=learner,
            final_assessment=final_assessment,
            answers_data=answers,
            integrity_flags=integrity_flags,
            score=score,
            passed=passed,
            terminated_reason=terminated_reason,
        )

        if passed:
            _issue_certificate(learner, attempt)

        return Response(FinalAssessmentAttemptSerializer(attempt).data)

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
            data.append({
                "id": enc.learner.id,
                "name": enc.learner.full_name,
                "email": enc.learner.email,
                "phone": enc.learner.phone_number,
                "resume": enc.learner.resume.url if enc.learner.resume else None,
                "progress": _calculate_track_progress(track, enc.learner),
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

        final_assessment_data = None
        final_assessment = getattr(track, 'final_assessment', None)
        if final_assessment:
            final_attempts = FinalAssessmentAttempt.objects.filter(
                final_assessment=final_assessment,
                learner=learner
            ).order_by('-created_at')

            attempts_data = []
            for attempt in final_attempts:
                certificate = getattr(attempt, 'certificate', None)
                attempts_data.append({
                    "id": attempt.id,
                    "score": attempt.score,
                    "passed": attempt.passed,
                    "answers": attempt.answers_data,
                    "integrity_flags": attempt.integrity_flags,
                    "terminated_reason": attempt.terminated_reason,
                    "certificate": {
                        "id": certificate.id,
                        "certificate_code": certificate.certificate_code,
                        "issued_at": certificate.issued_at,
                    } if certificate else None,
                    "created_at": attempt.created_at,
                })

            final_assessment_data = {
                "id": final_assessment.id,
                "title": final_assessment.title,
                "description": final_assessment.description,
                "passing_score": final_assessment.passing_score,
                "time_limit_minutes": final_assessment.time_limit_minutes,
                "questions": final_assessment.questions_data,
                "attempt_count": final_attempts.count(),
                "attempts": attempts_data,
            }
            
        return Response({
            "learner": {
                "id": learner.id,
                "name": learner.full_name,
                "email": learner.email,
                "phone": learner.phone_number,
                "resume": learner.resume.url if learner.resume else None,
            },
            "personalized_summary": enrollment.personalized_summary,
            "modules": modules_data,
            "final_assessment": final_assessment_data,
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
        from apps.ai_generation.langgraph_workflows import assessment_generator_app
        
        result = assessment_generator_app.invoke({
            "track_title": assessment.module.track.title,
            "module_title": assessment.module.title,
            "assessment_questions": []
        })
        
        questions = result.get("assessment_questions", [])
        
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


class RoadmapViewSet(viewsets.ModelViewSet):
    queryset = Roadmap.objects.all().prefetch_related('steps__track')
    serializer_class = RoadmapSerializer

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return Roadmap.objects.none()
        
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=self.request.user.email).first()
        if not learner:
            return Roadmap.objects.none()

        if self.request.user.email == SUPER_ADMIN_EMAIL:
            return Roadmap.objects.all().prefetch_related('steps__track')

        # Roadmaps are private to their creator and enrolled learners.
        # Finalized roadmaps can still be opened via direct share-link retrieval below,
        # but they should not appear in the general listing for unrelated users.
        return Roadmap.objects.filter(
            models.Q(created_by=learner) | 
            models.Q(enrollments__learner=learner) |
            models.Q(created_by__email=SUPER_ADMIN_EMAIL)
        ).distinct().prefetch_related('steps__track')

    def get_object(self):
        # Override to allow retrieving a specific roadmap even if not in the default queryset 
        # (critical for the enrollment landing page and public links)
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        return get_object_or_404(Roadmap.objects.all(), **filter_kwargs)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        # Allow viewing if it's finalized or the user is the creator/staff
        if not instance.is_finalized:
            from apps.accounts.models import Learner
            learner = Learner.objects.filter(email=request.user.email).first()
            if instance.created_by != learner and not request.user.is_staff:
                 return Response({"error": "Roadmap not found or access restricted"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        goal = request.data.get('goal')
        if not goal:
            return Response({"error": "Goal is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        from apps.accounts.models import Learner
        from apps.ai_generation.langgraph_workflows import roadmap_generator_app
        
        learner = None
        if not self.request.user.is_anonymous:
            learner = Learner.objects.filter(email=self.request.user.email).first()
        
        if not learner:
            learner, _ = Learner.objects.get_or_create(
                email="operator@example.com",
                defaults={"full_name": "MVP Operator", "auth_user_id": "mvp_operator"}
            )

        result = roadmap_generator_app.invoke({
            "goal": goal,
            "admin_id": str(learner.id),
            "roadmap_title": "",
            "roadmap_description": "",
            "steps": [],
            "roadmap_id": ""
        })
        
        roadmap_id = result.get("roadmap_id")
        if not roadmap_id:
            return Response({"error": "Failed to generate roadmap"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        roadmap = Roadmap.objects.get(id=roadmap_id)
        roadmap.created_by = learner
        roadmap.save()
        
        return Response(self.get_serializer(roadmap).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        roadmap = self.get_object()
        
        # Check permissions for non-public roadmaps (optional, but consistent)
        if not roadmap.is_finalized and not request.user.is_staff:
            from apps.accounts.models import Learner
            learner = Learner.objects.filter(email=request.user.email).first()
            if roadmap.created_by != learner:
                return Response({"error": "Enrollment restricted"}, status=status.HTTP_403_FORBIDDEN)
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=request.user.email).first()
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)
            
        enrollment, created = RoadmapEnrollment.objects.get_or_create(
            learner=learner,
            roadmap=roadmap
        )
        
        # Auto-enroll in all existing tracks and trigger background personalization
        from .models import TrackEnrollment
        from apps.ai_generation.services import analyze_resume_for_background

        learner_summary = None
        if learner.resume:
            try:
                learner_summary = analyze_resume_for_background(learner.resume.path)
            except:
                pass

        for step in roadmap.steps.all():
            if step.track:
                t_enroll, _ = TrackEnrollment.objects.get_or_create(
                    learner=learner,
                    track=step.track,
                    defaults={'personalized_summary': learner_summary}
                )
                # Trigger personalized content generation for this track
                thread = threading.Thread(target=background_generate_content, args=(step.track.id, learner.id))
                thread.start()
            
        return Response({"status": "enrolled", "created": created})

    @action(detail=True, methods=['get'])
    def enrolled_candidates(self, request, pk=None):
        if not request.user.is_staff:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        roadmap = self.get_object()
        enrollments = RoadmapEnrollment.objects.filter(roadmap=roadmap).select_related('learner')

        data = []
        for enrollment in enrollments:
            learner = enrollment.learner
            step_progress = []

            for step in roadmap.steps.all().order_by('order'):
                track_progress = None
                current_module = None
                if step.track:
                    track_progress = _calculate_track_progress(step.track, learner)
                    current_module = _get_current_module_summary(step.track, learner)

                step_progress.append({
                    "step_id": step.id,
                    "step_title": step.title,
                    "track_id": step.track.id if step.track else None,
                    "track_title": step.track.title if step.track else None,
                    "progress": track_progress,
                    "is_completed": track_progress == 100.0 if track_progress is not None else False,
                    "current_module": current_module,
                })

            data.append({
                "id": learner.id,
                "name": learner.full_name,
                "email": learner.email,
                "phone": learner.phone_number,
                "resume": learner.resume.url if learner.resume else None,
                "progress": _calculate_roadmap_progress(roadmap, learner),
                "enrolled_at": enrollment.enrolled_at,
                "current_focus": _get_roadmap_current_focus(roadmap, learner),
                "steps": step_progress,
            })

        return Response(data)

    @action(detail=True, methods=['post'])
    def finalize_step(self, request, pk=None):
        roadmap = self.get_object()
        step_id = request.data.get('step_id')
        step = RoadmapStep.objects.get(id=step_id, roadmap=roadmap)
        
        if step.track:
            return Response({"status": "already_finalized", "track_id": step.track.id})
            
        # Generate learning track for this step title/topic
        topic = step.title
        from apps.accounts.models import Learner
        learner = roadmap.created_by or Learner.objects.filter(email="operator@example.com").first()

        curriculum_data = generate_track_curriculum(topic, None) # No summary needed for template track
        if not curriculum_data:
            return Response({"error": "Failed to generate curriculum for step"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        track = Track.objects.create(
            title=curriculum_data.get('title', topic),
            description=curriculum_data.get('description', step.description),
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

        step.track = track
        step.save()
        
        return Response({"status": "finalized", "track_id": track.id})

    @action(detail=True, methods=['post'])
    def finalize_all(self, request, pk=None):
        roadmap = self.get_object()
        roadmap.is_finalized = True
        roadmap.save()
        
        # Immediate response with a share URL
        # We assume the frontend joins the base URL with the ID
        share_url = f"/roadmaps/share/{roadmap.id}" 
        
        from apps.accounts.models import Learner
        learner = roadmap.created_by or Learner.objects.filter(email=request.user.email).first() or Learner.objects.filter(email="operator@example.com").first()
        
        # Start background processing
        thread = threading.Thread(target=background_finalize_roadmap, args=(roadmap.id, learner.id))
        thread.start()
        
        return Response({
            "status": "processing", 
            "message": "Roadmap is being finalized in the background.",
            "share_url": share_url
        })

    @action(detail=True, methods=['get'])
    def final_assessment(self, request, pk=None):
        roadmap = self.get_object()
        learner = _get_request_learner(request)
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        finalized_tracks = [step.track for step in roadmap.steps.all() if step.track]
        total_modules = Module.objects.filter(track__in=finalized_tracks).count()
        completed_modules = AssessmentAttempt.objects.filter(
            learner=learner,
            assessment__module__track__in=finalized_tracks,
            passed=True
        ).values('assessment__module').distinct().count() if finalized_tracks else 0

        if total_modules == 0 or completed_modules < total_modules:
            return Response({
                "available": False,
                "completed_modules": completed_modules,
                "total_modules": total_modules,
                "error": "Complete every track in the roadmap before attempting the final evaluation."
            }, status=status.HTTP_200_OK)

        final_assessment = getattr(roadmap, 'final_assessment', None)
        if not final_assessment or not final_assessment.questions_data:
            final_assessment = _build_roadmap_final_assessment(roadmap)

        if not final_assessment:
            return Response({"error": "Failed to prepare roadmap final assessment"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "available": True,
            "assessment": FinalAssessmentSerializer(final_assessment, context={"request": request}).data
        })

    @action(detail=True, methods=['post'])
    def submit_final_assessment(self, request, pk=None):
        roadmap = self.get_object()
        learner = _get_request_learner(request)
        if not learner:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        final_assessment = getattr(roadmap, 'final_assessment', None)
        if not final_assessment:
            return Response({"error": "Final assessment not ready"}, status=status.HTTP_400_BAD_REQUEST)

        existing_attempt = FinalAssessmentAttempt.objects.filter(
            final_assessment=final_assessment,
            learner=learner
        ).first()
        if existing_attempt:
            return Response(
                {
                    "error": "This final assessment has already been completed.",
                    "attempt": FinalAssessmentAttemptSerializer(existing_attempt).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        answers = request.data.get('answers', {})
        integrity_flags = request.data.get('integrity_flags', {}) or {}
        violation_detected = any([
            integrity_flags.get('tab_switch_count', 0) > 0,
            integrity_flags.get('fullscreen_exit_count', 0) > 0,
            integrity_flags.get('context_menu_count', 0) > 0,
        ])

        score = 0.0 if violation_detected else _grade_questions(final_assessment.questions_data, answers)
        passed = (not violation_detected) and score >= final_assessment.passing_score
        terminated_reason = "Integrity violation detected during proctored final evaluation." if violation_detected else ""

        attempt = FinalAssessmentAttempt.objects.create(
            learner=learner,
            final_assessment=final_assessment,
            answers_data=answers,
            integrity_flags=integrity_flags,
            score=score,
            passed=passed,
            terminated_reason=terminated_reason,
        )

        if passed:
            _issue_certificate(learner, attempt)

        return Response(FinalAssessmentAttemptSerializer(attempt).data)

    @action(detail=True, methods=['post'])
    def reorder_steps(self, request, pk=None):
        roadmap = self.get_object()
        step_ids = request.data.get('step_ids', [])
        for index, step_id in enumerate(step_ids):
            RoadmapStep.objects.filter(id=step_id, roadmap=roadmap).update(order=index)
        return Response({"status": "reordered"})

    @action(detail=True, methods=['post'])
    def add_step(self, request, pk=None):
        roadmap = self.get_object()
        title = request.data.get('title', 'New Milestone')
        description = request.data.get('description', '')
        
        last_step = roadmap.steps.order_by('-order').first()
        order = (last_step.order + 1) if last_step else 0
        
        step = RoadmapStep.objects.create(
            roadmap=roadmap,
            title=title,
            description=description,
            order=order
        )
        return Response(RoadmapStepSerializer(step).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def delete_step(self, request, pk=None):
        roadmap = self.get_object()
        step_id = request.data.get('step_id')
        step = RoadmapStep.objects.filter(id=step_id, roadmap=roadmap).first()
        if step:
            if step.track:
                return Response({"error": "Cannot delete a step that has been finalized into a track"}, status=status.HTTP_400_BAD_REQUEST)
            step.delete()
            return Response({"status": "deleted"})
        return Response({"error": "Step not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def ai_add_step(self, request, pk=None):
        roadmap = self.get_object()
        instruction = request.data.get('instruction')
        if not instruction:
            return Response({"error": "Instruction is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        from apps.ai_generation.services import generate_custom_roadmap_step
        roadmap_data = RoadmapSerializer(roadmap).data
        
        step_data = generate_custom_roadmap_step(instruction, roadmap_data)
        if not step_data:
            return Response({"error": "Failed to generate AI step"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        last_step = roadmap.steps.order_by('-order').first()
        order = (last_step.order + 1) if last_step else 0
        
        step = RoadmapStep.objects.create(
            roadmap=roadmap,
            title=step_data.get('title', 'AI Milestone'),
            description=step_data.get('description', ''),
            order=order
        )
        return Response(RoadmapStepSerializer(step).data, status=status.HTTP_201_CREATED)


class RoadmapStepViewSet(viewsets.ModelViewSet):
    queryset = RoadmapStep.objects.all()
    serializer_class = RoadmapStepSerializer


class RoadmapEnrollmentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RoadmapEnrollmentSerializer

    def get_queryset(self):
        from apps.accounts.models import Learner
        learner = Learner.objects.filter(email=self.request.user.email).first()
        if not learner:
            return RoadmapEnrollment.objects.none()
        return RoadmapEnrollment.objects.filter(learner=learner)
