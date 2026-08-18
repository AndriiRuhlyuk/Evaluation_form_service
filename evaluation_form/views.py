from django.contrib.auth import get_user_model
from django.db.models import (
    prefetch_related_objects,
    Prefetch,
    Q,
    Exists,
    OuterRef,
)
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination

from working_form.permissions import IsRecruiter
from .permissions import CanScoreOrFeedback, CanCreateScore
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from evaluation_form.models import (
    EvaluationForm,
    EvaluationFeedback,
    EvaluationScore,
    EvaluationFormItem,
    Candidate,
)
from evaluation_form.serializers import (
    RecruiterEvaluationSerializer,
    InterviewerEvaluationSerializer,
    EvaluationFormListSerializer,
    EvaluationFeedbackSerializer,
    EvaluationScoreSerializer,
    EvaluationFormUpdateSerializer,
    EmptySerializer,
    EvaluationScoreLiteSerializer,
    CandidateDetailSerializer,
    CandidateListSerializer,
)
from .services import (
    check_and_complete_evaluation,
    generate_html_report,
    PeopleForceService,
)

# Змінна, що зберігає модель користувача системи (працівника)
# Приклад: Employee = User або Employee = CustomUser
Employee = get_user_model()


class CandidatePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for view candidates and them history.
    Used for:
    1. Search candidate when create EvaluationForm (Autocomplete).
    2. View candidate profile with (History).
    """

    # Набір даних, що містить всіх кандидатів
    # Приклад: [<Candidate: John Doe>, <Candidate: Jane Smith>]
    queryset = Candidate.objects.all()
    pagination_class = CandidatePagination

    # Клас серіалізатора для перетворення об'єктів кандидатів у JSON
    # Приклад: {"id": 1, "full_name": "John Doe", "email": "john@example.com"}
    serializer_class = CandidateListSerializer

    # Класи дозволів, що визначають хто має доступ до цього ViewSet
    # Приклад: Тільки автентифіковані користувачі можуть переглядати кандидатів
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Отримує відфільтрований набір кандидатів на основі параметрів запиту.

        Параметри запиту:
        - search: Пошук за ім'ям або email

        Приклад запиту: /candidates/?search=john
        Приклад результату: [<Candidate: John Doe>]
        """
        queryset = super().get_queryset()

        # Параметр пошуку з URL, наприклад "john"
        search = self.request.query_params.get("search")
        if search:
            # Фільтрація кандидатів за ім'ям або email
            # Приклад: Пошук "john" знайде "John Doe" та "john@example.com"
            queryset = queryset.filter(
                Q(full_name__icontains=search) | Q(email__icontains=search)
            )

        # Для детального перегляду кандидата завантажуємо пов'язані оцінювання
        if self.action == "retrieve":
            # Приклад: Кандидат з усіма його формами оцінювання
            queryset = queryset.prefetch_related("evaluations")

        return queryset

    def get_serializer_class(self):
        """
        Визначає який серіалізатор використовувати в залежності від дії.

        - If LIST (/candidates/) -> CandidateListSerializer
          Приклад: [{"id": 1, "full_name": "John Doe"}, {"id": 2, "full_name": "Jane Smith"}]

        - If RETRIEVE (/candidates/1/) -> CandidateDetailSerializer
          Приклад: {"id": 1, "full_name": "John Doe", "email": "john@example.com",
                   "evaluations": [{"id": 1, "status": "completed"}]}
        """
        if self.action == "list":
            # Для списку кандидатів використовуємо спрощений серіалізатор
            return CandidateListSerializer

        # Для детального перегляду використовуємо розширений серіалізатор
        return CandidateDetailSerializer


class EvaluationFormViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Provides read-only access to Evaluation Forms.
    Shows different data based on user role and form status.
    """

    # Набір даних, що містить всі форми оцінювання
    # Приклад: [<EvaluationForm: Form for John Doe>, <EvaluationForm: Form for Jane Smith>]
    queryset = EvaluationForm.objects.all()

    # Поле для пошуку об'єкта замість стандартного 'pk'
    # Приклад: /evaluation-forms/john-doe-2023-05-15/ замість /evaluation-forms/1/
    lookup_field = "slug"

    def get_permissions(self):
        """
        Визначає дозволи для різних дій.

        Приклад:
        - Для оновлення та видалення: Тільки рекрутери можуть виконувати ці дії
        - Для перегляду: Будь-який автентифікований користувач
        """
        if self.action in ["update", "partial_update", "destroy"]:
            # Для оновлення та видалення потрібні права рекрутера
            # Приклад: Рекрутер може змінити статус форми або видалити її
            return [permissions.IsAuthenticated(), IsRecruiter()]

        # Для інших дій достатньо бути автентифікованим
        # Приклад: Інтерв'юер може переглядати форми, але не змінювати їх
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Оптимізує запити для списку та детального перегляду форм.
        Фільтрує форми по поточному користувачу.

        Користувач бачить форми, де він є:
        - manager (менеджер форми)
        - hiring_manager (HR-менеджер)
        - інтерв'юером
        - рекрутером

        Приклад для списку:
        - Завантажує пов'язані об'єкти кандидата, менеджера та HR-менеджера
        - Фільтрує по користувачу
        - Результат: [{"id": 1, "candidate": {"name": "John"}, "manager": {"name": "Mike"}}]

        Приклад для детального перегляду:
        - Додатково завантажує список рекрутерів
        - Фільтрує по користувачу
        - Результат: {"id": 1, "recruiters": [{"name": "Alice"}, {"name": "Bob"}]}
        """

        queryset = super().get_queryset()

        # Суперкористувачі бачять все, звичайні користувачи - тільки свої форми
        if not self.request.user.is_superuser:
            # Фільтруємо форми по поточному користувачу
            # Користувач бачить форми де він є:
            # 1. Менеджером форми (manager)
            # 2. HR-менеджером (hiring_manager)
            # 3. Інтерв'юером (в списку interviewers)
            # 4. Рекрутером (в списку recruiters)
            queryset = queryset.filter(
                Q(manager=self.request.user)  # Менеджер форми
                | Q(hiring_manager=self.request.user)  # HR-менеджер
                | Q(interviewers=self.request.user)  # Інтерв'юер
                | Q(recruiters=self.request.user)  # Рекрутер
            ).distinct()  # Уникаємо дублів через ManyToMany

        if self.action == "list":
            # Оптимізація для списку форм - завантажуємо пов'язані об'єкти
            # Приклад: Форма з даними кандидата та менеджерів
            queryset = queryset.select_related("candidate", "manager", "hiring_manager")

        if self.action == "retrieve":
            # Оптимізація для детального перегляду - додатково завантажуємо рекрутерів
            # Приклад: Форма з даними менеджерів та списком рекрутерів
            queryset = queryset.select_related(
                "manager", "hiring_manager"
            ).prefetch_related("recruiters")

        return queryset

    def get_object(self):
        """
        Отримує об'єкт форми один раз і кешує його в '_instance' для одного request'у.

        Кешування обмежене одним HTTP request'ом для безпеки:
        - Уникаємо повторних запитів до БД в межах одного request'у (GET операції)
        - Кеш не використовується для POST/PUT/PATCH/DELETE методів (лічено модифікацією)
        - Автоматично очищується для кожного нового request'у

        Приклад:
        - GET request (перший виклик): Запит до БД -> <EvaluationForm: Form for John>
        - GET request (наступні виклики): Повертає кешований об'єкт без запиту до БД
        - PUT/PATCH request: Кеш очищується, отримуємо свіжий об'єкт з БД
        """

        # Методи модифікації - очищуємо кеш щоб гарантувати свіжість даних
        if self.request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # Очищуємо кеш для методів модифікації
            if hasattr(self, "_instance"):
                delattr(self, "_instance")

        # Для безпечних методів (GET, HEAD, OPTIONS) використовуємо кешування
        if getattr(self, "_instance", None) is None:
            # Якщо об'єкт ще не кешований, отримуємо його з БД
            # З префетч'ованими даними з get_queryset()
            self._instance = super().get_object()

        # Повертаємо кешований об'єкт
        return self._instance

    def perform_destroy(self, instance):
        """
        М'яке видалення форми оцінювання замість фізичного.

        Форму зі статусом IN_PROGRESS видалити не можна (400) - співбесіда
        триває. PENDING та COMPLETED видаляються; report_file не чіпаємо,
        щоб посилання на звіт у нотатці PeopleForce лишалося робочим.
        Відновлення - тільки адміном через django admin.
        """
        if instance.status == EvaluationForm.Status.IN_PROGRESS:
            raise ValidationError(
                "Cannot delete an evaluation form while the interview "
                "is in progress."
            )
        instance.soft_delete(self.request.user)

    def get_serializer_class(self):
        """
        Визначає який серіалізатор використовувати в залежності від дії та ролі користувача.

        Приклади:
        - Для sync_crm: EmptySerializer (без даних)
        - Для оновлення: EvaluationFormUpdateSerializer (обмежений набір полів)
        - Для списку: EvaluationFormListSerializer (спрощений вигляд)
        - Для детального перегляду: Залежить від ролі користувача
          * Для рекрутера: RecruiterEvaluationSerializer (повний доступ)
          * Для інтерв'юера: InterviewerEvaluationSerializer (обмежений доступ)
        """

        if self.action == "sync_crm":
            # Для синхронізації з CRM не потрібні дані
            return EmptySerializer

        if self.action in ["update", "partial_update"]:
            # Для оновлення використовуємо спеціальний серіалізатор
            # Приклад: {"status": "completed"}
            return EvaluationFormUpdateSerializer

        if self.action == "list":
            # Для списку використовуємо спрощений серіалізатор
            # Приклад: [{"id": 1, "candidate": "John Doe", "status": "in_progress"}]
            return EvaluationFormListSerializer

        # Отримуємо об'єкт форми та поточного користувача
        instance = self.get_object()
        user = self.request.user

        # Визначаємо серіалізатор на основі ролі користувача та статусу форми

        if user.is_superuser:
            # Адміністратор бачить повну інформацію
            # Приклад: {"id": 1, "scores": [...], "feedbacks": [...]}
            return RecruiterEvaluationSerializer

        if instance.status == EvaluationForm.Status.COMPLETED:
            # Завершена форма доступна всім у повному обсязі
            return RecruiterEvaluationSerializer

        if user == instance.manager:
            # Менеджер форми бачить повну інформацію
            return RecruiterEvaluationSerializer

        if user == instance.hiring_manager:
            # HR-менеджер бачить повну інформацію
            return RecruiterEvaluationSerializer

        # Перевіряємо чи користувач є рекрутером для цієї форми
        recruiter_ids = {recruit.pk for recruit in instance.recruiters.all()}
        if user.pk in recruiter_ids:
            # Рекрутер бачить повну інформацію
            return RecruiterEvaluationSerializer

        # Інтерв'юер бачить обмежену інформацію
        # Приклад: {"id": 1, "my_scores": [...], "my_feedback": {...}}
        return InterviewerEvaluationSerializer

    def retrieve(self, request, *args, **kwargs):
        """
        Отримує детальну інформацію про форму оцінювання з оптимізованим завантаженням даних.

        Процес:
        1. Отримує об'єкт форми з кешованими рекрутерами
        2. Визначає відповідний серіалізатор на основі ролі користувача
        3. Завантажує необхідні дані (оцінки/відгуки) відповідно до обраного серіалізатора

        Приклад відповіді для рекрутера:
        {
            "id": 1,
            "candidate": {"name": "John Doe"},
            "feedbacks": [{"interviewer": "Alice", "decision": "next_step"}],
            "form_topics": [{"items": [{"scores": [{"interviewer": "Bob", "score": 4}]}]}]
        }

        Приклад відповіді для інтерв'юера:
        {
            "id": 1,
            "candidate": {"name": "John Doe"},
            "my_feedback": {"decision": "next_step"},
            "form_topics": [{"items": [{"my_score": {"score": 4}}]}]
        }
        """
        # Отримуємо об'єкт форми з кешу
        instance = self.get_object()
        # Визначаємо клас серіалізатора на основі ролі користувача
        serializer_class = self.get_serializer_class()
        # Поточний користувач
        user = self.request.user

        if serializer_class == RecruiterEvaluationSerializer:
            # Для рекрутерів завантажуємо всі відгуки та оцінки
            # Приклад: Всі відгуки та оцінки від усіх інтерв'юерів
            prefetch_related_objects(
                [instance],
                Prefetch(
                    "feedbacks",
                    queryset=EvaluationFeedback.objects.select_related("interviewer"),
                ),
                Prefetch(
                    "form_topics__items__scores",
                    queryset=EvaluationScore.objects.select_related("interviewer"),
                ),
            )
        else:
            # Для інтерв'юерів завантажуємо тільки їхні власні відгуки та оцінки
            # Приклад: Тільки відгуки та оцінки поточного користувача
            prefetch_related_objects(
                [instance],
                Prefetch(
                    "feedbacks",
                    queryset=EvaluationFeedback.objects.filter(interviewer=user),
                    to_attr="my_feedback_cache",  # Зберігаємо в спеціальному атрибуті
                ),
                Prefetch(
                    "form_topics__items",
                    queryset=EvaluationFormItem.objects.prefetch_related(
                        Prefetch(
                            "scores",
                            queryset=EvaluationScore.objects.filter(interviewer=user),
                            to_attr="my_scores_cache",  # Зберігаємо в спеціальному атрибуті
                        )
                    ),
                ),
            )

        # Серіалізуємо об'єкт з контекстом запиту
        serializer = serializer_class(instance, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsRecruiter],
    )
    def sync_crm(self, request, slug=None):
        """
        Синхронізує дані форми оцінювання з CRM системою (PeopleForce).

        Процес (атомарний - все або нічого):
        1. Перевіряє чи форма завершена і чи є посилання на кандидата в CRM
        2. Формує підсумок рішень інтерв'юерів
        3. Додає нотатку в CRM (перед генерацією файлу!)
        4. Генерує HTML-звіт з результатами оцінювання
        5. При помилці - все скасовується (rollback)

        Приклад успішної відповіді:
        {
            "status": "synced",
            "message": "Report generated and attached to form.",
            "report_url": "https://example.com/reports/form-123.html",
            "candidate_crm_link": "https://peopleforce.io/candidates/123"
        }

        Приклад помилки:
        {
            "error": "Complete the form first."
        }
        """
        from django.db import transaction

        # Отримуємо об'єкт форми та пов'язаного кандидата
        form = self.get_object()
        candidate = form.candidate

        # Перевіряємо чи форма завершена
        if form.status != EvaluationForm.Status.COMPLETED:
            return Response({"error": "Complete the form first."}, 400)

        # Перевіряємо чи є посилання на кандидата в CRM
        if not candidate.pf_link:
            return Response(
                {
                    "error": "Candidate does not have a PeopleForce link in their profile."
                },
                400,
            )

        # Використовуємо транзакцію для атомарності операцій
        # Якщо будь-яка операція поза та, весь блок скасується (rollback)
        try:
            with transaction.atomic():
                # Отримуємо всі рішення інтерв'юерів та формуємо загальне рішення
                # Приклад: ["next_step", "next_step", "reject"] -> "Mixed/Refuse"
                decisions = form.feedbacks.values_list("decision", flat=True)
                final_decision_str = (
                    "Move Forward"
                    if all(d == "next_step" for d in decisions)
                    else "Mixed/Refuse"
                )

                # Формуємо текстовий підсумок відгуків
                # Приклад: "- John Doe: Move to next step\n- Jane Smith: Reject\n"
                feedbacks_summary = ""
                for fb in form.feedbacks.select_related("interviewer").all():
                    feedbacks_summary += (
                        f"- {fb.interviewer.fullname}: {fb.get_decision_display()}\n"
                    )

                # Генеруємо HTML-звіт з результатами оцінювання ПЕРЕД додаванням в CRM
                # Якщо файл не буде створений, помилка буде піймана нижче
                # Приклад: Створює файл form-123.html з усіма оцінками та відгуками
                generate_html_report(form)

                # Формуємо повне URL для звіту
                # Приклад: https://example.com/media/reports/form-123.html
                report_url = request.build_absolute_uri(form.report_file.url)

                # Створюємо сервіс для роботи з PeopleForce API
                pf_service = PeopleForceService()

                # Додаємо нотатку в CRM з посиланням на звіт
                # Якщо це падає, файл буде видалено (rollback транзакції)
                # Приклад: Додає нотатку з посиланням на звіт та рішенням до профілю кандидата
                pf_service.add_evaluation_note(
                    pf_link=candidate.pf_link,
                    report_url=report_url,
                    decision=final_decision_str,
                    summary=feedbacks_summary,
                )

        except ValidationError as e:
            # Якщо виникла помилка при взаємодії з API або генерації звіту
            # Транзакція автоматично скасовується (rollback)
            # Але файл на файловій системі потрібно видалити вручну
            # (тому що файлова система не керується транзакціями БД)
            self._cleanup_report_file(form)
            return Response({"error": str(e)}, status=502)
        except Exception as e:
            # Ловимо інші помилки (наприклад, помилки файлової системи)
            # Видаляємо файл якщо він був створений
            self._cleanup_report_file(form)
            return Response({"error": f"Failed to sync with CRM: {str(e)}"}, status=500)

        # Повертаємо успішну відповідь з інформацією про синхронізацію
        return Response(
            {
                "status": "synced",
                "message": "Report generated and attached to form.",
                "report_url": report_url,
                "candidate_crm_link": candidate.pf_link,
            }
        )

    def _cleanup_report_file(self, form):
        """
        Видаляє файл звіту якщо він існує.
        Використовується при помилках для очищення файловій системи.
        """
        import os
        from django.conf import settings

        if form.report_file:
            try:
                # Отримуємо повний шлях до файлу
                file_path = os.path.join(settings.MEDIA_ROOT, str(form.report_file))
                if os.path.exists(file_path):
                    # Видаляємо файл
                    os.remove(file_path)
            except Exception as cleanup_error:
                # Якщо видалення не вдалося, логуємо помилку але не повертаємо помилку користувачу
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to cleanup report file: {cleanup_error}")


class EvaluationScoreViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """
    Interviewer can create scores.
    """

    # Клас серіалізатора для перетворення об'єктів оцінок у JSON
    # Приклад: {"item": 1, "score": 4, "comment": "Good knowledge"}
    serializer_class = EvaluationScoreSerializer

    def get_permissions(self):
        """
        Визначає дозволи для різних дій.

        Приклади:
        - Для створення (POST): Потрібен спеціальний дозвіл CanCreateScore
        - Для списку (GET): Достатньо бути автентифікованим
        """
        if self.action == "create":
            # Для створення оцінки потрібен спеціальний дозвіл
            # Приклад: Інтерв'юер може оцінювати тільки призначені йому форми
            return [permissions.IsAuthenticated(), CanCreateScore()]
        # Для інших дій достатньо бути автентифікованим
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Повертає оптимізований набір даних в залежності від дії.

        Приклади:
        - Для 'list': Повертає тільки оцінки поточного користувача для активних форм
          Приклад: [{"item": "Python knowledge", "score": 4}, {"item": "SQL", "score": 3}]

        - Для 'create': Повертає повний набір даних з усіма зв'язками для перевірки дозволів
          Приклад: Оцінка з даними про форму, менеджерів, рекрутерів та інтерв'юерів
        """
        # Поточний користувач
        user = self.request.user

        if self.action == "list":
            # Для списку повертаємо тільки оцінки поточного користувача для активних форм
            # Приклад: Всі оцінки, які поставив інтерв'юер для форм у статусі "В процесі"
            return EvaluationScore.objects.filter(
                interviewer=user,
                item__form_topic__evaluation_form__status=EvaluationForm.Status.IN_PROGRESS,
            ).select_related("item")

        # Для інших дій (створення) повертаємо повний набір даних з усіма зв'язками
        # Приклад: Оцінка з даними про форму, менеджерів, рекрутерів та інтерв'юерів
        queryset = EvaluationScore.objects.select_related(
            "item__form_topic__evaluation_form__hiring_manager",
            "item__form_topic__evaluation_form__manager",
            "interviewer",
        ).prefetch_related(
            "item__form_topic__evaluation_form__recruiters",
            "item__form_topic__evaluation_form__interviewers",
        )

        # Для адміністратора повертаємо всі дані
        if user.is_superuser:
            return queryset

        # Для звичайного користувача також повертаємо всі дані (для перевірки дозволів)
        return queryset

    def perform_create(self, serializer):
        """
        Автоматично встановлює поточного користувача як інтерв'юера при створенні оцінки.

        Приклад:
        - Вхідні дані: {"item": 1, "score": 4}
        - Збережені дані: {"item": 1, "score": 4, "interviewer": <current_user>}
        """
        # Зберігаємо оцінку з автоматичним встановленням інтерв'юера
        serializer.save(interviewer=self.request.user)

    def create(self, request, *args, **kwargs):
        """
        Створює або оновлює оцінку для елемента форми.

        Особливості:
        1. Перезавантажує об'єкт з prefetch-кешем перед перевіркою дозволів
        2. Використовує update_or_create для уникнення дублювання оцінок
        3. Повертає різні статус-коди в залежності від того, чи була створена нова оцінка

        Приклад запиту:
        {
            "item": 1,
            "score": 4,
            "comment": "Good knowledge of Python",
            "lacks_expertise": false
        }

        Приклад відповіді (нова оцінка):
        {
            "id": 1,
            "item": 1,
            "score": 4,
            "comment": "Good knowledge of Python"
        }

        Приклад відповіді (оновлена оцінка):
        {
            "id": 1,
            "item": 1,
            "score": 5,
            "comment": "Excellent knowledge of Python"
        }
        """
        # Валідуємо вхідні дані
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        # Отримуємо валідовані дані
        validated_data = input_serializer.validated_data
        # Елемент форми, який оцінюється
        # Приклад: <EvaluationFormItem: Python knowledge>
        item = validated_data["item"]

        # Формуємо словник з даними для створення/оновлення оцінки
        # Приклад: {"score": 4, "comment": "Good knowledge", "lacks_expertise": False}
        defaults = {
            "score": validated_data.get("score"),
            "comment": validated_data.get("comment", ""),
            "lacks_expertise": validated_data.get("lacks_expertise", False),
        }

        try:
            # Створюємо нову оцінку або оновлюємо існуючу
            # Приклад: (<EvaluationScore: 4 for Python knowledge>, True) - створена нова
            # Приклад: (<EvaluationScore: 5 for Python knowledge>, False) - оновлена існуюча
            score_obj, created = EvaluationScore.objects.update_or_create(
                item=item,
                interviewer=request.user,
                defaults=defaults,
            )
        except Exception as e:
            # Якщо виникла помилка при створенні/оновленні
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Серіалізуємо результат для відповіді
        # Використовуємо спрощений серіалізатор для відповіді
        output_serializer = EvaluationScoreLiteSerializer(score_obj)

        # Встановлюємо статус-код в залежності від того, чи була створена нова оцінка
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(output_serializer.data, status=status_code)


class EvaluationFeedbackViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """
    Interviewer can create and update feedbacks and submit it.
    """

    # Набір даних, що містить всі відгуки з оптимізованим завантаженням зв'язаних об'єктів
    # Приклад: [<EvaluationFeedback: Feedback by John Doe for Jane Smith>]
    queryset = EvaluationFeedback.objects.select_related(
        "evaluation_form", "interviewer"
    )

    # Класи дозволів, що визначають хто має доступ до цього ViewSet
    # Приклад: Тільки автентифіковані користувачі з правом оцінювання можуть працювати з відгуками
    permission_classes = [permissions.IsAuthenticated, CanScoreOrFeedback]

    def get_serializer_class(self):
        """
        Визначає який серіалізатор використовувати в залежності від дії.

        Приклади:
        - Для submit: EmptySerializer (без даних)
        - Для інших дій: EvaluationFeedbackSerializer (повний набір полів)
        """
        if self.action == "submit":
            # Для відправки відгуку не потрібні дані у відповіді
            return EmptySerializer

        # Для інших дій використовуємо стандартний серіалізатор
        # Приклад: {"pros": "Good knowledge", "cons": "Lacks experience", "decision": "next_step"}
        return EvaluationFeedbackSerializer

    def get_queryset(self):
        """
        Повертає оптимізований набір даних для перевірки дозволів.

        Завантажує пов'язані об'єкти для уникнення додаткових запитів до бази даних.

        Приклад:
        - Відгук з даними про форму оцінювання, менеджерів та інтерв'юера
        """
        # Поточний користувач
        user = self.request.user

        # Оптимізований запит з завантаженням пов'язаних об'єктів
        # Приклад: Відгук з даними про форму, менеджерів та інтерв'юера
        queryset = EvaluationFeedback.objects.select_related(
            "evaluation_form__manager", "evaluation_form__hiring_manager", "interviewer"
        ).prefetch_related(
            "evaluation_form__recruiters",
        )

        # Для адміністратора повертаємо всі дані
        if user.is_superuser:
            return queryset
        # Для звичайного користувача також повертаємо всі дані (для перевірки дозволів)
        return queryset

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """
        Відправляє відгук на перевірку та позначає його як завершений.

        Процес:
        1. Перевіряє чи заповнені всі обов'язкові поля (pros, cons, decision)
        2. Перевіряє чи оцінені всі питання, які оцінили інші інтерв'юери
        3. Позначає відгук як відправлений
        4. Перевіряє чи можна позначити всю форму як завершену

        Приклад успішної відповіді:
        {
            "status": "submitted"
        }

        Приклад помилки:
        {
            "error": "Pros, Cons, and Decision fields must all be filled to submit."
        }
        """
        # Отримуємо об'єкт відгуку
        # Приклад: <EvaluationFeedback: Feedback by John Doe for Jane Smith>
        feedback = self.get_object()
        # Поточний користувач (інтерв'юер)
        interviewer = request.user
        # Форма оцінювання, до якої належить відгук
        evaluation_form = feedback.evaluation_form

        # Отримуємо значення обов'язкових полів
        # Приклад: "Good knowledge of Python", "Lacks experience", "next_step"
        pros = feedback.pros
        cons = feedback.cons
        dec = feedback.decision

        # Перевіряємо чи заповнені всі обов'язкові поля
        if not pros or not cons or not dec:
            return Response(
                {
                    "error": "Pros, Cons, and Decision fields must all be filled to submit."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Отримуємо всі елементи форми з інформацією про те, хто їх оцінив
        form_items_with_scores = (
            EvaluationFormItem.objects.filter(
                form_topic__evaluation_form=evaluation_form
            )
            .annotate(
                # Перевіряємо чи цей елемент оцінив хтось (з score)
                has_any_score=Exists(
                    EvaluationScore.objects.filter(item=OuterRef("pk"))
                ),
                has_my_score=Exists(
                    EvaluationScore.objects.filter(
                        item=OuterRef("pk"), interviewer=interviewer
                    ).filter(Q(score__isnull=False) | Q(lacks_expertise=True))
                ),
            )
            .values("id", "has_any_score", "has_my_score")
        )

        # Формуємо набори ID на основі одного запиту
        required_item_ids = {
            item["id"] for item in form_items_with_scores if item["has_any_score"]
        }
        my_submitted_item_ids = {
            item["id"] for item in form_items_with_scores if item["has_my_score"]
        }

        # # Отримуємо всі елементи форми
        # # Приклад: [1, 2, 3, 4, 5] - ID елементів форми
        # all_form_item_ids = list(
        #     EvaluationFormItem.objects.filter(
        #         form_topic__evaluation_form=evaluation_form
        #     ).values_list("id", flat=True)
        # )
        #
        # # Отримуємо ID елементів, які оцінили інші інтерв'юери
        # # Приклад: {1, 2, 3} - елементи, які хтось оцінив
        # required_item_ids = set(
        #     EvaluationScore.objects.filter(
        #         item__id__in=all_form_item_ids, score__isnull=False
        #     ).values_list("item_id", flat=True)
        # )
        #
        # # Отримуємо ID елементів, які оцінив поточний інтерв'юер
        # # Приклад: {1, 3, 5} - елементи, які оцінив поточний інтерв'юер або позначив як "lacks expertise"
        # my_submitted_item_ids = set(
        #     EvaluationScore.objects.filter(
        #         item__id__in=all_form_item_ids, interviewer=interviewer
        #     )
        #     .filter(Q(score__isnull=False) | Q(lacks_expertise=True))
        #     .values_list("item__id", flat=True)
        # )

        # Знаходимо елементи, які оцінили інші, але не оцінив поточний інтерв'юер
        # Приклад: [2] - елемент, який оцінили інші, але не оцінив поточний інтерв'юер
        missing_to_score_ids = list(required_item_ids - my_submitted_item_ids)
        if missing_to_score_ids:
            return Response(
                {
                    "error": "You have not scored all questions that were asked by your colleagues. "
                    "Please score them or mark them as 'lacks expertise'.",
                    "missing_item_ids": missing_to_score_ids,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Позначаємо відгук як відправлений
        feedback.is_submitted = True
        feedback.save(update_fields=["is_submitted"])

        # Перевіряємо чи можна позначити всю форму як завершену
        # Якщо всі інтерв'юери відправили свої відгуки, форма буде позначена як завершена
        check_and_complete_evaluation(feedback.evaluation_form_id)
        return Response({"status": "submitted"}, status=status.HTTP_200_OK)
