from django.contrib import admin
from question.models import Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question_text", "difficulty", "is_active", "topic")
    search_fields = ("question_text",)
    list_filter = ("difficulty", "topic__name", "source", "is_active")
    readonly_fields = ("created_at", "updated_at")
