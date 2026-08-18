from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from template_form.permissions import IsManagerOrSuperuser
from topic.permissions import IsEmployee

from question.models import Question
from question.serializers import QuestionSerializer
from topic.models import Topic
from topic.serializers import (
    TopicSerializer,
    TopicListSerializer,
    TopicRestoreSerializer,
)


class TopicViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing question topics used in candidate evaluation forms.

    This viewset provides a complete set of CRUD operations for Topic objects,
    with additional features like soft deletion, restoration, and recommended
    questions. It implements different permission levels based on the action
    and uses different serializers for different views.

    **Features:**
    - Full CRUD operations
    - Search by name
    - Filter by active status
    - Soft delete functionality (marks as inactive instead of deleting)
    - Different serializers for list vs detail views
    - Recommended questions endpoint for form building

    **Endpoints:**
    - `GET /api/topics/` - List active topics
    - `POST /api/topics/` - Create new topic
    - `GET /api/topics/{id}/` - Get topic details (full view)
    - `PUT /api/topics/{id}/` - Update topic completely
    - `PATCH /api/topics/{id}/` - Update topic partially
    - `DELETE /api/topics/{id}/` - Soft delete topic
    - `POST /api/topics/{id}/restore/` - Restore inactive topic
    - `GET /api/topics/{id}/recommended_questions/` - Get recommended questions for this topic
    """

    # Base queryset for all operations (may be filtered further in get_queryset)
    queryset = Topic.objects.all()

    # Default serializer class (may be overridden in get_serializer_class)
    serializer_class = TopicSerializer

    # Filter backends for search, filtering, and ordering
    filter_backends = [
        filters.SearchFilter,  # Enables searching by name
        DjangoFilterBackend,  # Enables filtering by is_active
        filters.OrderingFilter,  # Enables ordering by specified fields
    ]

    search_fields = ["name"]  # Fields that can be searched
    filterset_fields = ["is_active"]  # Fields that can be filtered
    ordering_fields = ["name", "id"]  # Fields that can be used for ordering

    # Default permission classes (may be overridden in get_permissions)
    permission_classes = [IsAuthenticated, IsEmployee]

    def get_permissions(self):
        """
        Get the permissions that should be enforced for the current action.

        For list and retrieve actions, only authentication is required.
        For all other actions (create, update, delete), the user must be
        a manager or superuser in addition to being authenticated.

        Returns:
            list: List of permission classes to enforce
        """
        if self.action in ["list", "retrieve"]:
            # For read-only actions, only require authentication
            return [IsAuthenticated()]

        # For write actions, require authentication and manager/superuser status
        return [permissions.IsAuthenticated(), IsManagerOrSuperuser()]

    def get_serializer_class(self):
        """
        Return the serializer class to use based on the current action.

        Different serializers are used for different views to optimize
        the data returned and the validation performed.

        Returns:
            class: The serializer class to use
        """
        if self.action == "list":
            # Use simplified serializer for list view
            return TopicListSerializer
        if self.action == "restore":
            # Use specialized serializer for restore action
            return TopicRestoreSerializer
        # Use full serializer for all other actions
        return TopicSerializer

    def get_queryset(self):
        """
        Get the queryset for the current action.

        For LIST action - filter by is_active (by default only active topics)
        For DETAIL actions (retrieve, update, destroy) - always all objects

        Returns:
            QuerySet: Filtered queryset of Topic objects
        """
        # Start with all topics
        queryset = Topic.objects.all()

        if self.action == "list":
            # Check if is_active filter is explicitly provided
            is_active_param = self.request.query_params.get("is_active")
            if is_active_param is None:
                # If not provided, default to showing only active topics
                queryset = queryset.filter(is_active=True)

        return queryset

    def perform_destroy(self, instance):
        """
        Perform soft deletion by marking the topic as inactive.

        Instead of actually deleting the topic from the database,
        this sets is_active=False to preserve the data while hiding
        it from normal views.

        Args:
            instance: The Topic instance to soft-delete
        """
        instance.is_active = False
        instance.save()

    @action(detail=True, methods=["get"])
    def recommended_questions(self, request, pk=None):
        """
        Custom action to get recommended questions for a topic.

        This endpoint returns a list of active questions for the specified topic,
        optionally excluding questions that are already used in a specific form.
        Questions are ordered by usage count (most used first) to recommend
        the most popular questions.

        Args:
            request: The HTTP request object
            pk: The primary key of the topic

        Returns:
            Response: List of serialized Question objects
        """
        # Get the topic object
        topic = self.get_object()

        # Get all active questions for this topic
        question_queryset = Question.objects.filter(topic=topic, is_active=True)

        # Check if we need to exclude questions already used in a form
        form_slug_to_exclude = request.query_params.get("exclude_form")
        if form_slug_to_exclude:
            # Get IDs of questions already used in the form
            used_question_ids = question_queryset.values_list(
                "origin_question_id", flat=True
            )
            # Exclude those questions from the results
            question_queryset = question_queryset.exclude(id__in=used_question_ids)

        # Order by usage count (descending) to show most popular questions first
        question_queryset = question_queryset.order_by("-usage_count")

        # Serialize and return the questions
        serializer = QuestionSerializer(question_queryset, many=True)
        return Response(serializer.data)

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
        Custom action to restore a previously soft-deleted topic.

        This endpoint sets is_active=True for a topic that was previously
        marked as inactive. It returns an error if the topic is already active.

        Args:
            request: The HTTP request object
            pk: The primary key of the topic to restore

        Returns:
            Response: Success message and serialized topic data, or error message
        """
        # Get the topic object
        instance = self.get_object()

        # Check if the topic is already active
        if instance.is_active:
            return Response(
                {"error": "Topic is already active"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Restore the topic by setting is_active=True
        instance.is_active = True
        instance.save()

        # Serialize and return the restored topic
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
        """
        List topics with optional filtering, searching, and ordering.

        This method is decorated with extend_schema to provide additional
        API documentation. It uses the parent class implementation but
        with the enhanced documentation.

        Args:
            request: The HTTP request object
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Response: List of serialized Topic objects
        """
        return super().list(request, *args, **kwargs)
