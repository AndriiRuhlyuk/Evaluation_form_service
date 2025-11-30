import re

import requests
from rest_framework.exceptions import ValidationError

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from evaluation_form.models import (
    EvaluationForm,
    EvaluationFormItem,
    EvaluationFormTopic,
)


def check_and_complete_evaluation(form_id: int):
    """
    Checks if all interviewers have submitted their feedback.
    If so, locks the EvaluationForm and triggers notifications.
    Returns True if form was completed, False otherwise.
    Use transaction.atomic and select_for_update to avoid race conditions.
    """

    with transaction.atomic():
        try:
            form = EvaluationForm.objects.select_for_update().get(pk=form_id)
        except EvaluationForm.DoesNotExist:
            return False

        has_pending_feedbacks = form.feedbacks.filter(is_submitted=False).exists()

        if not has_pending_feedbacks:
            if form.status == EvaluationForm.Status.COMPLETED:
                return True

            items_to_delete = EvaluationFormItem.objects.filter(
                form_topic__evaluation_form=form,
                scores__isnull=True,
            )
            deleted_items_count, _ = items_to_delete.delete()

            topics_to_delete = EvaluationFormTopic.objects.filter(
                evaluation_form=form, items__isnull=True
            )
            deleted_topics_count, _ = topics_to_delete.delete()

            print(
                f"Form {form_id} cleanup: {deleted_items_count} items, {deleted_topics_count} topics removed."
            )

            form.status = EvaluationForm.Status.COMPLETED
            form.save(update_fields=["status"])

            # TODO: Send emails
            # Найкраща практика - відкласти відправку до успішного завершення транзакції
            # transaction.on_commit(lambda: send_completion_emails.delay(form.id))

            return True

    return False


def generate_html_report(form: EvaluationForm) -> str:
    """
    Generates static HTML report and saves it to the form instance.
    Returns the URL of the generated file.
    """

    topics = form.form_topics.prefetch_related(
        "items", "items__scores", "items__scores__interviewer"
    )
    feedbacks = form.feedbacks.select_related("interviewer").all()

    context = {
        "form": form,
        "topics": topics,
        "feedbacks": feedbacks,
        "generated_at": timezone.now(),
    }
    html_content = render_to_string("reports/evaluation_report.html", context)

    filename = f"Report_{form.slug}_{timezone.now().strftime('%Y%m%d')}.html"

    if form.report_file:
        form.report_file.delete(save=False)

    form.report_file.save(filename, ContentFile(html_content.encode("utf-8")))

    return form.report_file.url


class PeopleForceService:
    def __init__(self):
        self.api_key = settings.PEOPLEFORCE_API_KEY
        self.base_url = settings.PEOPLEFORCE_API_URL
        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def extract_candidate_id(self, pf_link: str) -> int:
        """
        Take ID from candidate link in PeopleForce.
        Support formats:
        - https://.../recruitment/applicants/12345 (Link with browser)
        - https://.../recruitment/candidates/12345 (Link with API)
        """

        match = re.search(r"/(?:candidates|applicants)/(\d+)", pf_link)
        if not match:
            match_simple = re.search(r"/(\d+)$", pf_link.rstrip("/"))
            if match_simple:
                return int(match_simple.group(1))

            raise ValidationError(
                f"Could not parse Candidate ID from link: {pf_link}. Expected format: .../applicants/12345"
            )
        return int(match.group(1))

    def add_evaluation_note(
        self, pf_link: str, report_url: str, decision: str, summary: str
    ):
        """
        Create note in candidate card with report_link.
        """

        candidate_id = self.extract_candidate_id(pf_link)

        endpoint = f"{self.base_url}/recruitment/candidates/{candidate_id}/notes"

        note_body = (
            f"✅ **Technical Evaluation Completed**\n\n"
            f"**Decision:** {decision}\n"
            f"**See Full Report:** {report_url}\n\n"
            f"**Summary:**\n{summary}"
        )

        payload = {"comment": note_body}

        try:

            response = requests.post(endpoint, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_details = str(e)

            if e.response is not None:
                error_details = (
                    f"Status: {e.response.status_code} | Body: {e.response.text}"
                )

            print(f"PeopleForce Sync Error: {error_details}")

            raise ValidationError(f"PeopleForce API Error: {error_details}")
