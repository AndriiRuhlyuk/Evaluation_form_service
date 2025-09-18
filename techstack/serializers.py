from rest_framework import serializers

from techstack.models import TechStack


class TechStackSerializer(serializers.ModelSerializer):
    """TechStack Serializer"""

    class Meta:
        model = TechStack
        fields = ("id", "name", "description", "is_active")


class TechStackListSerializer(serializers.ModelSerializer):
    """Techstack list serializer"""

    detail = serializers.SerializerMethodField()

    class Meta:
        model = TechStack
        fields = ("id", "name", "is_active", "detail")

    def get_detail(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/techstacks/{obj.pk}/")
        return f"/api/techstacks/{obj.pk}/"


class TechStackRestoreSerializer(serializers.ModelSerializer):
    """Serializer for restored techstack response"""

    class Meta:
        model = TechStack
        fields = ("id", "name", "is_active")
        read_only_fields = ("id", "name", "is_active", "description")
