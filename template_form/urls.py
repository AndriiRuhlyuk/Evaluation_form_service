from django.urls import path, include
from rest_framework_nested import routers
from .views import TemplateFormViewSet, TemplateFormItemViewSet

app_name = "template_form"

router = routers.SimpleRouter()
router.register(r"", TemplateFormViewSet, basename="template-form")

items_router = routers.NestedSimpleRouter(router, r"", lookup="form")
items_router.register(r"items", TemplateFormItemViewSet, basename="form-items")

urlpatterns = [
    path("", include(items_router.urls)),
    path("", include(router.urls)),
]
