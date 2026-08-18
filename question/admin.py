from django.contrib import admin
from django.db import models
from unfold.contrib.forms.widgets import WysiwygWidget

from question.models import Question
from unfold.admin import ModelAdmin


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    """
    Admin configuration for the Question model.

    This class defines how Question objects are displayed, filtered, and edited
    in the Django admin interface. It uses the Unfold admin theme for enhanced UI.
    """

    # Fields to display in the list view of questions
    list_display = ("question_text", "difficulty", "usage_count", "topic")

    # Fields that can be searched in the admin interface
    search_fields = ("question_text", "topic__name")

    # Fields that can be used to filter the list of questions
    list_filter = ("difficulty", "topic__name", "source", "is_active", "topic")

    # Fields that cannot be edited in the admin interface
    readonly_fields = ("created_at", "updated_at", "question_author")

    # Override the default TextField widget with a rich text editor
    formfield_overrides = {
        models.TextField: {
            "widget": WysiwygWidget
        },  # Use WYSIWYG editor for question_text
    }
