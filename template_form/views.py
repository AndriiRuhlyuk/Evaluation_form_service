from rest_framework import viewsets

from template_form.models import TemplateForm, TemplateFormItems
from template_form.serializers import (
    TemplateFormListSerializer,
    TemplateFormDetailSerializer,
    TemplateFormSerializer,
    TemplateFormItemsDetailSerializer,
    TemplateFormItemsListSerializer,
    TemplateFormItemUpdateSerializer,
)
from template_form.services import _synchronize_form_topics


class TemplateFormViewSet(viewsets.ModelViewSet):
    queryset = TemplateForm.objects.prefetch_related("items")

    def get_serializer_class(self):
        if self.action == "list":
            return TemplateFormListSerializer
        elif self.action == "retrieve":
            return TemplateFormDetailSerializer
        return TemplateFormSerializer

    def get_serializer_context(self):
        """
        Pass request object to serializer for access to current user
        """
        return {"request": self.request}


class TemplateFormItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing items element inside TemplateForm
    URL: /template-form/{form_pk}/items/{item_pk}/
    """

    serializer_class = TemplateFormItemsListSerializer

    def get_queryset(self):
        """
        Queryset elements filtered by TemplateForm
        """
        return TemplateFormItems.objects.filter(form_id=self.kwargs["form_pk"])

    def get_serializer_class(self):
        if self.action in ["update", "partial_update"]:
            return TemplateFormItemUpdateSerializer
        return TemplateFormItemsDetailSerializer

    def perform_update(self, serializer):
        """
        Topics synchronisation after UPDATE items
        """

        instance = serializer.save()
        _synchronize_form_topics(instance.form)

    def perform_destroy(self, instance):
        """Soft-delete"""

        instance.is_removed = True
        instance.save()
