from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from techstack.models import TechStack
from drf_spectacular.utils import extend_schema, OpenApiParameter
from techstack.serializers import TechStackSerializer, TechStackListSerializer


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

    queryset = TechStack.objects.filter(is_active=True)
    serializer_class = TechStackSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active"]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]

    def get_serializer_class(self):
        if self.action == "list":
            return TechStackListSerializer
        return TechStackSerializer

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
                description="Filter by active status (ex. ?is_active=true)",
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
