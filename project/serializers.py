from rest_framework import serializers

from project.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    """
    Serializer for the Project model providing full representation.

    This serializer handles the conversion between Project model instances and their
    JSON representation for API responses and requests. It includes all fields needed
    for detailed project information.
    """

    class Meta:
        model = Project
        # All fields needed for complete project representation
        fields = ("id", "name", "description", "is_active")


class ProjectListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing Project instances with simplified representation.

    This serializer is optimized for list views, providing a more concise representation
    of projects with only essential fields and a link to the detailed view.
    """

    # Additional field that provides a URL to the detailed view of the project
    detail = serializers.SerializerMethodField()

    class Meta:
        model = Project
        # Simplified fields for list view with detail URL
        fields = ("id", "name", "is_active", "detail")

    def get_detail(self, obj):
        """
        Generate a URL to the detailed view of the project.

        Args:
            obj: The Project instance being serialized

        Returns:
            str: Absolute URL to the project detail endpoint if request is available,
                 otherwise a relative URL
        """
        # Get the request from the serializer context
        request = self.context.get("request")
        # If request is available, build an absolute URI
        if request:
            return request.build_absolute_uri(f"/api/projects/{obj.pk}/")
        # Otherwise return a relative URL
        return f"/api/projects/{obj.pk}/"


class ProjectRestoreSerializer(serializers.ModelSerializer):
    """
    Serializer for representing restored project responses.

    This serializer is specifically used when a soft-deleted project is restored
    to active status. It provides a read-only representation with limited fields.
    """

    class Meta:
        model = Project
        # Limited fields for restore response
        fields = ("id", "name", "is_active")
        # All fields are read-only as this serializer is only used for responses
        read_only_fields = ("id", "name", "is_active", "description")
