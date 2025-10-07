from rest_framework import routers
from django.urls import path, include
from question.views import QuestionViewSet


app_name = "question"
router = routers.DefaultRouter()

router.register("", QuestionViewSet, basename="question")

urlpatterns = [path("", include(router.urls))]