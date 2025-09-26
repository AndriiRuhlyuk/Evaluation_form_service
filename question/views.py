from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from permissions import IsEmployee

from question.models import Question
from question.serializers import (
    QuestionSerializer,
    QuestionListSerializer,
    QuestionDetailSerializer,
    QuestionRestoreSerializer,
)


class QuestionPagination(PageNumberPagination):
    """Pagination class for Question API"""

    page_size = 10
    max_page_size = 100


class QuestionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing questions used in candidate evaluation forms.

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
    - `DELETE /api/questions/{id}/` - Soft delete topic
    - `POST /api/questions/{id}/restore/` - Restore unactive question
    """

    queryset = Question.objects.select_related("topic", "question_author").order_by(
        "topic", "-difficulty", "created_at"
    )

    serializer_class = QuestionSerializer
    pagination_class = QuestionPagination
    filter_backends = (
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    )
    filterset_fields = {
        "topic": ["exact"],
        "topic__name": ["icontains"],
        "difficulty": ["exact"],
        "source": ["exact"],
        "is_active": ["exact"],
    }
    search_fields = ["question_text"]
    ordering_fields = ["difficulty", "usage_count"]
    permission_classes = [IsAuthenticated, IsEmployee]

    def get_serializer_class(self):
        if self.action == "list":
            return QuestionListSerializer
        if self.action == "retrieve":
            return QuestionDetailSerializer
        if self.action == "restore":
            return QuestionRestoreSerializer
        return QuestionSerializer

    def perform_create(self, serializer):
        """
        Temporary Automatically identifies the
        author of the question as the current user
        """
        serializer.save(question_author=self.request.user)

    def get_queryset(self):
        """
        For LIST - filter by is_active (by default only active)
        For DETAIL (retrieve, update, destroy) - always all objects
        """
        queryset = Question.objects.all()

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
        POST /api/question/{id}/restore/ - restore unactive question
        """
        instance = self.get_object()

        if instance.is_active:
            return Response(
                {"error": "Question is already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.is_active = True
        instance.save()

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
        return super().list(request, *args, **kwargs)
