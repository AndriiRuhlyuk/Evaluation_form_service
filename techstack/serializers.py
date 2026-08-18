from rest_framework import serializers

from techstack.models import TechStack


class TechStackSerializer(serializers.ModelSerializer):
    """
    TechStack Serializer for detailed representation of technology stacks.

    This serializer provides a complete representation of a TechStack instance,
    including all fields (id, name, description, is_active). It is used for
    detail views, creation, and updates.
    """

    class Meta:
        model = TechStack
        fields = (
            "id",
            "name",
            "description",
            "is_active",
        )  # All fields of the TechStack model


class TechStackListSerializer(serializers.ModelSerializer):
    """
    TechStack List Serializer for concise representation in list views.

    This serializer provides a simplified representation of TechStack instances
    for list views, including only essential fields and a detail URL. It optimizes
    response size while providing navigation links to detailed views.
    """

    detail = (
        serializers.SerializerMethodField()
    )  # URL to the detail view of this tech stack

    class Meta:
        model = TechStack
        fields = ("id", "name", "is_active", "detail")  # Limited fields for list view

    def get_detail(self, obj):
        """
        Generates a URL to the detail view of this tech stack.

        Args:
            obj (TechStack): The TechStack instance

        Returns:
            str: Absolute URL to the tech stack detail endpoint if request context is available,
                 otherwise a relative URL
        """
        request = self.context.get(
            "request"
        )  # Get the request from context if available
        if request:
            return request.build_absolute_uri(
                f"/api/techstacks/{obj.pk}/"
            )  # Absolute URL with domain
        return f"/api/techstacks/{obj.pk}/"  # Relative URL as fallback


class TechStackRestoreSerializer(serializers.ModelSerializer):
    """
    Serializer for representing restored tech stack responses.

    This serializer is used specifically for the response when a soft-deleted
    tech stack is restored. It includes only the essential fields needed to
    confirm the restoration was successful, with all fields being read-only
    since this is used only for responses, not for accepting input.
    """

    class Meta:
        model = TechStack
        fields = (
            "id",
            "name",
            "is_active",
        )  # Essential fields for restoration confirmation
        read_only_fields = (
            "id",
            "name",
            "is_active",
            "description",
        )  # All fields are read-only
