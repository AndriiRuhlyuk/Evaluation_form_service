from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APITestCase

from question.models import Question
from question.permissions import IsEmployee
from question.views import QuestionViewSet
from template_form.permissions import IsManagerOrSuperuser
from topic.models import Topic

User = get_user_model()

LIST_URL = "/api/questions/"


class QuestionTestMixin:
    """
    Shared actors and one topic. `Question` is reference data: it has no
    soft-delete manager, so every test reads it back through the plain
    `Question.objects` - there is no `all_objects` here.
    """

    @classmethod
    def setUpTestData(cls):
        # create_user defaults to is_staff=True, so role is what actually
        # separates these two: IsManagerOrSuperuser only looks at role.
        cls.manager = User.objects.create_user(
            email="manager@example.com",
            password="pass",
            role="MANAGER",
        )
        cls.interviewer = User.objects.create_user(
            email="interviewer@example.com",
            password="pass",
            role="INTERVIEWER",
        )
        cls.topic = Topic.objects.create(name="Databases")


class QuestionCreateTests(QuestionTestMixin, APITestCase):
    """
    Creation is the only place authorship is set. `QuestionSerializer` does
    not expose `question_author`, so the value can only come from
    `perform_create` - a regression there would silently produce ownerless
    questions instead of failing.
    """

    def test_create_sets_request_user_as_author(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            LIST_URL,
            {
                "question_text": "Explain MVCC in PostgreSQL",
                "topic": self.topic.pk,
                "difficulty": Question.QuestionDifficulty.HARD,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        question = Question.objects.get(pk=response.data["id"])
        self.assertEqual(question.question_author, self.manager)
        self.assertEqual(question.difficulty, Question.QuestionDifficulty.HARD)
        # Untouched model defaults - the serializer accepts neither of them
        self.assertEqual(question.source, Question.QuestionSource.TEMPLATE)
        self.assertTrue(question.is_active)

    def test_create_denied_for_interviewer(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.post(
            LIST_URL,
            {"question_text": "Denied", "topic": self.topic.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Question.objects.filter(question_text="Denied").exists())

    def test_create_denied_for_anonymous(self):
        response = self.client.post(
            LIST_URL,
            {"question_text": "Anonymous", "topic": self.topic.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Question.objects.filter(question_text="Anonymous").exists())


class QuestionSoftDeleteTests(QuestionTestMixin, APITestCase):
    """
    DELETE flips `is_active` instead of removing the row. Unlike the three
    form stages, nothing filters that flag at the model layer - only
    `get_queryset()` does, and only for `list`. These tests pin the
    consequences of that asymmetry.
    """

    def setUp(self):
        self.question = Question.objects.create(
            question_text="What is a write-ahead log?",
            topic=self.topic,
            difficulty=Question.QuestionDifficulty.MEDIUM,
        )
        self.detail_url = f"/api/questions/{self.question.pk}/"

    def test_destroy_soft_deletes_and_keeps_row(self):
        self.client.force_authenticate(self.manager)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # The row must survive - perform_destroy only flips the flag
        question = Question.objects.get(pk=self.question.pk)
        self.assertFalse(question.is_active)

    def test_destroy_denied_for_interviewer(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Question.objects.get(pk=self.question.pk).is_active)

    def test_second_delete_returns_204_not_404(self):
        # Deliberately different from WorkingForm, where the manager hides
        # deleted rows and the second DELETE 404s. Here `get_queryset()`
        # filters only on `list`, so the row stays reachable by pk forever.
        self.client.force_authenticate(self.manager)
        self.client.delete(self.detail_url)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Question.objects.get(pk=self.question.pk).is_active)

    def test_deleted_question_hidden_from_list_but_still_retrievable(self):
        self.client.force_authenticate(self.manager)
        self.client.delete(self.detail_url)

        list_response = self.client.get(LIST_URL)
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertNotIn(self.question.pk, ids)

        # Same asymmetry as above: retrieve bypasses the is_active filter
        retrieve_response = self.client.get(self.detail_url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertFalse(retrieve_response.data["is_active"])


class QuestionRestoreTests(QuestionTestMixin, APITestCase):
    """
    The `restore` action is the only writer that is not a standard CRUD verb,
    and its docstring claims "author or interviewer" while `get_permissions`
    hands it to IsManagerOrSuperuser. The code is the contract.
    """

    def setUp(self):
        self.question = Question.objects.create(
            question_text="Describe two-phase commit",
            topic=self.topic,
            is_active=False,
        )
        self.restore_url = f"/api/questions/{self.question.pk}/restore/"

    def test_restore_reactivates_question(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["question"]["is_active"])
        self.assertTrue(Question.objects.get(pk=self.question.pk).is_active)

    def test_restore_of_active_question_returns_400(self):
        self.question.is_active = True
        self.question.save(update_fields=["is_active"])
        self.client.force_authenticate(self.manager)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Question is already active")

    def test_restore_denied_for_interviewer(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # A leaked restore would resurrect a question the team retired
        self.assertFalse(Question.objects.get(pk=self.question.pk).is_active)

    def test_restore_of_unknown_pk_returns_404(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post("/api/questions/999999/restore/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class QuestionListFilterTests(QuestionTestMixin, APITestCase):
    """
    `get_queryset()` hides inactive questions only when `is_active` is absent
    from the query string. Passing it explicitly must hand control back to
    django-filter, otherwise `?is_active=false` would return nothing.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.active = Question.objects.create(
            question_text="Active question",
            topic=cls.topic,
        )
        cls.inactive = Question.objects.create(
            question_text="Inactive question",
            topic=cls.topic,
            is_active=False,
        )

    def test_list_hides_inactive_by_default(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(self.active.pk, ids)
        self.assertNotIn(self.inactive.pk, ids)

    def test_list_with_is_active_false_returns_only_inactive(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.get(LIST_URL, {"is_active": "false"})

        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [self.inactive.pk])

    def test_list_requires_authentication(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class QuestionPermissionWiringTests(APITestCase):
    """
    `IsEmployee` is declared in `permission_classes` but `get_permissions()`
    is overridden and never consults that attribute, so the class is dead
    code. Pinning it here means whoever restores it will see this test fail
    instead of assuming the check was live all along.
    """

    def _permission_types(self, action):
        view = QuestionViewSet()
        view.action = action
        return [type(permission) for permission in view.get_permissions()]

    def test_is_employee_is_declared_but_never_applied(self):
        self.assertIn(IsEmployee, QuestionViewSet.permission_classes)
        for action in ("list", "retrieve", "create", "destroy", "restore"):
            self.assertNotIn(IsEmployee, self._permission_types(action))

    def test_read_actions_require_only_authentication(self):
        for action in ("list", "retrieve"):
            self.assertEqual(self._permission_types(action), [IsAuthenticated])

    def test_write_actions_require_manager_or_superuser(self):
        for action in ("create", "update", "partial_update", "destroy", "restore"):
            self.assertEqual(
                self._permission_types(action),
                [IsAuthenticated, IsManagerOrSuperuser],
            )
