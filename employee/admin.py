from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext as _

from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(DjangoUserAdmin):

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "fullname")}),
        (_("Work info"), {"fields": ("role", "level", "project", "tech_stack")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "updated_at", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )
    list_display = (
        "id",
        "email",
        "fullname",
        "role",
        "level",
        "is_active",
        "updated_at",
    )
    list_filter = ("role", "level", "is_active", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "fullname")
    ordering = ("email",)
