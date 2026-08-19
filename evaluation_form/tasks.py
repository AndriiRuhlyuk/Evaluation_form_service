from celery import (
    shared_task,
)  # Імпорт декоратора shared_task з Celery для створення асинхронних задач, наприклад: @shared_task
from django.utils import (
    timezone,
)  # Імпорт timezone з Django для роботи з часовими поясами, наприклад: timezone.now()
from .models import (
    EvaluationForm,
    INTERVIEW_PENDING_THRESHOLD,
)  # Імпорт моделі EvaluationForm з локального модуля, наприклад: EvaluationForm.objects.filter()


@shared_task  # Декоратор, який позначає функцію як асинхронну задачу Celery, що може бути викликана як update_evaluation_statuses.delay()
def update_evaluation_statuses():
    """
    Periodic task Celery, that:
    1. Finds evaluation forms in 'PENDING' status, that should be started
       during next hour.
    2. Move them in 'IN_PROGRESS' status and send message.
    """

    # Поточний час з урахуванням часового поясу, наприклад: 2023-10-15 14:30:00+03:00
    now = timezone.now()

    # Час через годину після поточного, наприклад: 2023-10-15 15:30:00+03:00
    one_hour_later = now + INTERVIEW_PENDING_THRESHOLD

    # Запит до бази даних для отримання форм оцінювання зі статусом 'PENDING',
    # які мають початися протягом наступної години
    # Приклад: QuerySet[<EvaluationForm: id=1, status='PENDING', interview_datetime='2023-10-15 15:00:00+03:00'>, ...]
    forms_to_start = EvaluationForm.objects.filter(
        status=EvaluationForm.Status.PENDING, interview_datetime__lte=one_hour_later
    )

    # Оптимізація: використовуємо QuerySet.update() для одного SQL UPDATE запиту
    # замість циклу з N окремими save() викликами
    # Переваги:
    # - 1 запит до БД замість N+1
    # - Оновлює ТІЛЬКИ вказане поле (status), інші поля не змінюються
    # - Повертає кількість оновлених записів
    # Приклад: QuerySet[..., ..., ...].update(status='in_progress') -> 3
    forms_started_count = forms_to_start.update(
        status=EvaluationForm.Status.IN_PROGRESS
    )

    # TODO: Додати іншу Celery task для відправки email повідомлень інтерв'юерам та рекрутерам
    # Приклад: send_interview_reminder_email.delay(form.id) для кожної форми

    # Повернення рядка з інформацією про кількість оновлених форм, наприклад: "Updated 3 forms to IN_PROGRESS."
    return f"Updated {forms_started_count} forms to IN_PROGRESS."
