from rest_framework import routers
from django.urls import path, include
from project.views import ProjectViewSet


app_name = "project"
router = routers.DefaultRouter()

router.register("", ProjectViewSet, basename="project")

urlpatterns = [path("", include(router.urls))]
