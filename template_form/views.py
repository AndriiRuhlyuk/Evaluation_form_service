from django.db.models import Count, Q


from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets, filters

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
    """
    ViewSet for managing TemplateForm.

    **Features:**
    - Full CRUD operations
    - Search by TemplateForm name
    - Filter by name of topics, topics and techstack
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/template-form/` - List active TemplateForm
    - `POST /api/template-form/` - Create new TemplateForm
    - `GET /api/template-form/{slug}/` - Get TemplateForm details
    - `PUT /api/template-form/{slug}/` - Update TemplateForm completely
    - `PATCH /api/template-form/{slug}/` - Update TemplateForm partially
    - `DELETE /api/template-form/{slug}/` - Soft delete TemplateForm
    """

    queryset = (
        TemplateForm.objects.select_related("tech_stack", "manager")
        .prefetch_related(
            "topics",
            "form_topics__topic",
            "form_topics__items__origin_question",
        )
        .annotate(
            active_items_count=Count(
                "form_topics__items", filter=Q(form_topics__items__is_removed=False)
            )
        )
    )
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = {
        "tech_stack": ["exact"],
        "tech_stack__name": ["icontains"],
        "topics": ["exact"],
    }
    search_fields = ["name"]
    ordering_fields = ["created_at"]

    lookup_field = "slug"

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

    @extend_schema(
        summary="List of template forms",
        description="Get list of template forms with comprehensive filtering, search and ordering options",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by template forms name (ex. ?search=Java Engineer)",
            ),
            OpenApiParameter(
                name="tech_stack",
                type=str,
                description="Filter by technical stack (ex. ?tech_stack=Java)",
            ),
            OpenApiParameter(
                name="tech_stack__name",
                type=str,
                description="Filter by technical stack name icontaints (ex. ?source=Jav)",
            ),
            OpenApiParameter(
                name="topics",
                type=str,
                description="Filter by topic (ex. ?topics=DB)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by: created_at,-created_at",
            ),
        ],
        tags=["Question"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class TemplateFormItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing items element inside TemplateForm

    **Features:**
    - Full CRUD operations
    - Search by TemplateFormItem text snapshot
    - Filter by name of topic_snapshot, topic_snapshot, source_snapshot and is_removed
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/template-form/items/` - List active TemplateFormItems
    - `GET /api/template-form/{slug}/items/{item_pk}/`` - Get TemplateFormItems details
    - `PUT /api/template-form/{slug}/items/{item_pk}/`` - Update TemplateFormItems completely
    - `PATCH /api/template-form/{slug}/items/{item_pk}/`` - Update TemplateFormItems partially
    - `DELETE /api/template-form/{slug}/items/{item_pk}/` - Soft delete TemplateFormItems instance
    """

    queryset = TemplateFormItems.objects.select_related(
        "form_topic__form", "form_topic__topic", "origin_question", "added_by"
    )
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = {
        "is_removed": ["exact"],
        "source_snapshot": ["exact"],
        "topic_snapshot": ["exact"],
    }
    search_fields = ["text_snapshot", "origin_question__question_text"]
    ordering_fields = [
        "difficulty_snapshot",
        "created_at",
    ]

    serializer_class = TemplateFormItemsListSerializer

    def get_queryset(self):
        """
        Queryset elements filtered by TemplateForm
        """
        base_queryset = super().get_queryset()
        return base_queryset.filter(
            form_topic__form__slug=self.kwargs["form_topic__form_slug"]
        )

    def get_serializer_class(self):
        if self.action in ["update", "partial_update"]:
            return TemplateFormItemUpdateSerializer
        return TemplateFormItemsDetailSerializer

    def perform_update(self, serializer):
        """
        Topics synchronisation after UPDATE items
        """

        instance = serializer.save()
        _synchronize_form_topics(instance.form_topic.form)

    def perform_destroy(self, instance):
        """Soft-delete"""

        instance.is_removed = True
        instance.save()

    @extend_schema(
        summary="List of template forms items",
        description="Get list of template form items with comprehensive filtering, search and ordering options",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by snapshot text question (ex. ?text_snapshot=What is the dependency injection?)",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by origin question text question (ex. ?origin_question__question_text=What is)",
            ),
            OpenApiParameter(
                name="topic_snapshot",
                type=str,
                description="Filter by topic snapshot (ex. ?topic_snapshot=ORM)",
            ),
            OpenApiParameter(
                name="source_snapshot",
                type=str,
                description="Filter by source of question snapshot (ex. ?source=TEMPLATE)",
            ),
            OpenApiParameter(
                name="is_removed",
                type=bool,
                description="Filter by active status (ex. ?is_removed=false)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by: created_at, -created_at, difficulty_snapshot, -difficulty_snapshot",
            ),
        ],
        tags=["Question"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
