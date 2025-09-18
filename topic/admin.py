from django.contrib import admin
from topic.models import Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name"]
    list_editable = ["is_active"]
    readonly_fields = ["created_at", "updated_at"]
