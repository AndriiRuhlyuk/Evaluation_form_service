import tempfile
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from evaluation_form.admin import EvaluationFormAdmin
from evaluation_form.models import Candidate, EvaluationForm
from evaluation_form.tasks import update_evaluation_statuses
from techstack.models import TechStack

User = get_user_model()

TEMP_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class EvaluationFormSoftDeleteTests(APITestCase):
    """
    Soft delete of EvaluationForm: PENDING and COMPLETED forms hide, an
    IN_PROGRESS form refuses deletion (400), and the report file linked
    from the PeopleForce note stays untouched.
    """

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            email="recruiter@example.com",
            password="pass",
            role="RECRUITER",
        )
        cls.interviewer = User.objects.create_user(
            email="interviewer@example.com",
            password="pass",
            role="INTERVIEWER",
        )
        cls.tech_stack = TechStack.objects.create(name="Python")
        cls.candidate = Candidate.objects.create(
            full_name="Test Candidate",
            email="candidate@example.com",
            pf_link="https://example.com/candidate",
        )

    def _create_form(self, form_status, name, **extra):
        """
        Creates an evaluation form owned by the recruiter (manager), so the
        user-scoped `get_queryset` of the viewset can see it.
        """
        return EvaluationForm.objects.create(
            candidate=self.candidate,
            tech_stack=self.tech_stack,
            manager=self.recruiter,
            status=form_status,
            interview_datetime=timezone.now() + timedelta(days=1),
            name=name,
            vacancy_snapshot="Python Engineer",
            level_snapshot="junior",
            **extra,
        )

    def _url(self, form):
        return f"/api/evaluation-form/evaluation-forms/{form.slug}/"

    def test_destroy_pending_soft_deletes_with_audit_fields(self):
        form = self._create_form(EvaluationForm.Status.PENDING, "Eval pending 1")
        self.client.force_authenticate(self.recruiter)
        response = self.client.delete(self._url(form))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        row = EvaluationForm.all_objects.get(pk=form.pk)
        self.assertTrue(row.is_deleted)
        self.assertEqual(row.deleted_by, self.recruiter)
        self.assertIsNotNone(row.deleted_at)
        self.assertFalse(EvaluationForm.objects.filter(pk=form.pk).exists())

    def test_destroy_in_progress_returns_400_and_keeps_row_live(self):
        form = self._create_form(EvaluationForm.Status.IN_PROGRESS, "Eval running 1")
        self.client.force_authenticate(self.recruiter)
        response = self.client.delete(self._url(form))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EvaluationForm.all_objects.get(pk=form.pk).is_deleted)

    def test_destroy_completed_keeps_report_file(self):
        form = self._create_form(
            EvaluationForm.Status.COMPLETED,
            "Eval completed 1",
            report_file=SimpleUploadedFile(
                "report.html", b"<html>report</html>", content_type="text/html"
            ),
        )
        self.client.force_authenticate(self.recruiter)
        response = self.client.delete(self._url(form))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        row = EvaluationForm.all_objects.get(pk=form.pk)
        self.assertTrue(row.is_deleted)
        # The PeopleForce note links to this file in media - it must survive
        self.assertTrue(row.report_file)
        self.assertTrue(row.report_file.storage.exists(row.report_file.name))

    def test_deleted_form_hidden_from_list_and_retrieve(self):
        form = self._create_form(EvaluationForm.Status.PENDING, "Eval hidden 1")
        form.soft_delete(self.recruiter)
        self.client.force_authenticate(self.recruiter)

        list_response = self.client.get("/api/evaluation-form/evaluation-forms/")
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertNotIn(form.pk, ids)

        retrieve_response = self.client.get(self._url(form))
        self.assertEqual(retrieve_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_destroy_denied_for_non_recruiter(self):
        form = self._create_form(EvaluationForm.Status.PENDING, "Eval protected 1")
        form.interviewers.add(self.interviewer)
        self.client.force_authenticate(self.interviewer)
        response = self.client.delete(self._url(form))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EvaluationForm.all_objects.get(pk=form.pk).is_deleted)

    def test_status_task_ignores_soft_deleted_pending_form(self):
        soon = timezone.now() + timedelta(minutes=30)
        live = self._create_form(EvaluationForm.Status.PENDING, "Eval live 1")
        deleted = self._create_form(EvaluationForm.Status.PENDING, "Eval gone 1")
        EvaluationForm.all_objects.filter(pk__in=[live.pk, deleted.pk]).update(
            interview_datetime=soon
        )
        deleted.soft_delete(self.recruiter)

        update_evaluation_statuses()

        self.assertEqual(
            EvaluationForm.all_objects.get(pk=live.pk).status,
            EvaluationForm.Status.IN_PROGRESS,
        )
        # The deleted PENDING form must stay untouched by the celery task
        self.assertEqual(
            EvaluationForm.all_objects.get(pk=deleted.pk).status,
            EvaluationForm.Status.PENDING,
        )

    def test_admin_sees_deleted_and_restore_clears_fields(self):
        form = self._create_form(EvaluationForm.Status.PENDING, "Eval restore 1")
        form.soft_delete(self.recruiter)
        admin_instance = EvaluationFormAdmin(EvaluationForm, admin_site=admin.site)

        admin_qs = admin_instance.get_queryset(request=None)
        self.assertIn(form.pk, admin_qs.values_list("pk", flat=True))

        admin_instance.restore_selected(
            request=None,
            queryset=EvaluationForm.all_objects.filter(pk=form.pk),
        )
        row = EvaluationForm.objects.get(pk=form.pk)
        self.assertFalse(row.is_deleted)
        self.assertIsNone(row.deleted_by)
        self.assertIsNone(row.deleted_at)

        # The restored form is reachable through the API again
        self.client.force_authenticate(self.recruiter)
        response = self.client.get(self._url(form))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EvaluationFormOrderingTests(APITestCase):
    """
    BUG-6, the EvaluationForm half - and deliberately a smaller test than the
    other two apps get.

    This model already ordered by -interview_datetime, so DRF never warned and
    there is no behavioural failure to reproduce: the defect is that the sort
    key is not unique, and rows sharing an interview slot fall back to whatever
    the query plan returns. A test asserting "ties come back in pk order" would
    pass before the fix on any small table, which proves nothing. So this is an
    explicit contract assertion instead, and it is honest about being one.
    """

    def test_meta_ordering_keeps_a_unique_tiebreaker(self):
        self.assertEqual(EvaluationForm._meta.ordering, ["-interview_datetime", "-pk"])
