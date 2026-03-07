from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.accounts.views import LearnerViewSet
from apps.curriculum.views import TrackViewSet, ModuleViewSet, LessonViewSet, AssessmentViewSet
from apps.readiness.views import ReadinessSnapshotViewSet

router = DefaultRouter()
router.register(r'learners', LearnerViewSet)
router.register(r'tracks', TrackViewSet, basename='track')
router.register(r'modules', ModuleViewSet)
router.register(r'lessons', LessonViewSet)
router.register(r'assessments', AssessmentViewSet)
router.register(r'readiness', ReadinessSnapshotViewSet)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/oidc/', include('mozilla_django_oidc.urls')),
    path('api/', include(router.urls)),
    path('api/', include('apps.ai_generation.urls')),
]
