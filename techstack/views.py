from rest_framework.decorators import action
from rest_framework import viewsets, filters, status, permissions
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from techstack.models import TechStack
from drf_spectacular.utils import extend_schema, OpenApiParameter

from techstack.permissions import (
    IsEmployee,
)  # Custom permission to check if user is an employee
from techstack.serializers import (
    TechStackSerializer,  # Detailed serializer for single tech stack
    TechStackListSerializer,  # Simplified serializer for list views
    TechStackRestoreSerializer,  # Serializer for restoration responses
)
from template_form.permissions import (
    IsManagerOrSuperuser,
)  # Permission for manager/admin operations


class TechStackViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing technology stacks used in candidate evaluation forms.

    This ViewSet provides a complete set of CRUD operations for managing technology stacks
    that are used to categorize and organize evaluation forms. It implements soft deletion
    instead of hard deletion to preserve data integrity, and provides specialized endpoints
    for restoring soft-deleted tech stacks.

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
    - `POST /api/techstacks/{id}/restore/` - Restore inactive techstack
    """

    queryset = TechStack.objects.all()  # Base queryset of all tech stacks
    serializer_class = (
        TechStackSerializer  # Default serializer for detail, create, update operations
    )
    filter_backends = [
        DjangoFilterBackend,  # Enables filtering by query parameters
        filters.SearchFilter,  # Enables searching by specified fields
        filters.OrderingFilter,  # Enables ordering by specified fields
    ]
    filterset_fields = ["is_active"]  # Fields that can be filtered via query params
    search_fields = ["name"]  # Fields that can be searched
    ordering_fields = ["name", "id"]  # Fields that can be used for ordering
    permission_classes = [IsAuthenticated, IsEmployee]  # Default permissions

    def get_permissions(self):
        """
        Determine the permissions for different actions.

        For read-only actions (list, retrieve), only authentication is required.
        For all other actions (create, update, delete, restore), the user must be
        both authenticated and have manager or superuser privileges.

        Returns:
            list: List of permission classes to apply
        """
        if self.action in ["list", "retrieve"]:
            return [
                IsAuthenticated()
            ]  # Read-only operations require only authentication

        return [
            permissions.IsAuthenticated(),
            IsManagerOrSuperuser(),
        ]  # Write operations require manager/admin privileges

    def get_serializer_class(self):
        """
        Select the appropriate serializer based on the current action.

        - For list views: Use TechStackListSerializer for a concise representation
        - For restore action: Use TechStackRestoreSerializer for restoration responses
        - For all other actions: Use TechStackSerializer for full representation

        Returns:
            class: The serializer class to use
        """
        if self.action == "list":
            return TechStackListSerializer  # Simplified serializer for list views
        if self.action == "restore":
            return TechStackRestoreSerializer  # Specialized serializer for restoration responses
        return TechStackSerializer  # Detailed serializer for all other operations

    def get_queryset(self):
        """
        Filter the queryset based on the current action.

        For LIST action:
        - By default, only return active tech stacks (is_active=True)
        - If 'is_active' query parameter is explicitly provided, use that value instead

        For all other actions (retrieve, update, destroy):
        - Return all tech stacks regardless of active status

        Returns:
            QuerySet: Filtered queryset of TechStack objects
        """
        queryset = TechStack.objects.all()  # Start with all tech stacks

        if self.action == "list":
            is_active_param = self.request.query_params.get(
                "is_active"
            )  # Get is_active filter from query params
            if is_active_param is None:
                queryset = queryset.filter(
                    is_active=True
                )  # Default to showing only active tech stacks

        return queryset

    def perform_destroy(self, instance):
        """
        Implement soft deletion instead of hard deletion.

        Instead of removing the record from the database, this method marks
        the tech stack as inactive (is_active=False). This preserves the data
        for historical purposes while hiding it from normal use.

        Args:
            instance (TechStack): The tech stack to soft-delete
        """
        instance.is_active = False  # Mark as inactive instead of deleting
        instance.save()  # Save the updated instance

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
        Restore a soft-deleted tech stack by setting is_active=True.

        This endpoint allows administrators to restore a previously soft-deleted
        tech stack, making it available for use again in the system. It checks
        if the tech stack is already active to prevent unnecessary operations.

        Args:
            request (Request): The HTTP request
            pk (int): The primary key of the tech stack to restore

        Returns:
            Response: A response containing a success message and the restored tech stack data,
                     or an error message if the tech stack is already active
        """
        instance = self.get_object()  # Get the tech stack instance

        if instance.is_active:
            # If already active, return an error
            return Response(
                {"error": "Techstack is already active"},  # Error message
                status=status.HTTP_400_BAD_REQUEST,  # 400 status code
            )

        # Restore the tech stack by setting is_active to True
        instance.is_active = True
        instance.save()

        # Serialize the restored tech stack for the response
        serializer = self.get_serializer(instance)
        return Response(
            {
                "message": f"Techstack '{instance.name}' restored successfully",  # Success message
                "topic": serializer.data,  # Serialized tech stack data
            },
            status=status.HTTP_200_OK,  # 200 status code
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
        """
        List tech stacks with optional filtering, searching, and ordering.

        This method extends the default list behavior with OpenAPI documentation
        for the available query parameters. By default, it returns only active
        tech stacks unless the is_active parameter is explicitly provided.

        Args:
            request (Request): The HTTP request with optional query parameters
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments

        Returns:
            Response: A paginated list of tech stacks matching the filters
        """
        return super().list(
            request, *args, **kwargs
        )  # Use the parent class implementation
