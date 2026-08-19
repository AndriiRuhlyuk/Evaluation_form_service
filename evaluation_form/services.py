import re  # Модуль для роботи з регулярними виразами, використовується для парсингу ID з URL

import requests  # Бібліотека для HTTP запитів, використовується для взаємодії з PeopleForce API
from rest_framework.exceptions import (
    ValidationError,
)  # Виключення для обробки помилок валідації, наприклад: "Could not parse Candidate ID from link"

from django.conf import (
    settings,
)  # Доступ до налаштувань проекту, наприклад: PEOPLEFORCE_API_KEY
from django.core.files.base import (
    ContentFile,
)  # Клас для створення файлів з вмісту, наприклад: ContentFile(html_content.encode("utf-8"))
from django.db import transaction  # Модуль для управління транзакціями бази даних
from django.template.loader import (
    render_to_string,
)  # Функція для рендерингу HTML шаблонів, наприклад: render_to_string("reports/evaluation_report.html", context)
from django.utils import (
    timezone,
)  # Утиліти для роботи з часом, наприклад: timezone.now()

from evaluation_form.models import (
    EvaluationForm,  # Модель форми оцінювання, наприклад: EvaluationForm(id=1, status="DRAFT")
    EvaluationFormItem,  # Модель елемента форми оцінювання, наприклад: EvaluationFormItem(id=1, name="Python knowledge")
    EvaluationFormTopic,  # Модель теми форми оцінювання, наприклад: EvaluationFormTopic(id=1, name="Technical skills")
)


def check_and_complete_evaluation(form_id: int):
    """
    Checks if all interviewers have submitted their feedback.
    If so, locks the EvaluationForm and triggers notifications.
    Returns True if form was completed, False otherwise.
    Use transaction.atomic and select_for_update to avoid race conditions.
    """
    # form_id: ідентифікатор форми оцінювання, наприклад: 42

    with transaction.atomic():  # Створює атомарну транзакцію для запобігання race conditions
        try:
            # form: об'єкт форми оцінювання, наприклад: EvaluationForm(id=42, status="IN_PROGRESS")
            form = EvaluationForm.objects.select_for_update().get(pk=form_id)
        except EvaluationForm.DoesNotExist:
            return False

        # has_pending_feedbacks: булеве значення, яке вказує, чи є незавершені відгуки, наприклад: True/False
        has_pending_feedbacks = form.feedbacks.filter(is_submitted=False).exists()

        if not has_pending_feedbacks:
            if form.status == EvaluationForm.Status.COMPLETED:
                return True

            # items_to_delete: QuerySet елементів форми без оцінок, наприклад: [EvaluationFormItem(id=5), EvaluationFormItem(id=8)]
            items_to_delete = EvaluationFormItem.objects.filter(
                form_topic__evaluation_form=form,
                scores__isnull=True,
            )
            # deleted_items_count: кількість видалених елементів, наприклад: 3
            deleted_items_count, _ = items_to_delete.delete()

            # topics_to_delete: QuerySet тем форми без елементів, наприклад: [EvaluationFormTopic(id=2)]
            topics_to_delete = EvaluationFormTopic.objects.filter(
                evaluation_form=form, items__isnull=True
            )
            # deleted_topics_count: кількість видалених тем, наприклад: 1
            deleted_topics_count, _ = topics_to_delete.delete()

            print(
                f"Form {form_id} cleanup: {deleted_items_count} items, {deleted_topics_count} topics removed."
            )

            # Оновлення статусу форми на "COMPLETED"
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
    # form: об'єкт форми оцінювання, наприклад: EvaluationForm(id=42, status="COMPLETED", slug="senior-python-dev-2023")

    # topics: QuerySet тем форми з попередньо завантаженими елементами та оцінками,
    # наприклад: [EvaluationFormTopic(id=1, name="Python"), EvaluationFormTopic(id=2, name="Django")]
    topics = form.form_topics.prefetch_related(
        "items", "items__scores", "items__scores__interviewer"
    )

    # feedbacks: QuerySet відгуків з попередньо завантаженими інтерв'юерами,
    # наприклад: [Feedback(id=1, interviewer=User(id=5, name="John")), Feedback(id=2, interviewer=User(id=8, name="Alice"))]
    feedbacks = form.feedbacks.select_related("interviewer").all()

    # context: словник з даними для шаблону,
    # наприклад: {"form": EvaluationForm(...), "topics": [...], "feedbacks": [...], "generated_at": datetime(2023, 5, 15, 10, 30)}
    context = {
        "form": form,
        "topics": topics,
        "feedbacks": feedbacks,
        "generated_at": timezone.now(),  # поточний час, наприклад: datetime(2023, 5, 15, 10, 30)
    }

    # html_content: рядок з HTML-кодом звіту,
    # наприклад: "<html><head>...</head><body>...</body></html>"
    html_content = render_to_string("reports/evaluation_report.html", context)

    # filename: ім'я файлу звіту,
    # наприклад: "Report_senior-python-dev-2023_20230515.html"
    filename = f"Report_{form.slug}_{timezone.now().strftime('%Y%m%d')}.html"

    # Видалення попереднього файлу звіту, якщо він існує
    if form.report_file:
        form.report_file.delete(save=False)

    # Збереження нового файлу звіту
    form.report_file.save(filename, ContentFile(html_content.encode("utf-8")))

    # Повертає URL файлу звіту, наприклад: "/media/reports/Report_senior-python-dev-2023_20230515.html"
    return form.report_file.url


class PeopleForceService:
    """
    Сервіс для взаємодії з API PeopleForce - системи управління персоналом.
    Використовується для додавання нотаток про технічну оцінку кандидатів.
    """

    def __init__(self):
        """
        Ініціалізує сервіс з налаштуваннями для API PeopleForce.
        """
        # api_key: ключ API для автентифікації в PeopleForce, наприклад: "pf_api_key_12345abcde"
        self.api_key = settings.PEOPLEFORCE_API_KEY

        # base_url: базовий URL API PeopleForce, наприклад: "https://api.peopleforce.io/api/v1"
        self.base_url = settings.PEOPLEFORCE_API_URL

        # headers: заголовки HTTP запитів до API,
        # наприклад: {"X-API-KEY": "pf_api_key_12345abcde", "Content-Type": "application/json", "Accept": "application/json"}
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
        # pf_link: посилання на кандидата в PeopleForce,
        # наприклад: "https://company.peopleforce.io/recruitment/applicants/12345"

        # match: результат пошуку ID кандидата в посиланні за допомогою регулярного виразу,
        # наприклад: re.Match об'єкт з групою "12345"
        match = re.search(r"/(?:candidates|applicants)/(\d+)", pf_link)
        if not match:
            # match_simple: альтернативний пошук ID в кінці посилання,
            # наприклад: re.Match об'єкт з групою "12345"
            match_simple = re.search(r"/(\d+)$", pf_link.rstrip("/"))
            if match_simple:
                return int(
                    match_simple.group(1)
                )  # Повертає ID кандидата, наприклад: 12345

            # Якщо ID не знайдено, викидає помилку валідації
            raise ValidationError(
                f"Could not parse Candidate ID from link: {pf_link}. Expected format: .../applicants/12345"
            )
        return int(match.group(1))  # Повертає ID кандидата, наприклад: 12345

    def add_evaluation_note(
        self, pf_link: str, report_url: str, decision: str, summary: str
    ):
        """
        Create note in candidate card with report_link.
        """
        # pf_link: посилання на кандидата, наприклад: "https://company.peopleforce.io/recruitment/applicants/12345"
        # report_url: URL звіту оцінювання, наприклад: "/media/reports/Report_senior-python-dev-2023_20230515.html"
        # decision: рішення щодо кандидата, наприклад: "Hire" або "Reject"
        # summary: короткий підсумок оцінювання, наприклад: "Strong Python skills, good understanding of Django"

        # candidate_id: ID кандидата, витягнутий з посилання, наприклад: 12345
        candidate_id = self.extract_candidate_id(pf_link)

        # endpoint: URL для створення нотатки, наприклад: "https://api.peopleforce.io/api/v1/recruitment/candidates/12345/notes"
        endpoint = f"{self.base_url}/recruitment/candidates/{candidate_id}/notes"

        # note_body: текст нотатки з форматуванням Markdown,
        # наприклад: "✅ **Technical Evaluation Completed**\n\n**Decision:** Hire\n**See Full Report:** /media/reports/Report.html\n\n**Summary:**\nStrong Python skills"
        note_body = (
            f"✅ **Technical Evaluation Completed**\n\n"
            f"**Decision:** {decision}\n"
            f"**See Full Report:** {report_url}\n\n"
            f"**Summary:**\n{summary}"
        )

        # payload: дані для відправки в API, наприклад: {"comment": "✅ **Technical Evaluation Completed**\n\n..."}
        payload = {"comment": note_body}

        try:
            # response: відповідь від API PeopleForce,
            # наприклад: Response(status_code=201, json={"id": 789, "comment": "✅ **Technical Evaluation Completed**\n\n..."})
            response = requests.post(endpoint, json=payload, headers=self.headers)
            response.raise_for_status()
            return (
                response.json()
            )  # Повертає дані відповіді у форматі JSON, наприклад: {"id": 789, "comment": "..."}
        except requests.exceptions.RequestException as e:
            # error_details: деталі помилки, наприклад: "404 Client Error: Not Found for url: https://api.peopleforce.io/..."
            error_details = str(e)

            if e.response is not None:
                # Якщо є відповідь від сервера, додаємо статус код і тіло відповіді до деталей помилки
                error_details = (
                    f"Status: {e.response.status_code} | Body: {e.response.text}"
                )

            print(f"PeopleForce Sync Error: {error_details}")

            # Викидаємо помилку валідації з деталями помилки API
            raise ValidationError(f"PeopleForce API Error: {error_details}")
