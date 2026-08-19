from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext as _

from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(DjangoUserAdmin):
    """
    Admin configuration for the Employee model.
    Extends Django's UserAdmin with customizations for the Employee model.
    Configures how Employee objects are displayed and edited in the Django admin interface.
    """

    # Define the fields to be displayed in the admin form, grouped into sections
    fieldsets = (
        (None, {"fields": ("email",)}),  # Email field section
        (
            _("Personal info"),  # Personal information section
            {
                "fields": (
                    "first_name",  # Employee's first name
                    "last_name",  # Employee's last name
                )
            },
        ),
        (
            _("Work info"),  # Work-related information section
            {
                "fields": (
                    "role",  # Employee's role in the organization
                    "level",  # Employee's experience level
                )
            },
        ),
        # Password field section
        (None, {"fields": ("password",)}),
        (
            _("Permissions"),  # Permissions section
            {
                "fields": (
                    "is_active",  # Whether the employee account is active
                    "is_staff",  # Whether the employee can access the admin site
                    "is_superuser",  # Whether the employee has all permissions
                    "groups",  # The groups the employee belongs to
                    "user_permissions",  # Specific permissions for the employee
                )
            },
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "updated_at", "date_joined")},
        ),  # Dates section
    )

    # Define the fields to be displayed when adding a new employee
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),  # CSS class for styling
                "fields": (
                    "email",  # Email address for login
                    "password",  # Password field
                    "password2",  # Password confirmation field
                    "is_staff",  # Admin site access
                    "is_superuser",  # All permissions flag
                ),
            },
        ),
    )

    # Fields to display in the list view
    list_display = (
        "id",  # Employee ID
        "fullname",  # Full name (first + last)
        "email",  # Email address
        "role",  # Role in organization
        "level",  # Experience level
        "is_active",  # Active status
        "updated_at",  # Last update timestamp
    )

    # Fields that cannot be edited
    readonly_fields = ("last_login", "date_joined", "updated_at", "fullname")

    # Fields to filter the list by
    list_filter = ("role", "level", "is_active", "is_staff", "is_superuser")

    # Fields to search by
    search_fields = ("email", "first_name", "last_name")

    # Default ordering
    ordering = ("email",)
