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
    It is used as nested inside TemplateFormDetailSerializer
    for group questions by topic (get_topics_with_questions)
    """

    class Meta:
        model = Topic
        fields = ("id", "name")


class TechStackRelatedField(serializers.RelatedField):
    """
    Serializer for custom field - TechStack (ID, dict, str).
    Call _ensure_tech_stacks for take TechStack instance.
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
    It is used as nested inside TopicWithQuestionsInputSerializer
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
    It is used as nested inside TopicWithQuestionsInputSerializer
    """

    origin_question = serializers.IntegerField(required=False)
    question_text = serializers.CharField(required=False)
    difficulty = serializers.IntegerField(required=False)

    def validate(self, data):
        is_existing = "origin_question" in data
        is_new = all(k in data for k in ["question_text", "difficulty"])
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
    Validate internal serializer - TopicWithQuestionsInputSerializer
    Pass validated data to service.py (create_template_form / update_template_form)
    for crete/update Template Form instance.
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
    items_count = serializers.IntegerField(source="active_items_count", read_only=True)
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

        view_name = "template_form:form-items-detail"
        kwargs = {
            "form_topic__form_slug": instance.form_topic.form.slug,
            "pk": instance.pk,
        }

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

    def get_topics_with_questions(self, instance):
        """
        Group prefetched active questions by topics
        """
        grouped_items = defaultdict(list)

        for form_topic in instance.form_topics.all():
            for item in form_topic.items.all():

                if not item.is_removed:

                    grouped_items[form_topic.topic].append(item)

        sorted_grouped_items = dict(
            sorted(grouped_items.items(), key=lambda x: x[0].name)
        )

        result = []
        for topic, items_list in sorted_grouped_items.items():
            result.append(
                {
                    "topic": TopicSerializer(topic, context=self.context).data,
                    "questions": TemplateFormItemsListSerializer(
                        items_list, many=True, context=self.context
                    ).data,
                }
            )

        return result
