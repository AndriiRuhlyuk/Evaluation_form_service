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

    This ViewSet provides a complete set of CRUD operations for Project models,
    with additional features like soft deletion, restoration, filtering, and search.
    It uses different serializers for different actions to optimize API responses.

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
    - `POST /api/projects/{id}/restore/` - Restore inactive project
    """

    # Base queryset for all operations
    queryset = Project.objects.all()
    # Default serializer class for most operations
    serializer_class = ProjectSerializer
    # Filter backends for search, ordering and filtering capabilities
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    # Fields that can be filtered via query parameters
    filterset_fields = ["is_active"]
    # Fields that can be searched via the search query parameter
    search_fields = ["name"]
    # Fields that can be used for ordering results
    ordering_fields = ["name", "id"]
    # Default permission classes requiring authentication and employee status
    permission_classes = [IsAuthenticated, IsEmployee]

    def get_permissions(self):
        """
        Customize permissions based on the action being performed.

        Different actions require different permission levels:
        - destroy and restore: Only employees can perform these actions
        - create, update, partial_update: Any authenticated user can perform these actions
        - Other actions: No specific permissions required

        Returns:
            list: List of permission instances appropriate for the current action
        """
        # Check if action attribute exists and has a value
        if hasattr(self, "action") and self.action:
            # Actions that require employee status
            if self.action in ["destroy", "restore"]:
                return [IsEmployee()]
            # Actions that only require authentication
            elif self.action in ["create", "update", "partial_update"]:
                return [AllowAny()]
        # Default to empty permissions list
        return []

    def get_serializer_class(self):
        """
        Select the appropriate serializer class based on the current action.

        Different actions require different serialization:
        - list: Uses simplified serializer with links to detail views
        - restore: Uses specialized serializer for restoration responses
        - Other actions: Uses the full project serializer

        Returns:
            class: The serializer class to use for the current action
        """
        # For list actions, use the simplified list serializer
        if self.action == "list":
            return ProjectListSerializer
        # For restore actions, use the specialized restore serializer
        if self.action == "restore":
            return ProjectRestoreSerializer
        # Default to the full project serializer
        return ProjectSerializer

    def get_queryset(self):
        """
        Customize the queryset based on the current action.

        For list actions, filter by is_active by default (showing only active projects),
        unless explicitly requested otherwise via query parameters.
        For all other actions, return the full queryset.

        Returns:
            QuerySet: Filtered queryset appropriate for the current action
        """
        # Start with the complete queryset
        queryset = Project.objects.all()

        # For list actions, apply default filtering
        if self.action == "list":
            # Check if is_active parameter was provided in the request
            is_active_param = self.request.query_params.get("is_active")
            # If not provided, default to showing only active projects
            if is_active_param is None:
                queryset = queryset.filter(is_active=True)

        return queryset

    def perform_destroy(self, instance):
        """
        Implement soft deletion instead of actual deletion.

        Instead of removing the project from the database, mark it as inactive.
        This allows for restoration later and preserves historical data.

        Args:
            instance: The Project instance to be "deleted"
        """
        # Mark the project as inactive instead of deleting it
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
        Restore a previously soft-deleted project.

        This endpoint allows administrators to reactivate a project that was previously
        marked as inactive through the soft-delete mechanism.

        Args:
            request: The HTTP request object
            pk: The primary key of the project to restore

        Returns:
            Response: HTTP response with restoration status and project data
        """
        # Get the project instance to restore
        instance = self.get_object()

        # Check if the project is already active
        if instance.is_active:
            return Response(
                {"error": "Project is already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark the project as active
        instance.is_active = True
        instance.save()

        # Serialize the restored project
        serializer = self.get_serializer(instance)
        # Return success response with project data
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
        """
        List projects with optional filtering, search, and ordering.

        This method is enhanced with OpenAPI documentation to clearly describe
        the available query parameters for filtering, searching, and ordering.

        Args:
            request: The HTTP request object
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Response: HTTP response containing the list of projects
        """
        return super().list(request, *args, **kwargs)
