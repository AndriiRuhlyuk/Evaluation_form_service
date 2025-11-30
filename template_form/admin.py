from django.contrib import admin
from django.utils.html import strip_tags
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline, StackedInline

from question.models import Question
from .models import (
    TemplateForm,
    TemplateFormTopic,
    TemplateFormItems,
    ReadOnlyTemplateForm,
    ReadOnlyFormTopic,
)


# --- INLINES ---


class TemplateFormItemsInline(TabularInline):
    """
    Inline for snapshots, that  represented on TemplateFormAdmin page.
    Use AJAX-request to js-helper for autocomplete fields:
    - text_snapshot
    - difficulty_snapshot
    that call service.get_question_details()
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
        Optimisation: Load 'origin_question',
        :exception avoid  N+1 request in 'save_formset'.
        """
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.base_fields["origin_question"].queryset = formset.form.base_fields[
            "origin_question"
        ].queryset.select_related("topic")
        return formset

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        return queryset.filter(is_removed=False).select_related(
            "origin_question", "form_topic__topic"
        )


class FormTopicInline(StackedInline):
    """Inline for topics, that represented on TemplateFormAdmin page."""

    model = TemplateFormTopic
    extra = 0
    fields = ("topic", "manage_questions_link")
    readonly_fields = ("manage_questions_link",)
    ordering = ("topic__id",)

    @admin.display(description="Questions")
    def manage_questions_link(self, obj):
        if not obj.pk:
            return "Save before add questions"
        url = reverse("admin:template_form_templateformtopic_change", args=[obj.pk])
        return format_html(
            f'<a href="{url}" class="button button-secondary button-sm">Manage questions</a>'
        )


# --- MAIN ADMIN CLASSES ---


@admin.register(TemplateFormTopic)
class TemplateFormTopicAdmin(ModelAdmin):
    """
    Page for manage TemplateFormTopic instance and questions.
    Logic to save TemplateFormItems.
    """

    inlines = [TemplateFormItemsInline]
    readonly_fields = ("form", "topic")

    def get_queryset(self, request):
        """
        Optimisation: Load 'form' and 'topic',
        to avoid N+1 request in 'save_formset'.
        """
        return super().get_queryset(request).select_related("form", "topic")

    def has_module_permission(self, request):
        return False

    def save_formset(self, request, form, formset, change):

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
                    if not instance.origin_question and instance.text_snapshot:
                        snapshots_for_new_questions.append(instance)
                    elif instance.origin_question:
                        snapshots_for_existing_questions.append(instance)
                else:
                    snapshots_to_update.append(instance)

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

            if questions_to_create:
                created_questions = Question.objects.bulk_create(questions_to_create)

                for created_question, parent_snapshot in zip(
                    created_questions, snapshot_parents_for_new_questions
                ):
                    parent_snapshot.origin_question = created_question

            final_snapshots_to_create = (
                snapshots_for_new_questions + snapshots_for_existing_questions
            )

            if final_snapshots_to_create:
                for snapshot in final_snapshots_to_create:
                    snapshot.text_snapshot = snapshot.origin_question.question_text
                    snapshot.difficulty_snapshot = snapshot.origin_question.difficulty
                    snapshot.added_by = request.user
                    snapshot.max_score_snapshot = snapshot.origin_question.max_score
                    snapshot.source_snapshot = snapshot.origin_question.source
                    snapshot.topic_snapshot = snapshot.form_topic.topic
                TemplateFormItems.objects.bulk_create(final_snapshots_to_create)

            if snapshots_to_update:
                for snapshot in snapshots_to_update:
                    snapshot.max_score_snapshot = snapshot.origin_question.max_score
                    snapshot.source_snapshot = snapshot.origin_question.source
                    snapshot.topic_snapshot = snapshot.form_topic.topic
                update_fields = [
                    "text_snapshot",
                    "difficulty_snapshot",
                    "max_score_snapshot",
                    "is_removed",
                    "origin_question",
                    "topic_snapshot",
                    "source_snapshot",
                ]
                TemplateFormItems.objects.bulk_update(
                    snapshots_to_update, update_fields
                )


@admin.register(TemplateForm)
class TemplateFormAdmin(ModelAdmin):
    """Main admin panel page for TemplateForm."""

    list_display = ("name", "tech_stack", "manager", "created_at", "view_on_site_link")
    search_fields = ("name", "tech_stack__name")
    list_filter = ("tech_stack",)
    inlines = [FormTopicInline]
    readonly_fields = ("manager",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="View page")
    def view_on_site_link(self, obj):
        if not obj.slug:
            return "Save to take a link"
        url = reverse("admin:template_form_readonlytemplateform_change", args=[obj.id])
        icon_svg = """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 mr-1 inline-block">
                <path d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
                <path fill-rule="evenodd" d="M.664 10.59a1.651 1.651 0 0 1 0-1.18l3.423-3.423a1.651 1.651 0 0 1 2.334 0L10 9.393a1.651 1.651 0 0 1 2.334 0l3.579-3.579a1.651 1.651 0 0 1 2.334 0l3.423 3.423a1.651 1.651 0 0 1 0 1.18l-3.423 3.423a1.651 1.651 0 0 1-2.334 0L10 10.607a1.651 1.651 0 0 1-2.334 0L4.086 14.21a1.651 1.651 0 0 1-2.334 0L.664 10.59Z" clip-rule="evenodd" />
            </svg>
        """
        return format_html(
            f"""
                    <a href="{url}" target="_blank"
                       class="flex items-center text-primary-600 hover:text-primary-800 font-semibold">
                       {icon_svg}
                       View
                    </a>
                    """
        )

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.manager = request.user
        super().save_model(request, obj, form, change)


# --- READ-ONLY ADMIN CLASSES (Two Level: Form+Topic / Topic+Snapshots) ---


class ReadOnlyTemplateFormItemsInline(TabularInline):
    """
    Inline for snapshot questions, for ReadOnlyFormTopicAdmin page.
    Used for represented question in ReadOnlyFormTopicAdmin
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
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        return queryset.filter(is_removed=False)


@admin.register(ReadOnlyFormTopic)
class ReadOnlyFormTopicAdmin(ModelAdmin):
    """
    Admin panel page for one topic.
    """

    inlines = [ReadOnlyTemplateFormItemsInline]
    readonly_fields = ("form", "topic")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return False  # Ховаємо з головної


class ReadOnlyFormTopicInline(StackedInline):
    """
    Inline for topics list, for ReadOnlyTemplateFormAdmin page.
    Used for represented topics in ReadOnlyTemplateFormAdmin
    """

    model = TemplateFormTopic
    extra = 0
    fields = ("topic", "view_questions_link")
    readonly_fields = ("topic", "view_questions_link")

    @admin.display(description="Questions")
    def view_questions_link(self, obj):
        if not obj.pk:
            return "---"

        url = reverse("admin:template_form_readonlyformtopic_change", args=[obj.pk])
        return format_html(f'<a href="{url}" class="button">View questions</a>')

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReadOnlyTemplateForm)
class ReadOnlyTemplateFormAdmin(ModelAdmin):
    """
    Main admin page for ReadOnly TemplateForm.
    """

    inlines = [ReadOnlyFormTopicInline]
    readonly_fields = ("name", "tech_stack", "manager", "slug")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return False
