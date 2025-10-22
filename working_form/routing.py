from django.urls import path
from . import consumers


websocket_urlpatterns = [
    path("ws/working_form/<int:form_id>", consumers.WorkingFormConsumer.as_asgi()),
]
