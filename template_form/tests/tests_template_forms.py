import warnings

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.paginator import UnorderedObjectListWarning
from rest_framework import status
from rest_framework.test import APITestCase

from techstack.models import TechStack
from template_form.admin import TemplateFormAdmin
from template_form.models import TemplateForm

User = get_user_model()


class TemplateFormSoftDeleteTests(APITestCase):
    """
    Soft delete of TemplateForm: DELETE hides the row instead of erasing it,
    the slug stays reserved, and restore is admin-only.
    """

    @classmethod
    def setUpTestData(cls):
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
        cls.recruiter = User.objects.create_user(
            email="recruiter@example.com",
            password="pass",
            role="RECRUITER",
        )
        cls.tech_stack = TechStack.objects.create(name="Python")

    def setUp(self):
        self.template = TemplateForm.objects.create(
            name="Python Backend Interview",
            tech_stack=self.tech_stack,
            manager=self.manager,
        )
        self.url = f"/api/template-form/{self.template.slug}/"

    def test_destroy_soft_deletes_with_audit_fields(self):
        self.client.force_authenticate(self.manager)
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # The row must still exist, only hidden: check via the unfiltered manager
        form = TemplateForm.all_objects.get(pk=self.template.pk)
        self.assertTrue(form.is_deleted)
        self.assertEqual(form.deleted_by, self.manager)
        self.assertIsNotNone(form.deleted_at)
        self.assertFalse(TemplateForm.objects.filter(pk=self.template.pk).exists())

    def test_deleted_form_hidden_from_list_and_retrieve(self):
        self.template.soft_delete(self.manager)
        self.client.force_authenticate(self.manager)

        list_response = self.client.get("/api/template-form/")
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertNotIn(self.template.pk, ids)

        retrieve_response = self.client.get(self.url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_second_delete_returns_404(self):
        self.client.force_authenticate(self.manager)
        self.client.delete(self.url)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_destroy_denied_for_non_manager(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(TemplateForm.all_objects.get(pk=self.template.pk).is_deleted)

    def test_slug_stays_reserved_by_deleted_form(self):
        self.template.soft_delete(self.manager)
        clone = TemplateForm.objects.create(
            name="Python Backend Interview",
            tech_stack=self.tech_stack,
        )
        # Slug of the deleted form is still taken, the new one gets a suffix
        self.assertNotEqual(clone.slug, self.template.slug)
        self.assertTrue(clone.slug.startswith(self.template.slug))

    def test_create_working_form_from_deleted_template_404(self):
        # Менеджер, а не рекрутер: TemplateFormViewSet.get_permissions() перекриває
        # permission_classes з декоратора @action, тож create_working_form фактично
        # вимагає IsManagerOrSuperuser попри заявлений IsRecruiter. Тут перевіряємо
        # soft delete, тому беремо роль, яка гарантовано проходить перевірку прав.
        self.template.soft_delete(self.manager)
        self.client.force_authenticate(self.manager)
        response = self.client.post(f"{self.url}create_working_form/", data={})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_sees_deleted_and_restore_clears_fields(self):
        self.template.soft_delete(self.manager)
        admin_instance = TemplateFormAdmin(TemplateForm, admin_site=admin.site)

        admin_qs = admin_instance.get_queryset(request=None)
        self.assertIn(self.template.pk, admin_qs.values_list("pk", flat=True))

        admin_instance.restore_selected(
            request=None,
            queryset=TemplateForm.all_objects.filter(pk=self.template.pk),
        )
        form = TemplateForm.objects.get(pk=self.template.pk)
        self.assertFalse(form.is_deleted)
        self.assertIsNone(form.deleted_by)
        self.assertIsNone(form.deleted_at)

        # The restored form is reachable through the API again
        self.client.force_authenticate(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TemplateFormOrderingTests(APITestCase):
    """
    BUG-6: the list endpoint paginated over an unordered queryset, so a row
    could repeat or vanish between ?page=1 and ?page=2 - the order without an
    ORDER BY depends on the query plan, which changes as the table grows.

    The -pk tiebreaker is not decoration: created_at is auto_now_add, and
    clone_template_to_working() stamps a whole batch inside one transaction,
    so equal timestamps are the normal case here, not an edge case.
    """

    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(
            email="ordering-manager@example.com",
            password="pass",
            role="MANAGER",
        )
        cls.tech_stack = TechStack.objects.create(name="Python")

    def setUp(self):
        # Один timestamp на всі три: саме так їх створює клонування, і саме
        # тут тайбрейкер вирішує, чи порядок детермінований.
        self.forms = [
            TemplateForm.objects.create(
                name=f"Ordering probe {index}",
                tech_stack=self.tech_stack,
                manager=self.manager,
            )
            for index in range(3)
        ]

    def test_default_queryset_carries_an_order_by(self):
        self.assertTrue(TemplateForm.objects.all().ordered)

    def test_list_endpoint_does_not_paginate_an_unordered_queryset(self):
        self.client.force_authenticate(self.manager)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            response = self.client.get("/api/template-form/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        unordered = [
            str(entry.message)
            for entry in caught
            if issubclass(entry.category, UnorderedObjectListWarning)
        ]
        self.assertEqual(unordered, [])

    def test_meta_ordering_is_newest_first_with_a_unique_tiebreaker(self):
        self.assertEqual(TemplateForm._meta.ordering, ["-created_at", "-pk"])
