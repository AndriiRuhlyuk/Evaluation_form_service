from rest_framework import routers
from django.urls import path, include
from topic.views import TopicViewSet


app_name = "topic"
router = routers.DefaultRouter()

router.register("", TopicViewSet, basename="topic")

urlpatterns = [path("", include(router.urls))]
