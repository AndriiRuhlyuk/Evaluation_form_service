from django.urls import path, include
from rest_framework import routers

from evaluation_form import views

app_name = "evaluation_form"

router = routers.DefaultRouter()

# 1. Головний ViewSet (тільки для читання: list, retrieve)
router.register(
    r"evaluation-forms", views.EvaluationFormViewSet, basename="evaluation-form"
)

# 2. ViewSet для ЗАПИСУ ОЦІНОК (питань)
#    Дозволяє POST/PATCH на /api/evaluation-scores/
router.register(
    r"evaluation-scores", views.EvaluationScoreViewSet, basename="evaluation-score"
)

# 3. ViewSet для ЗАПИСУ ФІДБЕКІВ
#    Дозволяє GET/PATCH на /api/evaluation-feedbacks/{id}/
router.register(
    r"evaluation-feedbacks",
    views.EvaluationFeedbackViewSet,
    basename="evaluation-feedback",
)

router.register(r"candidates", views.CandidateViewSet, basename="candidate")


urlpatterns = [
    path("", include(router.urls)),
]
