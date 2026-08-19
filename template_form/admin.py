from django.contrib import admin
from django.utils.html import strip_tags
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline, StackedInline

from employee.admin_mixins import ManagerPermissionMixin
from question.models import Question
from .models import (
    TemplateForm,
    TemplateFormTopic,
    TemplateFormItems,
    ReadOnlyTemplateForm,
    ReadOnlyFormTopic,
)
from .services import populate_snapshot_from_question, SNAPSHOT_FIELDS


# --- INLINES ---


class TemplateFormItemsInline(ManagerPermissionMixin, TabularInline):
    """
    An inline panel for managing question snapshots (`TemplateFormItems`).

    Displayed on the `TemplateFormTopicAdmin` edit page. Allows adding,
    removing, and editing questions that belong to a specific topic within
    a form template. Uses an AJAX request to autofill the `text_snapshot`
    and `difficulty_snapshot` fields when an `origin_question` is selected.
    """

    model = TemplateFormItems
    extra = 0
    fields = (
        "origin_question",
        "text_snapshot",
        "difficulty_snapshot",
        "is_removed",
    )

    readonly_fields = ("topic_snapshot", "source_snapshot", "max_score_snapshot")
    autocomplete_fields = ("origin_question",)

    def get_formset(self, request, obj=None, **kwargs):
        """
        Optimizes the database query for the `origin_question` field.

        Uses `select_related("topic")` to load the related topic in a single query,
        avoiding the N+1 query problem when saving the formset.

        Returns:
            FormSet: The formset class with the optimized `origin_question` field.
        """
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.base_fields["origin_question"].queryset = formset.form.base_fields[
            "origin_question"
        ].queryset.select_related("topic")
        return formset

    def get_queryset(self, request):
        """
        Filters the queryset to display only active items.

        Returns only `TemplateFormItems` with `is_removed=False`.
        Also uses `select_related` to optimize loading of the related
        `Question` and `Topic` models.

        Returns:
            QuerySet: The filtered and optimized queryset.
        """
        queryset = super().get_queryset(request)

        return queryset.filter(is_removed=False).select_related(
            "origin_question", "form_topic__topic"
        )


class FormTopicInline(ManagerPermissionMixin, StackedInline):
    """
    An inline panel for managing topics (`TemplateFormTopic`) within a form template.

    Displayed on the main `TemplateFormAdmin` page. Allows adding or removing
    topics that belong to the form.
    """

    model = TemplateFormTopic
    extra = 0
    fields = ("topic", "manage_questions_link")
    readonly_fields = ("manage_questions_link",)
    ordering = ("topic__id",)

    @admin.display(description="Questions")
    def manage_questions_link(self, obj):
        """
        Creates a link to navigate to the topic's question management page.

        If the object has not been saved yet displays a message. Otherwise,
        generates an HTML link that leads to the `TemplateFormTopicAdmin` page
        for the corresponding topic.

        Returns:
            str: An HTML button or a text message.
        """
        if not obj.pk:
            return "Save before add questions"
        url = reverse("admin:template_form_templateformtopic_change", args=[obj.pk])
        return format_html(
            f'<a href="{url}" class="button button-secondary button-sm">Manage questions</a>'
        )


# --- MAIN ADMIN CLASSES ---


@admin.register(TemplateFormTopic)
class TemplateFormTopicAdmin(ManagerPermissionMixin, ModelAdmin):
    """
    The admin page for managing a single topic within a form template.

    This page is where the main work with topic questions takes place:
    adding, editing, and removing them via `TemplateFormItemsInline`.
    It also contains custom logic for saving the formset.
    """

    inlines = [TemplateFormItemsInline]
    readonly_fields = ("form", "topic")

    def get_queryset(self, request):
        """
        Optimizes loading of the related `form` and `topic` objects.

        Uses `select_related` to avoid the N+1 query problem during
        formset save processing.

        Returns:
            QuerySet: The optimized queryset.
        """
        return super().get_queryset(request).select_related("form", "topic")

    def has_module_permission(self, request):
        """
        Hides this model from the main admin dashboard.

        Managing form topics should be done through the form's own page,
        so direct access to the `TemplateFormTopic` list is not needed.

        Returns:
            bool: Always False.
        """

        return False

    def save_formset(self, request, form, formset, change):
        """
        Custom logic for saving question "snapshots" (TemplateFormItems).

        This method handles three main scenarios:
        1. Creating a new Question "on the fly" if the user fills in the
           `text_snapshot` but does not select an `origin_question`.
        2. Linking an existing Question selected from the autocomplete field.
        3. Updating existing snapshots.

        It uses a database transaction and bulk operations (`bulk_create`,
        `bulk_update`) for efficiency.
        """
        instances = formset.save(commit=False)

        snapshots_to_update = []
        snapshots_for_new_questions = []
        snapshots_for_existing_questions = []
        questions_to_create = []
        snapshot_parents_for_new_questions = []

        with transaction.atomic():
            for obj in formset.deleted_objects:
                if obj.pk:
                    obj.delete()

            for instance in instances:
                if instance.pk is None:
                    # Scenario: create a new question on the fly
                    if not instance.origin_question and instance.text_snapshot:
                        snapshots_for_new_questions.append(instance)
                    # Scenario: add an existing question
                    elif instance.origin_question:
                        snapshots_for_existing_questions.append(instance)
                else:
                    # Scenario: update an existing snapshot
                    snapshots_to_update.append(instance)

            # Prepare new questions for creation
            for snapshot in snapshots_for_new_questions:
                difficulty = (
                    snapshot.difficulty_snapshot or Question.QuestionDifficulty.EASY
                )
                clean_text = strip_tags(snapshot.text_snapshot)
                new_question = Question(
                    question_text=clean_text,
                    difficulty=difficulty,
                    topic=snapshot.form_topic.topic,
                    question_author=request.user,
                    source=Question.QuestionSource.TEMPLATE,
                )
                questions_to_create.append(new_question)
                snapshot_parents_for_new_questions.append(snapshot)

            # Bulk create new questions
            if questions_to_create:
                created_questions = Question.objects.bulk_create(questions_to_create)

                for created_question, parent_snapshot in zip(
                    created_questions, snapshot_parents_for_new_questions
                ):
                    parent_snapshot.origin_question = created_question

            # Combine snapshots for both new and existing questions
            final_snapshots_to_create = (
                snapshots_for_new_questions + snapshots_for_existing_questions
            )

            # Bulk create snapshots
            if final_snapshots_to_create:
                for snapshot in final_snapshots_to_create:
                    populate_snapshot_from_question(snapshot, request.user)
                TemplateFormItems.objects.bulk_create(final_snapshots_to_create)

            # Bulk update snapshots
            if snapshots_to_update:
                for snapshot in snapshots_to_update:
                    if snapshot.origin_question:
                        populate_snapshot_from_question(snapshot)
                update_fields = SNAPSHOT_FIELDS + ["is_removed", "origin_question"]
                TemplateFormItems.objects.bulk_update(
                    snapshots_to_update, update_fields
                )


@admin.register(TemplateForm)
class TemplateFormAdmin(ManagerPermissionMixin, ModelAdmin):
    """Main admin page for managing form templates (TemplateForm)."""

    list_display = (
        "name",
        "tech_stack",
        "manager",
        "created_at",
        "is_deleted",
        "view_on_site_link",
    )
    list_select_related = ("tech_stack", "manager")
    search_fields = ("name", "tech_stack__name")
    list_filter = ("tech_stack", "is_deleted")
    inlines = [FormTopicInline]
    readonly_fields = ("manager", "deleted_by", "deleted_at")
    prepopulated_fields = {"slug": ("name",)}
    actions = ["restore_selected"]

    def get_queryset(self, request):
        """
        Uses `all_objects` so soft-deleted templates stay visible here:
        the admin is the only place a deleted form can be restored.
        """
        return TemplateForm.all_objects.all()

    @admin.action(description="Restore selected (clear soft delete)")
    def restore_selected(self, request, queryset):
        """
        Clears the soft-delete flag and audit fields on selected templates.

        Deliberately a bulk `update()`: it bypasses `save()` and therefore
        any name/slug regeneration, so a restored form keeps its identity.
        """
        queryset.update(is_deleted=False, deleted_by=None, deleted_at=None)

    @admin.display(description="View page")
    def view_on_site_link(self, obj):
        """
        Creates a link to the read-only view page of the template.

        If the object is not yet saved, no link is generated. Otherwise, it
        points to the `ReadOnlyTemplateFormAdmin` page.

        Returns:
            str: An HTML link or a text message.
        """
        if not obj.slug:
            return "Save to take a link"
        url = reverse("admin:template_form_readonlytemplateform_change", args=[obj.id])
        return format_html(
            '<a href="{}" target="_blank" class="text-primary-600 hover:text-primary-800">View</a>',
            url,
        )

    def save_model(self, request, obj, form, change):
        """
        Assigns the current user as the manager when creating a new template.
        """
        if not obj.pk:
            obj.manager = request.user
        super().save_model(request, obj, form, change)


# --- READ-ONLY ADMIN CLASSES (Two Level: Form+Topic / Topic+Snapshots) ---


class ReadOnlyTemplateFormItemsInline(TabularInline):
    """
    Inline panel for displaying questions in read-only mode.

    Used on the `ReadOnlyFormTopicAdmin` page to show a list of questions
    belonging to a topic, without allowing any edits.
    """

    model = TemplateFormItems
    extra = 0
    fields = (
        "text_snapshot",
        "difficulty_snapshot",
        "source_snapshot",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        """Disables adding new objects."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disables deleting objects."""
        return False

    def get_queryset(self, request):
        """Shows only active (not removed) questions."""
        queryset = super().get_queryset(request)

        return queryset.filter(is_removed=False)

    def has_view_permission(self, request, obj=None):
        """Allows viewing for authenticated users."""
        return request.user.is_authenticated


@admin.register(ReadOnlyFormTopic)
class ReadOnlyFormTopicAdmin(ModelAdmin):
    """
    Admin page for viewing a topic and its questions in read-only mode.

    Uses `ReadOnlyTemplateFormItemsInline` to display the questions.
    All data modification actions are disabled.
    """

    inlines = [ReadOnlyTemplateFormItemsInline]
    readonly_fields = ("form", "topic")

    def has_add_permission(self, request):
        """Disables creating new objects."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disables editing."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disables deleting."""
        return False

    def has_view_permission(self, request, obj=None):
        """Allows viewing for authenticated users."""
        return request.user.is_authenticated

    def has_module_permission(self, request):
        """Hides this model from the main admin dashboard."""
        return False


class ReadOnlyFormTopicInline(StackedInline):
    """
    Inline panel for displaying topics in read-only mode.

    Used on the `ReadOnlyTemplateFormAdmin` page to show a list of topics
    belonging to a template, with links to view their respective questions.
    """

    model = TemplateFormTopic
    extra = 0
    fields = ("topic", "view_questions_link")
    readonly_fields = ("topic", "view_questions_link")

    @admin.display(description="Questions")
    def view_questions_link(self, obj):
        """Creates a link to the topic's read-only question view page."""
        if not obj.pk:
            return "---"

        url = reverse("admin:template_form_readonlyformtopic_change", args=[obj.pk])
        return format_html(f'<a href="{url}" class="button">View questions</a>')

    def has_add_permission(self, request, obj=None):
        """Disables adding."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disables deleting."""
        return False

    def has_view_permission(self, request, obj=None):
        """Allows viewing for authenticated users."""
        return request.user.is_authenticated


@admin.register(ReadOnlyTemplateForm)
class ReadOnlyTemplateFormAdmin(ModelAdmin):
    """
    Main page for viewing a form template in read-only mode.

    Uses the `ReadOnlyTemplateForm` proxy model and `ReadOnlyFormTopicInline`
    to provide a comprehensive overview of a template without allowing
    any modifications.
    """

    inlines = [ReadOnlyFormTopicInline]
    readonly_fields = ("name", "tech_stack", "manager", "slug")

    def get_queryset(self, request):
        """
        Uses `all_objects` so the read-only view keeps working for
        soft-deleted templates (e.g. via the link from the main admin list).
        """
        return ReadOnlyTemplateForm.all_objects.all()

    def has_add_permission(self, request):
        """Disables creation."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disables editing."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disables editing."""
        return False

    def has_view_permission(self, request, obj=None):
        """Allows viewing for authenticated users."""
        return request.user.is_authenticated

    def has_module_permission(self, request):
        """Hides this model from the main admin dashboard."""
        return False
