from rest_framework import permissions

from evaluation_form.models import (
    EvaluationForm,  # Модель оцінювальної форми, наприклад: id=1, status='IN_PROGRESS'
    EvaluationFeedback,  # Модель відгуку оцінювання, наприклад: id=1, is_submitted=False
    EvaluationScore,  # Модель оцінки, наприклад: id=1, score=4
    EvaluationFormItem,  # Модель елемента форми, наприклад: id=1, name='Technical Skills'
)


class CanScoreOrFeedback(permissions.BasePermission):
    """
    Permission for 'EvaluationScoreViewSet' and 'EvaluationFeedbackViewSet'
    Check:
    - READ (GET):
        - if form is 'COMPLETED': Can see any is_authenticated=True user.
        - if form is 'IN_PROGRESS': Can see  author and admins (superuser, manager, hm, recruiter).
    - WRITE (POST/PATCH):
        - Can edit/create ONLY author, IF form is_submitted=False.
    """

    # Повідомлення про помилку, яке буде показано користувачу при відмові в доступі
    # Приклад: "You can no longer edit this evaluation."
    message = "You can no longer edit this evaluation."

    def has_object_permission(self, request, view, obj):
        """
        Перевіряє чи має користувач доступ до конкретного об'єкта (EvaluationFeedback або EvaluationScore)
        Приклад виклику: permission.has_object_permission(request, view, feedback_obj)
        """
        # Поточний користувач з запиту
        # Приклад: user = User(id=1, username='john_doe')
        user = request.user

        # Суперкористувачі мають повний доступ
        # Приклад: якщо user.is_superuser == True, повертає True
        if user.is_superuser:
            return True

        try:
            # Визначаємо тип об'єкта та отримуємо відповідні дані
            if isinstance(obj, EvaluationFeedback):
                # Якщо об'єкт - відгук, отримуємо його напряму
                # Приклад: feedback = EvaluationFeedback(id=1, is_submitted=False)
                feedback = obj
                # Форма оцінювання, пов'язана з відгуком
                # Приклад: evaluation_form = EvaluationForm(id=1, status='IN_PROGRESS')
                evaluation_form = obj.evaluation_form
                # Інтерв'юер, який створив відгук
                # Приклад: interviewer = User(id=2, username='interviewer1')
                interviewer = obj.interviewer

            elif isinstance(obj, EvaluationScore):
                # Якщо об'єкт - оцінка, отримуємо форму через зв'язки
                # Приклад: evaluation_form = EvaluationForm(id=1, status='IN_PROGRESS')
                evaluation_form = obj.item.form_topic.evaluation_form
                # Інтерв'юер, який поставив оцінку
                # Приклад: interviewer = User(id=2, username='interviewer1')
                interviewer = obj.interviewer

                # Знаходимо відповідний відгук для цього інтерв'юера та форми
                # Приклад: feedback = EvaluationFeedback(id=1, is_submitted=False)
                feedback = EvaluationFeedback.objects.get(
                    evaluation_form=evaluation_form, interviewer=interviewer
                )
            else:
                # Якщо об'єкт не є ні відгуком, ні оцінкою - відмовляємо в доступі
                return False
        except (EvaluationFeedback.DoesNotExist, AttributeError, TypeError):
            # При помилці з пошуком відгуку або неправильній структурі даних
            return False

        # Перевірка для безпечних методів (GET, HEAD, OPTIONS)
        # Приклад: request.method == 'GET'
        if request.method in permissions.SAFE_METHODS:

            # Якщо форма завершена, будь-який авторизований користувач може її переглядати
            # Приклад: evaluation_form.status == 'COMPLETED'
            if evaluation_form.status == EvaluationForm.Status.COMPLETED:
                return user.is_authenticated

            # Перевіряємо чи є користувач менеджером форми
            # Приклад: is_form_manager = True, якщо user.id == evaluation_form.manager.id
            is_form_manager = user == evaluation_form.manager

            # Перевіряємо чи є користувач HR-менеджером
            # Приклад: is_hiring_manager = True, якщо user.id == evaluation_form.hiring_manager.id
            is_hiring_manager = user == evaluation_form.hiring_manager

            # Перевіряємо чи є користувач рекрутером, призначеним до форми
            # Приклад: is_assigned_recruiter = True, якщо user є в списку recruiters
            is_assigned_recruiter = False

            # Перевірка кешу для оптимізації запитів
            # Приклад: cache = {'recruiters': [<User: recruiter1>, <User: recruiter2>]}
            cache = getattr(evaluation_form, "_prefetched_objects_cache", None)
            if cache is not None and "recruiters" in cache:
                # Використовуємо кеш для перевірки
                # Приклад: user.pk = 3, {r.pk for r in recruiters} = {1, 3, 5}
                is_assigned_recruiter = user.pk in {
                    r.pk for r in evaluation_form.recruiters.all()
                }
            else:
                # Робимо запит до бази даних, якщо кеш недоступний
                # Приклад: evaluation_form.recruiters.filter(pk=3).exists() = True
                is_assigned_recruiter = evaluation_form.recruiters.filter(
                    pk=user.pk
                ).exists()

            # Перевіряємо чи є користувач адміністратором форми (менеджер, HR або рекрутер)
            # Приклад: is_admin_user = True, якщо будь-яка з умов вище True
            is_admin_user = (
                is_form_manager or is_hiring_manager or is_assigned_recruiter
            )

            # Перевіряємо чи є користувач автором відгуку/оцінки
            # Приклад: is_author = True, якщо user.id == interviewer.id
            is_author = interviewer == user

            # Дозволяємо доступ, якщо користувач є автором або адміністратором
            return is_author or is_admin_user

        # Перевірка статусу форми - якщо форма в статусі "PENDING", редагування заборонено
        # Приклад: evaluation_form.status == 'PENDING'
        if evaluation_form.status == EvaluationForm.Status.PENDING:
            self.message = "This interview has not started yet."
            return False

        # Перевіряємо чи є користувач автором відгуку/оцінки
        # Приклад: is_author = True, якщо user.id == interviewer.id
        is_author = interviewer == user

        # Якщо користувач не є автором, забороняємо редагування
        if not is_author:
            self.message = "You can only edit your own scores and feedback."

        try:
            # Отримуємо об'єкт відгуку для перевірки статусу
            if isinstance(obj, EvaluationFeedback):
                # Якщо об'єкт вже є відгуком, використовуємо його
                # Приклад: feedback = EvaluationFeedback(id=1, is_submitted=False)
                feedback = obj
            else:
                # Інакше знаходимо відгук для поточного користувача та форми
                # Приклад: feedback = EvaluationFeedback(id=1, is_submitted=False)
                feedback = EvaluationFeedback.objects.get(
                    evaluation_form=evaluation_form, interviewer=user
                )
        except EvaluationFeedback.DoesNotExist:
            # Якщо відгук не знайдено, забороняємо доступ
            return False

        # Перевіряємо чи відгук ще не відправлений
        # Приклад: is_not_submitted = True, якщо feedback.is_submitted == False
        is_not_submitted = not feedback.is_submitted

        # Перевіряємо чи форма ще не завершена
        # Приклад: is_not_completed = True, якщо evaluation_form.status != 'COMPLETED'
        is_not_completed = evaluation_form.status != EvaluationForm.Status.COMPLETED

        # Встановлюємо відповідне повідомлення про помилку
        if not is_not_submitted:
            self.message = "You have already submitted your feedback."
        elif not is_not_completed:
            self.message = "This evaluation is completed and locked."

        # Дозволяємо редагування тільки якщо відгук не відправлений і форма не завершена
        return is_not_submitted and is_not_completed


class CanCreateScore(permissions.BasePermission):
    """
    Permission for 'EvaluationScoreViewSet.create()' (POST / upsert).
    Chack, that feedback NOT "submitted", BEFORE create/'update' score.
    """

    # Повідомлення про помилку, яке буде показано користувачу при відмові в доступі
    # Приклад: "You cannot add or edit scores in submitted form."
    message = "You cannot add or edit scores in submitted form."

    def has_permission(self, request, view):
        """
        Перевіряє чи має користувач доступ до створення/оновлення оцінок
        Приклад виклику: permission.has_permission(request, view)
        """
        # Поточний користувач з запиту
        # Приклад: user = User(id=1, username='john_doe')
        user = request.user

        # Перевіряємо чи користувач авторизований
        # Приклад: якщо user is None або user.is_authenticated == False, повертає False
        if not user or not user.is_authenticated:
            return False

        # Суперкористувачі мають повний доступ
        # Приклад: якщо user.is_superuser == True, повертає True
        if user.is_superuser:
            return True

        # Перевіряємо метод запиту - дозволяємо всі методи крім POST без додаткових перевірок
        # Приклад: якщо request.method == 'GET', повертає True
        if request.method != "POST":
            return True

        # Отримуємо ID елемента форми з даних запиту
        # Приклад: item_id = 42 з request.data = {'item': 42, 'score': 5}
        item_id = request.data.get("item")

        # Якщо ID елемента не вказано, дозволяємо запит (буде оброблено на рівні валідації)
        if not item_id:
            return True

        try:
            # Отримуємо елемент форми з бази даних разом із зв'язаними об'єктами
            # Приклад: item = EvaluationFormItem(id=42, name='Technical Skills')
            item = EvaluationFormItem.objects.select_related(
                "form_topic__evaluation_form"
            ).get(pk=item_id)

            # Отримуємо форму оцінювання через зв'язки
            # Приклад: evaluation_form = EvaluationForm(id=1, status='IN_PROGRESS')
            evaluation_form = item.form_topic.evaluation_form

            # Перевіряємо статус форми - якщо форма завершена, забороняємо редагування
            # Приклад: якщо evaluation_form.status == 'COMPLETED', повертає False
            if evaluation_form.status == EvaluationForm.Status.COMPLETED:
                self.message = "This evaluation is completed and locked."
                return False

            # Перевіряємо статус форми - якщо інтерв'ю ще не почалося, забороняємо редагування
            # Приклад: якщо evaluation_form.status == 'PENDING', повертає False
            if evaluation_form.status == EvaluationForm.Status.PENDING:
                self.message = "This interview has not started yet."
                return False

            # Шукаємо відгук користувача для цієї форми
            # Приклад: feedback = EvaluationFeedback(id=1, is_submitted=False)
            feedback = EvaluationFeedback.objects.filter(
                evaluation_form=evaluation_form, interviewer=user
            ).first()

            # Перевіряємо статус відгуку
            if feedback:
                # Якщо відгук вже відправлений, забороняємо зміну оцінок
                # Приклад: якщо feedback.is_submitted == True, повертає False
                if feedback.is_submitted:
                    self.message = "You have already submitted your feedback and cannot change scores."
                    return False
            else:
                # Якщо відгуку немає, перевіряємо чи користувач є інтерв'юером для цієї форми
                # Приклад: якщо user не в списку interviewers, повертає False
                if not evaluation_form.interviewers.filter(pk=user.pk).exists():
                    self.message = (
                        "You are not assigned as an interviewer for this form."
                    )
                    return False

            # Якщо всі перевірки пройдені успішно, дозволяємо доступ
            return True

        except (EvaluationFormItem.DoesNotExist, EvaluationFeedback.DoesNotExist):
            # Якщо елемент форми не знайдено або виникла помилка з відгуком
            self.message = "Invalid item ID or you do not have feedback on this form."
            return False

        except (AttributeError, TypeError):
            # При помилці атрибуту або типу (наприклад, неправильна структура даних)
            self.message = "Invalid request data."
            return False
