from django.urls import path, include
from rest_framework_nested import routers

from template_form import views


app_name = "template_form"

router = routers.SimpleRouter()
router.register(r"", views.TemplateFormViewSet, basename="template-form")

items_router = routers.NestedSimpleRouter(router, r"", lookup="form_topic__form")
items_router.register(r"items", views.TemplateFormItemViewSet, basename="form-items")

urlpatterns = [
    path("", include(items_router.urls)),
    path("", include(router.urls)),
]
