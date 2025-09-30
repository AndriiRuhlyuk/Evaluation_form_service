from django.contrib import admin
from question.models import Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question_text", "difficulty", "usage_count", "topic")
    search_fields = ("question_text", "topic__name")
    list_filter = ("difficulty", "topic__name", "source", "is_active", "topic")
    readonly_fields = ("created_at", "updated_at", "question_author")

    def save_model(self, request, obj, form, change):
        """
        Add current user as author for created question.
        """
        if not obj.pk:
            obj.question_author = request.user
        super().save_model(request, obj, form, change)

    def get_search_results(self, request, queryset, search_term):
        print("\n--- ✅ Starting get_search_results ---")

        # 1. Перевіряємо початковий стан
        print(f"Initial queryset count: {queryset.count()}")
        print(f"Search term received: '{search_term}'")

        # 2. Застосовуємо наш фільтр
        topic_name = request.GET.get("topic_name")
        print(f"Topic name from URL: '{topic_name}'")

        if topic_name:
            # ЦЕ НАЙВАЖЛИВІШИЙ КРОК
            filtered_queryset = queryset.filter(topic__name__iexact=topic_name.strip())
            print(f"Queryset count AFTER topic filter: {filtered_queryset.count()}")
            queryset = filtered_queryset
        else:
            print("No topic name provided, skipping topic filter.")

        # 3. Застосовуємо стандартний пошук
        final_queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        print(f"Queryset count AFTER super() search: {final_queryset.count()}")
        print("--- 🛑 Ending get_search_results ---\n")

        return final_queryset, use_distinct
