from django.contrib import admin
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from project.models import Project
from techstack.models import TechStack
from working_form.admin import WorkingFormAdmin
from working_form.models import WorkingForm

User = get_user_model()


class WorkingFormSoftDeleteTests(APITestCase):
    """
    Soft delete of WorkingForm. DELETE used to hard-delete the row because
    the viewset had no `perform_destroy`; these tests pin the fixed contract.
    """

    @classmethod
    def setUpTestData(cls):
        # create_user defaults to is_staff=True in this project, which is
        # exactly what IsAdminUser on `destroy` requires
        cls.admin = User.objects.create_user(
            email="admin@example.com",
            password="pass",
            role="MANAGER",
        )
        cls.non_staff = User.objects.create_user(
            email="plain@example.com",
            password="pass",
            role="INTERVIEWER",
            is_staff=False,
        )
        cls.tech_stack = TechStack.objects.create(name="Python")
        cls.project = Project.objects.create(name="Evaluation Service")

    def setUp(self):
        self.form = WorkingForm.objects.create(
            name="Working form: Junior Python (Evaluation Service)",
            vacancy="Python Engineer",
            level=WorkingForm.Level.JUNIOR,
            project=self.project,
            tech_stack=self.tech_stack,
        )
        self.url = f"/api/working-form/{self.form.slug}/"

    def test_destroy_soft_deletes_with_audit_fields(self):
        self.client.force_authenticate(self.admin)
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # The row must survive in the database - this is the bug being fixed:
        # without perform_destroy DRF removed it physically
        form = WorkingForm.all_objects.get(pk=self.form.pk)
        self.assertTrue(form.is_deleted)
        self.assertEqual(form.deleted_by, self.admin)
        self.assertIsNotNone(form.deleted_at)
        self.assertFalse(WorkingForm.objects.filter(pk=self.form.pk).exists())

    def test_soft_delete_does_not_rename_form(self):
        # soft_delete saves with update_fields, otherwise WorkingForm.save()
        # would regenerate name/slug on a full save of an existing object
        original_name, original_slug = self.form.name, self.form.slug
        self.form.soft_delete(self.admin)
        form = WorkingForm.all_objects.get(pk=self.form.pk)
        self.assertEqual(form.name, original_name)
        self.assertEqual(form.slug, original_slug)

    def test_deleted_form_hidden_from_list_and_retrieve(self):
        self.form.soft_delete(self.admin)
        self.client.force_authenticate(self.admin)

        list_response = self.client.get("/api/working-form/")
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertNotIn(self.form.pk, ids)

        retrieve_response = self.client.get(self.url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_second_delete_returns_404(self):
        self.client.force_authenticate(self.admin)
        self.client.delete(self.url)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_destroy_denied_for_non_staff(self):
        self.client.force_authenticate(self.non_staff)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(WorkingForm.all_objects.get(pk=self.form.pk).is_deleted)

    def test_admin_sees_deleted_and_restore_clears_fields(self):
        self.form.soft_delete(self.admin)
        admin_instance = WorkingFormAdmin(WorkingForm, admin_site=admin.site)

        admin_qs = admin_instance.get_queryset(request=None)
        self.assertIn(self.form.pk, admin_qs.values_list("pk", flat=True))

        admin_instance.restore_selected(
            request=None,
            queryset=WorkingForm.all_objects.filter(pk=self.form.pk),
        )
        form = WorkingForm.objects.get(pk=self.form.pk)
        self.assertFalse(form.is_deleted)
        self.assertIsNone(form.deleted_by)
        self.assertIsNone(form.deleted_at)

        # The restored form is reachable through the API again
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
