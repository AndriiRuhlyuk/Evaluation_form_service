from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.response import Response

from topic.models import Topic
from topic.serializers import (
    TopicSerializer,
    TopicListSerializer,
    TopicRestoreSerializer,
)


class TopicViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing questions topics used in candidate evaluation forms.

    **Features:**
    - Full CRUD operations
    - Search by name
    - Filter by active status
    - Soft delete functionality
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/topics/` - List active topics
    - `POST /api/topics/` - Create new topic
    - `GET /api/topics/{id}/` - Get topic details (full view)
    - `PUT /api/topics/{id}/` - Update topic completely
    - `PATCH /api/topics/{id}/` - Update topic partially
    - `DELETE /api/topics/{id}/` - Soft delete topic
    """

    queryset = Topic.objects.all()
    serializer_class = TopicSerializer
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]
    search_fields = ["name"]
    filterset_fields = ["is_active"]
    ordering_fields = ["name", "id"]

    def get_permissions(self):
        if hasattr(self, "action") and self.action:
            if self.action in ["destroy", "restore"]:
                return [IsAdminUser()]
            elif self.action in ["create", "update", "partial_update"]:
                return [AllowAny()]
        return []

    def get_serializer_class(self):
        if self.action == "list":
            return TopicListSerializer
        if self.action == "restore":
            return TopicRestoreSerializer
        return TopicSerializer

    def get_queryset(self):
        """
        For LIST - filter by is_active (by default only active)
        For DETAIL (retrieve, update, destroy) - always all objects
        """
        queryset = Topic.objects.all()

        if self.action == "list":
            is_active_param = self.request.query_params.get("is_active")
            if is_active_param is None:
                queryset = queryset.filter(is_active=True)

        return queryset

    def perform_destroy(self, instance):
        """Soft delete: mark as inactive instead of actual deletion"""
        instance.is_active = False
        instance.save()

    @extend_schema(
        summary="Restore inactive topic",
        description="Restore a soft-deleted topic by setting is_active=True. Only for admins.",
        responses={
            200: TopicRestoreSerializer,
            400: {"description": "Topic is already active"},
            404: {"description": "Topic not found"},
        },
        tags=["Topics"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """
        POST /api/topics/{id}/restore/ - restore unactive topic
        Only for admins
        """
        instance = self.get_object()

        if instance.is_active:
            return Response(
                {"error": "Topic is already active"}, status=status.HTTP_400_BAD_REQUEST
            )

        instance.is_active = True
        instance.save()

        serializer = self.get_serializer(instance)
        return Response(
            {
                "message": f"Topic '{instance.name}' restored successfully",
                "topic": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="List topics",
        description="Get list of topics with search and filtering",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by name (ex. ?search=CI/CD)",
            ),
            OpenApiParameter(
                name="is_active",
                type=bool,
                description="Filter by active status (ex. ?is_active=true)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by field (ex. ?ordering=name)",
            ),
        ],
        tags=["Topics"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
