from rest_framework import serializers
from rest_framework.reverse import reverse

from question.models import Question


class QuestionSerializer(serializers.ModelSerializer):
    """
    Base serializer for Question objects.

    This serializer is used for creating and updating Question objects.
    It includes only the essential fields needed for these operations.
    """

    class Meta:
        model = Question
        fields = (
            "id",  # Primary key
            "question_text",  # The actual question content
            "topic",  # Foreign key to Topic model
            "difficulty",  # Difficulty level (1-3)
        )


class QuestionListSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying questions in list views.

    This serializer is optimized for list views, including additional fields
    like source and usage_count, and a hyperlink to the detail view.
    It also converts the topic foreign key to its string representation.
    """

    # Add a hyperlink to the detail view of each question
    detail = serializers.SerializerMethodField()

    # Convert the topic foreign key to its string representation
    topic = serializers.StringRelatedField()

    class Meta:
        model = Question
        fields = (
            "id",  # Primary key
            "question_text",  # The actual question content
            "topic",  # String representation of the topic
            "difficulty",  # Difficulty level (1-3)
            "source",  # Source of the question (template, manual, etc.)
            "usage_count",  # Number of times the question has been used
            "detail",  # URL to the detail view
        )

    def get_detail(self, obj):
        """
        Generate a URL to the detail view for this question.

        Args:
            obj: The Question instance

        Returns:
            str: Absolute URL to the question detail endpoint
        """
        request = self.context.get("request")
        return reverse(
            "question:question-detail", kwargs={"pk": obj.pk}, request=request
        )


class QuestionDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for the detailed view of a question.

    This serializer includes all relevant fields for displaying a single question
    in detail, including metadata like creation date and author. It also includes
    the topic name directly rather than just the ID.
    """

    # Include the topic name directly instead of just the ID
    topic_name = serializers.CharField(source="topic.name")

    class Meta:
        model = Question
        fields = (
            "id",  # Primary key
            "question_text",  # The actual question content
            "topic_name",  # Name of the topic (not just ID)
            "difficulty",  # Difficulty level (1-3)
            "source",  # Source of the question (template, manual, etc.)
            "is_active",  # Whether the question is active or soft-deleted
            "usage_count",  # Number of times the question has been used
            "question_author",  # User who created the question
            "created_at",  # When the question was created
            "updated_at",  # When the question was last updated
        )


class QuestionRestoreSerializer(serializers.ModelSerializer):
    """
    Serializer for restoring soft-deleted questions.

    This serializer is used specifically for the restore action. It includes
    only the fields needed to confirm a successful restoration, and marks all
    fields as read-only since this operation doesn't accept any input data.
    """

    # Include the topic name directly instead of just the ID
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = Question
        fields = (
            "id",  # Primary key
            "question_text",  # The actual question content
            "is_active",  # Whether the question is active (should be True after restore)
            "topic_name",  # Name of the topic
            "difficulty",  # Difficulty level (1-3)
        )
        # All fields are read-only because this serializer is only used for output
        read_only_fields = (
            "id",
            "question_text",
            "is_active",
            "topic_name",
            "difficulty",
        )
