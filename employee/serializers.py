from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class EmployeeSerializer(serializers.ModelSerializer):
    """Employee serializer"""

    password = serializers.CharField(
        write_only=True,
        min_length=5,
        style={"input_type": "password"},
        trim_whitespace=False,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "fullname",
            "role",
            "level",
            "project",
            "tech_stack",
            "is_active",
            "updated_at",
        )
        read_only_fields = ("is_active", "updated_at", "fullname")

        extra_kwargs = {"password": {"write_only": True, "min_length": 5}}

    def create(self, validated_data):
        """Create a new user with encrypted password and return it"""
        password = validated_data.pop("password")
        user = User.objects.create(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        """Update a user, set the password correctly and return it"""
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user
