from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import WorkingForm


@admin.register(WorkingForm)
class WorkingFormAdmin(ModelAdmin):
    """
    Admin page for working forms.

    Its primary purpose is soft-delete management: the changelist shows
    deleted forms (via `all_objects`) and the restore action is the only
    way to bring a soft-deleted form back. The standard admin delete
    stays available as the intentional hard-delete escape hatch.
    """

    list_display = (
        "name",
        "vacancy",
        "level",
        "project",
        "status",
        "created_at",
        "is_deleted",
    )
    list_select_related = ("project", "tech_stack", "hiring_manager")
    search_fields = ("name", "vacancy")
    list_filter = ("status", "level", "is_deleted")
    readonly_fields = ("deleted_by", "deleted_at")
    actions = ["restore_selected"]

    def get_queryset(self, request):
        """
        Uses `all_objects` so soft-deleted forms stay visible here:
        the admin is the only place a deleted form can be restored.
        """
        return WorkingForm.all_objects.select_related(
            "project", "tech_stack", "hiring_manager"
        )

    @admin.action(description="Restore selected (clear soft delete)")
    def restore_selected(self, request, queryset):
        """
        Clears the soft-delete flag and audit fields on selected forms.

        Deliberately a bulk `update()`: it bypasses `save()`, which for
        WorkingForm regenerates name/slug on a full save of an existing
        object, so a restored form keeps its identity.
        """
        queryset.update(is_deleted=False, deleted_by=None, deleted_at=None)
