from rest_framework.decorators import action
from rest_framework import viewsets, filters, status
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.response import Response

from techstack.models import TechStack
from drf_spectacular.utils import extend_schema, OpenApiParameter
from techstack.serializers import (
    TechStackSerializer,
    TechStackListSerializer,
    TechStackRestoreSerializer,
)


class TechStackViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing technology stacks used in candidate evaluation forms.

    **Features:**
    - Full CRUD operations
    - Search by name
    - Filter by active status
    - Soft delete functionality
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/techstacks/` - List active tech stacks (simplified view)
    - `POST /api/techstacks/` - Create new tech stack
    - `GET /api/techstacks/{id}/` - Get tech stack details (full view)
    - `PUT /api/techstacks/{id}/` - Update tech stack completely
    - `PATCH /api/techstacks/{id}/` - Update tech stack partially
    - `DELETE /api/techstacks/{id}/` - Soft delete tech stack
    """

    queryset = TechStack.objects.all()
    serializer_class = TechStackSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active"]
    search_fields = ["name"]
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
            return TechStackListSerializer
        if self.action == "restore":
            return TechStackRestoreSerializer
        return TechStackSerializer

    def get_queryset(self):
        """
        For LIST - filter by is_active (by default only active)
        For DETAIL (retrieve, update, destroy) - always all objects
        """
        queryset = TechStack.objects.all()

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
        summary="Restore inactive techstack",
        description="Restore a soft-deleted techstack by setting is_active=True. Only for admins.",
        responses={
            200: TechStackRestoreSerializer,
            400: {"description": "Techstack is already active"},
            404: {"description": "Techstack not found"},
        },
        tags=["TechStack"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """
        POST /api/techstacks/{id}/restore/ - restore unactive techstack
        Only for admins
        """
        instance = self.get_object()

        if instance.is_active:
            return Response(
                {"error": "Techstack is already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.is_active = True
        instance.save()

        serializer = self.get_serializer(instance)
        return Response(
            {
                "message": f"Techstack '{instance.name}' restored successfully",
                "topic": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="List tech stacks",
        description="Get list of tech stacks with search and filtering",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by name (ex. ?search=python)",
            ),
            OpenApiParameter(
                name="is_active",
                type=bool,
                description="Filter by active status (ex. ?is_active=false)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by field (ex. ?ordering=name)",
            ),
        ],
        tags=["Tech Stacks"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
