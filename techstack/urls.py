from rest_framework import routers
from django.urls import path, include
from techstack.views import TechStackViewSet


app_name = "techstack"
router = routers.DefaultRouter()

router.register("", TechStackViewSet, basename="techstack")

urlpatterns = [path("", include(router.urls))]
