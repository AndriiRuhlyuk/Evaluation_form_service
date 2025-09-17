from rest_framework import serializers

from techstack.models import TechStack


class TechStackSerializer(serializers.ModelSerializer):
    """TechStack Serializer"""

    class Meta:
        model = TechStack
        fields = ("id", "name", "description")


class TechStackListSerializer(serializers.ModelSerializer):
    """Techstack list serializer"""

    class Meta:
        model = TechStack
        fields = ("id", "name")
