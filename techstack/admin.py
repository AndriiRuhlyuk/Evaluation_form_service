from django.contrib import admin
from .models import TechStack


@admin.register(TechStack)
class TechStackAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    list_editable = ["is_active"]
