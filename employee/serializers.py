from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework.exceptions import ValidationError

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


class LogoutSerializer(serializers.Serializer):
    """Logout serializer"""

    refresh = serializers.CharField(
        write_only=True,
        required=True,
        help_text="Refresh token to be blacklisted",
    )
    all_tokens = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set to true to blacklist all refresh tokens for the user",
    )

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)

            token_user_id = token.payload.get("user_id")
            authenticated_user_id = self.context["request"].user.id

            if int(token_user_id) != int(authenticated_user_id):
                raise ValidationError(
                    "Refresh token does not belong to the authenticated user"
                )

            token.verify()

        except TokenError as e:
            raise ValidationError("Invalid or expired refresh token")
        except (ValueError, TypeError):

            raise ValidationError("Invalid token format")
        except Exception as e:
            raise ValidationError("Token validation failed")

        return value
