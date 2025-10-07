from rest_framework import serializers
from rest_framework.reverse import reverse

from question.models import Question


class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for question objects."""

    class Meta:
        model = Question
        fields = (
            "id",
            "question_text",
            "topic",
            "difficulty",
        )


class QuestionListSerializer(serializers.ModelSerializer):
    """Serializer for list of questions."""

    detail = serializers.SerializerMethodField()
    topic_name = serializers.CharField(source="topic.name")

    class Meta:
        model = Question
        fields = (
            "id",
            "question_text",
            "topic_name",
            "difficulty",
            "source",
            "usage_count",
            "detail",
        )

    def get_detail(self, obj):
        request = self.context.get("request")
        return reverse(
            "question:question-detail", kwargs={"pk": obj.pk}, request=request
        )


class QuestionDetailSerializer(serializers.ModelSerializer):
    """Serializer for question detail."""

    topic_name = serializers.CharField(source="topic.name")

    class Meta:
        model = Question
        fields = (
            "id",
            "question_text",
            "topic_name",
            "difficulty",
            "source",
            "is_active",
            "usage_count",
            "question_author",
            "created_at",
            "updated_at",
        )


class QuestionRestoreSerializer(serializers.ModelSerializer):
    """Serializer for question restore."""

    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = Question
        fields = ("id", "question_text", "is_active", "topic_name", "difficulty")
        read_only_fields = (
            "id",
            "question_text",
            "is_active",
            "topic_name",
            "difficulty",
        )
