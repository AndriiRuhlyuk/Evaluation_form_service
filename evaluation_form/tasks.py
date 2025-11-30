from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import EvaluationForm


@shared_task
def update_evaluation_statuses():
    """
    Periodic task Celery, that:
    1. Finds evaluation forms in 'PENDING' status, that should be started
       during next hour.
    2. Move them in 'IN_PROGRESS' status and send message.
    """

    now = timezone.now()
    one_hour_later = now + timedelta(hours=1)

    forms_to_start = EvaluationForm.objects.filter(
        status=EvaluationForm.Status.PENDING, interview_datetime__lte=one_hour_later
    )

    forms_started_count = 0
    for form in forms_to_start:
        form.status = EvaluationForm.Status.IN_PROGRESS
        form.save(update_fields=["status"])

        # TODO
        ## (Will be another Celery-task
        ##  for send email every interviewer and recruiter)
        ## For example: send_interview_reminder_email.delay(form.id)

        forms_started_count += 1

    return f"Updated {forms_started_count} forms to IN_PROGRESS."
