from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import EvaluationForm


@admin.register(EvaluationForm)
class EvaluationFormAdmin(ModelAdmin):
    """
    Admin page for evaluation forms.

    Its primary purpose is soft-delete management: the changelist shows
    deleted forms (via `all_objects`) and the restore action is the only
    way to bring a soft-deleted form back. `report_file` is read-only so
    the report linked from the PeopleForce note cannot be replaced here;
    the standard admin delete stays available as the intentional
    hard-delete escape hatch.
    """

    list_display = (
        "name",
        "candidate",
        "status",
        "interview_datetime",
        "is_deleted",
    )
    list_select_related = ("candidate", "manager", "hiring_manager")
    search_fields = ("name", "candidate__full_name")
    list_filter = ("status", "is_deleted")
    readonly_fields = ("deleted_by", "deleted_at", "report_file")
    actions = ["restore_selected"]

    def get_queryset(self, request):
        """
        Uses `all_objects` so soft-deleted forms stay visible here:
        the admin is the only place a deleted form can be restored.
        """
        return EvaluationForm.all_objects.select_related(
            "candidate", "manager", "hiring_manager"
        )

    @admin.action(description="Restore selected (clear soft delete)")
    def restore_selected(self, request, queryset):
        """
        Clears the soft-delete flag and audit fields on selected forms.

        Deliberately a bulk `update()`: it bypasses `save()` and therefore
        the name/slug regeneration in `EvaluationForm.save()`, so a
        restored form keeps its identity.
        """
        queryset.update(is_deleted=False, deleted_by=None, deleted_at=None)
