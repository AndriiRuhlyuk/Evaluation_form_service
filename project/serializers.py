from rest_framework import serializers

from project.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    """Project Serializer"""

    class Meta:
        model = Project
        fields = ("id", "name", "description", "is_active")


class ProjectListSerializer(serializers.ModelSerializer):
    """Project list serializer"""

    detail = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ("id", "name", "is_active", "detail")

    def get_detail(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/projects/{obj.pk}/")
        return f"/api/projects/{obj.pk}/"


class ProjectRestoreSerializer(serializers.ModelSerializer):
    """Serializer for restored project response"""

    class Meta:
        model = Project
        fields = ("id", "name", "is_active")
        read_only_fields = ("id", "name", "is_active", "description")
