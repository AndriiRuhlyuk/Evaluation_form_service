from rest_framework import serializers
from rest_framework.reverse import reverse

from topic.models import Topic


class TopicSerializer(serializers.ModelSerializer):
    """
    Serializer for handling CRUD operations on Topic objects.

    This serializer provides full access to all Topic model fields and is used
    for creating, retrieving, updating, and deleting topic objects. It includes
    validation and proper field mapping for the Topic model.
    """

    class Meta:
        model = Topic  # The model this serializer is based on
        fields = (
            "id",  # Primary key of the topic
            "name",  # Name of the topic
            "description",  # Description of the topic
            "is_active",  # Active status flag
            "created_at",  # Creation timestamp
            "updated_at",  # Last update timestamp
        )
        read_only_fields = (
            "id",  # Auto-generated, should not be editable
            "created_at",  # Auto-generated on creation
            "updated_at",  # Auto-updated on save
        )


class TopicListSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying topics in dropdown lists and summary views.

    This serializer provides a simplified representation of Topic objects
    for use in UI components like dropdowns and list views. It includes
    a dynamic URL to the detail view of each topic.
    """

    # URL to the detail view of the topic
    detail = serializers.SerializerMethodField()

    class Meta:
        model = Topic  # The model this serializer is based on
        fields = (
            "id",  # Primary key of the topic
            "name",  # Name of the topic
            "detail",  # URL to the detail view
        )

    def get_detail(self, topic):
        """
        Generate a URL to the detail view of the topic.

        Args:
            topic: The Topic instance being serialized

        Returns:
            str: URL to the topic detail view, or None if request context is missing
        """
        # Get the request from the serializer context
        request = self.context.get("request")
        if request:
            # Generate a reverse URL to the topic detail view
            return reverse(
                "topic:topic-detail", kwargs={"pk": topic.pk}, request=request
            )
        return None


class TopicRestoreSerializer(serializers.ModelSerializer):
    """
    Serializer for representing restored topics after they've been reactivated.

    This serializer is specifically used when a previously deactivated topic
    is restored (is_active set to True). It provides a read-only view of the
    restored topic with a link to its detail page.
    """

    # URL to the detail view of the restored topic
    detail = serializers.SerializerMethodField()

    class Meta:
        model = Topic  # The model this serializer is based on
        fields = (
            "id",  # Primary key of the topic
            "name",  # Name of the topic
            "is_active",  # Active status flag (should be True for restored topics)
            "detail",  # URL to the detail view
        )
        read_only_fields = (
            "id",  # Auto-generated, should not be editable
            "name",  # Not editable in restore operation
            "is_active",  # Not editable in restore operation
            "detail",  # Generated field
        )

    def get_detail(self, obj):
        """
        Generate a URL to the detail view of the restored topic.

        Args:
            obj: The Topic instance being serialized

        Returns:
            str: URL to the topic detail view
        """
        # Get the request from the serializer context
        request = self.context.get("request")
        if request:
            # Generate an absolute URI to the topic detail view
            return request.build_absolute_uri(f"/api/topics/{obj.pk}/")
        # Fallback to a relative URL if request context is missing
        return f"/api/topics/{obj.pk}/"
