from django.contrib import admin
from django.db import models
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import WysiwygWidget

from employee.admin_mixins import ManagerPermissionMixin
from .models import TechStack


@admin.register(TechStack)
class TechStackAdmin(ManagerPermissionMixin, ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    list_editable = ["is_active"]

    formfield_overrides = {
        models.TextField: {"widget": WysiwygWidget},
    }
