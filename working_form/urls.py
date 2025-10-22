from django.urls import path, include
from rest_framework_nested import routers
from . import views


app_name = "working_form"

router = routers.SimpleRouter()
router.register(r"", views.WorkingFormViewSet, basename="working-form")

topics_router = routers.NestedSimpleRouter(router, r"", lookup="working_form")
topics_router.register(
    r"topics", views.WorkingFormTopicViewSet, basename="working-form-topics"
)

items_router = routers.NestedSimpleRouter(router, r"", lookup="working_form")
items_router.register(
    r"items", views.WorkingFormItemViewSet, basename="working-form-items"
)


urlpatterns = [
    path("", include(router.urls)),
    path("", include(topics_router.urls)),
    path("", include(items_router.urls)),
]
