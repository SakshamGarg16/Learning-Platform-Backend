from django.contrib import admin
from .models import Track, Module, Lesson, Assessment, AssessmentAttempt, TrackEnrollment, Roadmap, RoadmapStep, RoadmapEnrollment

@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'created_at')

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'track', 'order')

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'module', 'order')

@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('module',)

@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = ('learner', 'assessment', 'score', 'passed')

@admin.register(TrackEnrollment)
class TrackEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('learner', 'track', 'enrolled_at')

@admin.register(Roadmap)
class RoadmapAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'created_at')

@admin.register(RoadmapStep)
class RoadmapStepAdmin(admin.ModelAdmin):
    list_display = ('title', 'roadmap', 'order')

@admin.register(RoadmapEnrollment)
class RoadmapEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('learner', 'roadmap', 'enrolled_at')
