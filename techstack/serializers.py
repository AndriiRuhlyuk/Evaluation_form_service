from rest_framework import serializers

from techstack.models import TechStack


class TechStackSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechStack
        fields = ("id", "name", "description")


class TechStackListSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechStack
        fields = ("id", "name")
