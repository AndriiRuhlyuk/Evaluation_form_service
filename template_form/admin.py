# template_form/admin.py
# Повна версія файлу admin.py з усіма виправленнями.
# - Використання django-nested-admin для вкладених inlines.
# - Групування Items по топіках через FormTopicInline.
# - Виправлення RelatedObjectDoesNotExist: перевірки на obj.topic_id перед доступом до topic.
# - М'яке видалення, фільтрація origin_question по топіку.
# - Оновлені list_filter, fieldsets без 'topics'.
# - Поле 'manager' прибрано з fieldsets і додано до readonly_fields, щоб не можна було вибирати/змінювати.
# - Авто-заповнення снепшотів з origin_question перенесено в model save (без JS).

from collections import defaultdict
from django.contrib import admin
from django.contrib.admin.utils import quote
from django.forms.models import BaseInlineFormSet
from django.utils.safestring import mark_safe
from django.urls import reverse
import nested_admin
from .models import TemplateForm, FormTopic, TemplateFormItems
from question.models import Question


class SoftDeleteInlineFormSet(BaseInlineFormSet):
    """
    Кастомний formset для м'якого видалення в inline.
    Замість жорсткого видалення, встановлює is_removed=True.
    """

    def delete_existing(self, obj, commit=True):
        if commit:
            obj.is_removed = True
            obj.save()


class TemplateFormItemsInline(nested_admin.NestedTabularInline):
    """
    Inline для TemplateFormItems, вкладений в FormTopic.
    - Фільтрований origin_question до Питань з поточного топіка (рекомендовані).
    - Додавання нових Items тільки в цей топік.
    - Редаговані снепшоти, м'яке видалення.
    """

    model = TemplateFormItems
    extra = 1
    formset = SoftDeleteInlineFormSet
    fields = (
        "origin_question",
        "text_snapshot",
        "difficulty_snapshot",
        "topic_snapshot",
        "max_score_snapshot",
        "source_snapshot",
        "is_removed",
        "added_by",
        "created_at",
    )
    readonly_fields = (
        "topic_snapshot",
        "max_score_snapshot",
        "source_snapshot",
        "added_by",
        "created_at",
    )
    ordering = ("difficulty_snapshot",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(is_removed=False)

    def get_formset(self, request, obj=None, **kwargs):
        # obj тут - це FormTopic
        if (
            obj and obj.topic_id
        ):  # Перевірка на topic_id, щоб уникнути RelatedObjectDoesNotExist

            class CustomInlineForm(self.form):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    # Фільтрація origin_question до питань з цього топіка
                    self.fields["origin_question"].queryset = Question.objects.filter(
                        topic_id=obj.topic_id
                    )

            kwargs["form"] = CustomInlineForm
        return super().get_formset(request, obj, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return True  # Чекбокс для м'якого видалення


class FormTopicInline(nested_admin.NestedTabularInline):
    """
    Inline для FormTopic, вкладений в TemplateForm.
    - Дозволяє додавати/редагувати топіки в формі.
    - Вкладений inline для Items.
    """

    model = FormTopic
    extra = 1
    fields = ("topic",)
    inlines = [TemplateFormItemsInline]


@admin.register(TemplateForm)
class TemplateFormAdmin(nested_admin.NestedModelAdmin):
    """
    Адмін для TemplateForm з вкладеними inlines.
    - Створення форми з назвою та tech_stack.
    - Додавання Топіків через FormTopicInline (існуючі або нові через popup).
    - Items додаються через вкладений inline, згруповані по топіках.
    - Поле manager автоматично встановлюється на поточного юзера і не редагується.
    - Синхронізація топіків після збереження.
    """

    list_display = (
        "name",
        "manager",
        "tech_stack",
        "topics_count",
        "items_count",
        "created_at",
        "updated_at",
    )
    list_filter = ("tech_stack", "created_at", "updated_at")
    search_fields = ("name", "slug", "manager__username")
    ordering = ("-created_at",)
    inlines = [FormTopicInline]
    readonly_fields = (
        "slug",
        "created_at",
        "updated_at",
        "get_topics_with_questions",
        "manager",
    )  # Додано 'manager' до readonly
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "tech_stack", "slug"),
            },
        ),
        (
            "Мітки часу",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
        (
            "Згруповані Питання",
            {
                "fields": ("get_topics_with_questions",),
            },
        ),
    )

    def topics_count(self, obj):
        return obj.form_topics.count()

    topics_count.short_description = "Кількість Топіків"

    def items_count(self, obj):
        return TemplateFormItems.objects.filter(
            form_topic__form=obj, is_removed=False
        ).count()

    items_count.short_description = "Кількість Активних Елементів"

    def get_topics_with_questions(self, obj):
        """
        Відображення активних Items, згрупованих за топіками.
        """
        form_topics = obj.form_topics.all().prefetch_related("items__origin_question")
        grouped_items = defaultdict(list)
        for ft in form_topics:
            if ft.topic_id:  # Перевірка на topic_id
                topic_name = ft.topic.name
            else:
                topic_name = "Без топіка"
            active_items = ft.items.filter(is_removed=False)
            for item in active_items:
                item_detail_url = reverse(
                    "admin:template_form_templateformitems_change",
                    args=(quote(item.pk),),
                )
                grouped_items[topic_name].append(
                    {
                        "id": item.id,
                        "text": item.text_snapshot,
                        "difficulty": item.difficulty_snapshot,
                        "url": item_detail_url,
                    }
                )

        if not grouped_items:
            return "Немає активних питань."

        html = ""
        for topic, questions in grouped_items.items():
            html += f"<h4>{topic}</h4><ul>"
            for q in questions:
                html += f'<li><a href="{q["url"]}">[ID: {q["id"]}] Складність: {q["difficulty"]} - {q["text"][:100]}...</a></li>'
            html += "</ul>"
        return mark_safe(html)

    get_topics_with_questions.short_description = "Топіки з Питаннями (Згруповані)"

    def save_model(self, request, obj, form, change):
        if not obj.manager:
            obj.manager = (
                request.user
            )  # Автоматичне встановлення менеджера на поточного юзера
        super().save_model(request, obj, form, change)
        from .services import _synchronize_form_topics

        _synchronize_form_topics(obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        from .services import _synchronize_form_topics

        _synchronize_form_topics(form.instance)


@admin.register(FormTopic)
class FormTopicAdmin(admin.ModelAdmin):
    """
    Адмін для FormTopic.
    """

    list_display = ("form", "topic")
    list_filter = ("form__tech_stack",)
    search_fields = ("form__name", "topic__name")
    ordering = ("form", "topic")


@admin.register(TemplateFormItems)
class TemplateFormItemsAdmin(nested_admin.NestedModelAdmin):
    """
    Окремий адмін для TemplateFormItems (для прямого управління, якщо потрібно).
    - Перевизначення м'якого видалення.
    """

    list_display = (
        "form_topic",
        "text_snapshot_short",
        "difficulty_snapshot",
        "topic_snapshot",
        "is_removed",
        "origin_question",
        "added_by",
        "created_at",
    )
    list_filter = (
        "is_removed",
        "difficulty_snapshot",
        "source_snapshot",
        "form_topic__form__tech_stack",
        "form_topic__form",
    )
    search_fields = ("text_snapshot", "topic_snapshot", "form_topic__form__name")
    ordering = ("-created_at",)
    readonly_fields = ("max_score_snapshot", "created_at", "source_snapshot")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "form_topic",
                    "origin_question",
                    "text_snapshot",
                    "difficulty_snapshot",
                    "topic_snapshot",
                    "max_score_snapshot",
                    "source_snapshot",
                    "is_removed",
                ),
            },
        ),
        (
            "Метадані",
            {
                "fields": ("added_by", "created_at"),
            },
        ),
    )

    def text_snapshot_short(self, obj):
        return (
            obj.text_snapshot[:50] + "..."
            if len(obj.text_snapshot) > 50
            else obj.text_snapshot
        )

    text_snapshot_short.short_description = "Снепшот Тексту"

    def has_delete_permission(self, request, obj=None):
        return False  # Відключення жорсткого видалення у списку

    def delete_model(self, request, obj):
        # М'яке видалення для індивідуального видалення
        obj.is_removed = True
        obj.save()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.added_by = request.user
        if "difficulty_snapshot" in form.changed_data:
            obj.max_score_snapshot = obj.difficulty_snapshot * 3
        super().save_model(request, obj, form, change)
        from .services import _synchronize_form_topics

        _synchronize_form_topics(obj.form_topic.form)
