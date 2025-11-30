from django.contrib import admin
from django.db import models
from unfold.contrib.forms.widgets import WysiwygWidget

from question.models import Question
from unfold.admin import ModelAdmin


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_display = ("question_text", "difficulty", "usage_count", "topic")
    search_fields = ("question_text", "topic__name")
    list_filter = ("difficulty", "topic__name", "source", "is_active", "topic")
    readonly_fields = ("created_at", "updated_at", "question_author")

    formfield_overrides = {
        models.TextField: {"widget": WysiwygWidget},
    }
