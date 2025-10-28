from rest_framework.decorators import action
from rest_framework import viewsets, filters, status
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from project.models import Project
from drf_spectacular.utils import extend_schema, OpenApiParameter

from project.permissions import IsEmployee
from project.serializers import (
    ProjectSerializer,
    ProjectListSerializer,
    ProjectRestoreSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing projects used in candidate evaluation forms.

    **Features:**
    - Full CRUD operations
    - Search by name
    - Filter by active status
    - Soft delete functionality
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/projects/` - List active projects (simplified view)
    - `POST /api/projects/` - Create new project
    - `GET /api/projects/{id}/` - Get project details (full view)
    - `PUT /api/projects/{id}/` - Update project completely
    - `PATCH /api/projects/{id}/` - Update project partially
    - `DELETE /api/projects/{id}/` - Soft delete project
    - `POST /api/projects/{id}/restore/` - Restore unactive project
    """

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active"]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    permission_classes = [IsAuthenticated, IsEmployee]

    def get_permissions(self):
        if hasattr(self, "action") and self.action:
            if self.action in ["destroy", "restore"]:
                return [IsEmployee()]
            elif self.action in ["create", "update", "partial_update"]:
                return [AllowAny()]
        return []

    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer
        if self.action == "restore":
            return ProjectRestoreSerializer
        return ProjectSerializer

    def get_queryset(self):
        """
        For LIST - filter by is_active (by default only active)
        For DETAIL (retrieve, update, destroy) - always all objects
        """
        queryset = Project.objects.all()

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
        summary="Restore inactive project",
        description="Restore a soft-deleted project by setting is_active=True. Only for admins.",
        responses={
            200: ProjectRestoreSerializer,
            400: {"description": "Project is already active"},
            404: {"description": "Project not found"},
        },
        tags=["Project"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """
        POST /api/projects/{id}/restore/ - restore unactive project
        Only for admins
        """
        instance = self.get_object()

        if instance.is_active:
            return Response(
                {"error": "Project is already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.is_active = True
        instance.save()

        serializer = self.get_serializer(instance)
        return Response(
            {
                "message": f"Project '{instance.name}' restored successfully",
                "topic": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="List projects",
        description="Get list of projects with search and filtering",
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
        tags=["Projects"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
