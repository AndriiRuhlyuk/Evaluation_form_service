from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from template_form.permissions import IsManagerOrSuperuser
from .permissions import IsEmployee

from question.models import Question
from question.serializers import (
    QuestionSerializer,
    QuestionListSerializer,
    QuestionDetailSerializer,
    QuestionRestoreSerializer,
)


class QuestionPagination(PageNumberPagination):
    """
    Pagination class for Question API.

    This class configures how questions are paginated in API responses,
    controlling the default number of items per page and the maximum
    allowed page size.
    """

    # Default number of questions to display per page
    page_size = 10

    # Maximum number of questions that can be requested per page
    max_page_size = 100


class QuestionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing questions used in candidate evaluation forms.

    This ViewSet provides a complete set of CRUD operations for Question objects,
    with advanced filtering, searching, and permission controls. It implements
    soft delete functionality and uses different serializers based on the action.

    **Features:**
    - Full CRUD operations
    - Search by question text
    - Filter by name of topics, question difficulty, source and active status
    - Soft delete functionality
    - Different serializers for list vs detail views

    **Endpoints:**
    - `GET /api/questions/` - List active Questions
    - `POST /api/questions/` - Create new Question
    - `GET /api/questions/{id}/` - Get Question details (full view)
    - `PUT /api/questions/{id}/` - Update Question completely
    - `PATCH /api/questions/{id}/` - Update Question partially
    - `DELETE /api/questions/{id}/` - Soft delete Question
    - `POST /api/questions/{id}/restore/` - Restore unactive Question
    """

    # Base queryset with optimized database access using select_related
    queryset = Question.objects.select_related("topic", "question_author").order_by(
        "topic",
        "-difficulty",
        "created_at",  # Order by topic, then difficulty (descending), then creation date
    )

    # Default serializer for create/update operations
    serializer_class = QuestionSerializer

    # Pagination configuration for list views
    pagination_class = QuestionPagination

    # Filter backends for search, ordering, and filtering
    filter_backends = (
        DjangoFilterBackend,  # For field-based filtering
        filters.SearchFilter,  # For text search
        filters.OrderingFilter,  # For result ordering
    )

    # Fields that can be filtered and their lookup types
    filterset_fields = {
        "topic": ["exact"],  # Filter by topic ID
        "topic__name": ["icontains"],  # Filter by topic name (case-insensitive)
        "difficulty": ["exact"],  # Filter by difficulty level
        "source": ["exact"],  # Filter by question source
        "is_active": ["exact"],  # Filter by active status
    }

    # Fields that can be searched
    search_fields = ["question_text"]  # Search in question text

    # Fields that can be used for ordering results
    ordering_fields = [
        "difficulty",
        "usage_count",
    ]  # Order by difficulty or usage count

    # Default permission classes
    permission_classes = [
        IsAuthenticated,
        IsEmployee,
    ]  # User must be authenticated and an employee

    def get_serializer_class(self):
        """
        Return the appropriate serializer class based on the current action.

        This method dynamically selects the serializer based on the action being performed:
        - list: Uses QuestionListSerializer with minimal fields for list views
        - retrieve: Uses QuestionDetailSerializer with all fields for detail views
        - restore: Uses QuestionRestoreSerializer for the restore action
        - default: Uses QuestionSerializer for create/update operations

        Returns:
            Serializer class: The appropriate serializer for the current action
        """
        if self.action == "list":
            return QuestionListSerializer  # Simplified serializer for list views
        if self.action == "retrieve":
            return (
                QuestionDetailSerializer  # Detailed serializer for single question view
            )
        if self.action == "restore":
            return (
                QuestionRestoreSerializer  # Specialized serializer for restore action
            )
        return QuestionSerializer  # Default serializer for create/update

    def get_permissions(self):
        """
        Return the appropriate permission classes based on the current action.

        This method implements different permission levels:
        - For read-only actions (list, retrieve): Only authentication is required
        - For all other actions: User must be authenticated and have manager/superuser privileges

        Returns:
            list: List of permission instances for the current action
        """
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]  # Any authenticated user can view questions

        return [
            permissions.IsAuthenticated(),
            IsManagerOrSuperuser(),
        ]  # Only managers can modify questions

    def perform_create(self, serializer):
        """
        Set the current user as the author when creating a new question.

        This method is called during the creation of a new question and automatically
        assigns the authenticated user as the question_author.

        Args:
            serializer: The validated serializer instance
        """
        serializer.save(
            question_author=self.request.user
        )  # Set current user as question author

    def get_queryset(self):
        """
        Filter the queryset based on the current action and request parameters.

        For LIST action:
        - By default, only return active questions
        - If is_active parameter is explicitly provided, use that value instead

        For all other actions (retrieve, update, destroy):
        - Return all questions regardless of active status

        Returns:
            QuerySet: Filtered Question queryset
        """
        queryset = super().get_queryset()

        if self.action == "list":
            is_active_param = self.request.query_params.get(
                "is_active"
            )  # Check if is_active filter is provided
            if is_active_param is None:
                queryset = queryset.filter(
                    is_active=True
                )  # Default: show only active questions

        return queryset

    def perform_destroy(self, instance):
        """
        Implement soft delete by marking the question as inactive.

        Instead of actually deleting the question from the database,
        this method sets is_active=False to hide it from default views
        while preserving the data.

        Args:
            instance: The Question instance to be "deleted"
        """
        instance.is_active = False  # Mark as inactive instead of deleting
        instance.save()

    @extend_schema(
        summary="Restore inactive question",
        description="Restore a soft-deleted question by setting is_active=True. Only for author or interviewer.",
        responses={
            200: QuestionRestoreSerializer,
            400: {"description": "Question is already active"},
            404: {"description": "Question not found"},
        },
        tags=["Question"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """
        Restore a previously soft-deleted (inactive) question.

        This custom action allows authorized users to restore questions that were
        previously marked as inactive through the soft delete mechanism. It checks
        if the question is already active to prevent unnecessary operations.

        Args:
            request: The HTTP request object
            pk: The primary key of the question to restore

        Returns:
            Response: A success message with the restored question data or an error message

        HTTP Methods:
            POST /api/question/{id}/restore/ - restore inactive question
        """
        instance = self.get_object()  # Get the question instance

        # Check if the question is already active
        if instance.is_active:
            return Response(
                {"error": "Question is already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Restore the question by setting is_active to True
        instance.is_active = True
        instance.save()

        # Return success response with the restored question data
        serializer = self.get_serializer(instance)
        return Response(
            {
                "message": f"Question '{instance.question_text}' restored successfully",
                "question": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="List of questions",
        description="Get list of questions with comprehensive filtering, search and ordering options",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by question text (ex. ?search=webhooks)",
            ),
            OpenApiParameter(
                name="topic__name",
                type=str,
                description="Filter by topic name (ex. ?topic__name=frameworks)",
            ),
            OpenApiParameter(
                name="source",
                type=str,
                description="Filter by question source: template, manual, imported (ex. ?source=template)",
            ),
            OpenApiParameter(
                name="is_active",
                type=bool,
                description="Filter by active status (ex. ?is_active=false)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by: difficulty, usage_count, -difficulty, -usage_count",
            ),
        ],
        tags=["Question"],
    )
    def list(self, request, *args, **kwargs):
        """
        List questions with support for pagination, filtering, and searching.

        This method overrides the default list method to provide enhanced documentation
        through the @extend_schema decorator. It supports:
        - Pagination (configured by QuestionPagination)
        - Filtering by topic, difficulty, source, and active status
        - Searching by question text
        - Ordering by difficulty and usage count

        By default, only active questions are returned unless is_active parameter is specified.

        Args:
            request: The HTTP request object
            *args, **kwargs: Additional arguments passed to the parent method

        Returns:
            Response: Paginated list of questions matching the filter criteria
        """
        return super().list(request, *args, **kwargs)  # Use the parent implementation
