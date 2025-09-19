from rest_framework import serializers
from rest_framework.reverse import reverse

from topic.models import Topic


class TopicSerializer(serializers.ModelSerializer):
    """Serializer for CRUD topic object"""

    class Meta:
        model = Topic
        fields = (
            "id",
            "name",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TopicListSerializer(serializers.ModelSerializer):
    """Serializer for dropdown topic object"""

    detail = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = (
            "id",
            "name",
            "detail",
        )

    def get_detail(self, topic):
        request = self.context.get("request")
        if request:
            return reverse(
                "topic:topic-detail", kwargs={"pk": topic.pk}, request=request
            )
        return None


class TopicRestoreSerializer(serializers.ModelSerializer):
    """Serializer for restored topic response"""

    detail = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = ("id", "name", "is_active", "detail")
        read_only_fields = ("id", "name", "is_active", "detail")

    def get_detail(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/topics/{obj.pk}/")
        return f"/api/topics/{obj.pk}/"
