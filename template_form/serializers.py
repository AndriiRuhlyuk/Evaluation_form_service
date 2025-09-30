from collections import defaultdict

from django.urls import reverse
from rest_framework import serializers

from .models import TemplateForm, TemplateFormItems
from techstack.models import TechStack
from topic.models import Topic
from .services import (
    create_template_form,
    update_template_form,
    _ensure_tech_stacks,
)


class TopicSerializer(serializers.ModelSerializer):
    """
    Serializer for a Topic.
    It is used as nested inside TemplateFormSerializer
    """

    class Meta:
        model = Topic
        fields = ("id", "name")


class TechStackRelatedField(serializers.RelatedField):
    """
    Serializer for custom field - TechStack (ID, dict, str).
    """

    def to_internal_value(self, data):
        """Redirect to service function"""

        return _ensure_tech_stacks(data)

    def to_representation(self, value: TechStack):
        """API response - tech stack name"""

        return value.name


class InputTopicSerializer(serializers.Serializer):
    """
    Validate data for topic inside item.
    It is used as nested inside InputTemplateFormItemSerializer
    """

    id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get("id") and not data.get("name"):
            raise serializers.ValidationError(
                "Either 'id' or 'name' must be provided for a topic."
            )
        return data


class InputTemplateFormItemSerializer(serializers.Serializer):
    """
    Validate structure one 'item'-s in input list.
    It is used as nested inside TemplateFormSerializer
    """

    origin_question = serializers.IntegerField(required=False)
    question_text = serializers.CharField(required=False)
    difficulty = serializers.IntegerField(required=False)

    def validate(self, data):
        is_existing = "origin_question" in data
        is_new = all(k in data for k in ["question_text", "difficulty", "topic"])
        if not is_existing and not is_new:
            raise serializers.ValidationError(
                "Provide either 'origin_question' or full data for a new question."
            )
        return data


class TopicWithQuestionsInputSerializer(serializers.Serializer):
    """
    Validate structure one 'item'-s in input list: { topic: {...}, questions: [...].
    """

    topic = InputTopicSerializer()
    questions = InputTemplateFormItemSerializer(many=True, min_length=1)


class TemplateFormSerializer(serializers.ModelSerializer):
    """
    Serializer for CREATE & UPDATE Template Form (Create/Update).
    Validate and Pass input data to service.py
    """

    topics_with_questions = TopicWithQuestionsInputSerializer(
        many=True, required=True, write_only=True
    )
    tech_stack = TechStackRelatedField(queryset=TechStack.objects.all())

    class Meta:
        model = TemplateForm
        fields = ("id", "name", "tech_stack", "topics_with_questions")

    def create(self, validated_data):
        manager = self.context["request"].user
        return create_template_form(manager=manager, validated_data=validated_data)

    def update(self, instance, validated_data):
        manager = self.context["request"].user
        return update_template_form(
            instance=instance, manager=manager, validated_data=validated_data
        )


class TemplateFormListSerializer(serializers.ModelSerializer):
    """Serializer for List TemplateForm."""

    tech_stack = serializers.StringRelatedField()
    topics_count = serializers.IntegerField(source="topics.count", read_only=True)
    items_count = serializers.SerializerMethodField()
    form_detail_url = serializers.SerializerMethodField()

    class Meta:
        model = TemplateForm
        fields = (
            "id",
            "name",
            "tech_stack",
            "topics_count",
            "items_count",
            "form_detail_url",
        )

    def get_items_count(self, instance):
        """Count only active items."""

        return instance.items.filter(is_removed=False).count()

    def get_form_detail_url(self, instance):
        """
        Generate URL for item detail view.
        """

        request = self.context.get("request")
        if not request:
            return None

        kwargs = {"slug": instance.slug}
        view_name = "template_form:template-form-detail"

        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class TemplateFormItemsListSerializer(serializers.ModelSerializer):
    """
    Serializer for output items list.
    It is used as nested inside TemplateFormDetailSerializer
    """

    item_detail_url = serializers.SerializerMethodField()

    class Meta:
        model = TemplateFormItems
        fields = ("id", "text_snapshot", "difficulty_snapshot", "item_detail_url")

    def get_item_detail_url(self, instance):
        """
        Generate URL for item detail view.
        """

        request = self.context.get("request")
        if not request:
            return None

        kwargs = {"form_slug": instance.form.slug, "pk": instance.pk}
        view_name = "template_form:form-items-detail"

        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class TemplateFormItemsDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for detail representation for one item.
    """

    origin_question = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TemplateFormItems
        fields = (
            "id",
            "text_snapshot",
            "difficulty_snapshot",
            "topic_snapshot",
            "max_score_snapshot",
            "origin_question",
            "is_removed",
        )
        read_only_fields = fields


class TemplateFormItemUpdateSerializer(serializers.ModelSerializer):
    """Serializer for update item fields"""

    class Meta:
        model = TemplateFormItems
        fields = (
            "text_snapshot",
            "difficulty_snapshot",
            "topic_snapshot",
        )

    def validate_difficulty_snapshot(self, value):
        """
        Validate difficulty snapshot (1-3)
        """
        if value not in [1, 2, 3]:
            raise serializers.ValidationError(
                "Difficulty snapshot must be 1 (Easy),  2(Medium), 3(Hard)."
            )
        return value

    def update(self, instance, validated_data):
        if "difficulty_snapshot" in validated_data:
            difficulty = validated_data["difficulty_snapshot"]
            instance.max_score_snapshot = difficulty * 3

        return super().update(instance, validated_data)


class TemplateFormDetailSerializer(serializers.ModelSerializer):
    """DETAIL TemplateForm Serializer."""

    tech_stack = serializers.StringRelatedField(read_only=True)
    topics_with_questions = serializers.SerializerMethodField()
    manager = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TemplateForm
        fields = (
            "id",
            "name",
            "manager",
            "tech_stack",
            "topics_with_questions",
            "created_at",
        )

    def get_items(self, instance):
        """Filter items by is_removed=False"""

        active_items = instance.items.filter(is_removed=False)
        return TemplateFormItemsListSerializer(
            active_items, many=True, context=self.context
        ).data

    def get_topics_with_questions(self, instance):
        """
        Take active questions and group it by topic
        """
        active_items = instance.items.filter(is_removed=False).select_related(
            "origin_question__topic"
        )
        grouped_items = defaultdict(list)
        for item in active_items:
            if item.origin_question and item.origin_question.topic:
                topic = item.origin_question.topic
                grouped_items[topic].append(item)

        result = []
        for topic, items_list in grouped_items.items():
            result.append(
                {
                    "topic": TopicSerializer(topic, context=self.context).data,
                    "questions": TemplateFormItemsListSerializer(
                        items_list, many=True, context=self.context
                    ).data,
                }
            )

        return result
