from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APITestCase

from project.models import Project
from project.permissions import IsEmployee
from project.views import ProjectViewSet

User = get_user_model()

LIST_URL = "/api/projects/"


class ProjectTestMixin:
    """
    Shared actors. `Project` is reference data with a plain `is_active`
    flag and the default manager - there is no `all_objects` here, so
    `Project.objects` spans active and soft-deleted rows alike. That is
    the right manager for asserting a row survived a DELETE, but it also
    means a bare `.exists()` proves nothing about visibility: every read
    that cares must assert `is_active` alongside it.

    Two roles are created on purpose: `IsEmployee` only asks whether the
    user is an `Employee` instance, and `Employee` is AUTH_USER_MODEL, so
    role is irrelevant to every check in this app. The pair exists to pin
    that, not to distinguish privilege.
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


class ProjectCreateTests(ProjectTestMixin, APITestCase):
    """
    `get_permissions()` hands `create` to `AllowAny`, so this endpoint is
    writable without credentials. That is pinned below rather than fixed -
    a behaviour change is the product owner's call.
    """

    def test_create_returns_201_and_writes_row(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.post(
            LIST_URL,
            {"name": "Apollo", "description": "Payments platform"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        project = Project.objects.get(pk=response.data["id"])
        self.assertEqual(project.description, "Payments platform")
        # Model default survives a JSON create: the key is absent from the
        # body, so the serializer leaves the field alone
        self.assertTrue(project.is_active)

    def test_create_via_form_data_lands_inactive(self):
        # Pinned discrepancy, and the sharpest one in this app.
        # `ProjectSerializer` exposes `is_active`, and DRF's BooleanField
        # sets `default_empty_html = False`: for form-encoded bodies a
        # missing boolean is read as False rather than as "not supplied".
        # The identical body sent as JSON yields is_active=True, so the same
        # request produces two different rows depending on Content-Type -
        # and the form-encoded one is invisible in the default list.
        # Positive control: without a project that must stay visible, the
        # assertNotIn below would also pass against an empty list.
        visible = Project.objects.create(name="Stays visible")

        self.client.force_authenticate(self.recruiter)
        response = self.client.post(LIST_URL, {"name": "Born inactive"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        project = Project.objects.get(pk=response.data["id"])
        self.assertFalse(project.is_active)

        list_response = self.client.get(LIST_URL)
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertIn(visible.pk, ids)
        self.assertNotIn(project.pk, ids)

    def test_create_is_open_to_anonymous(self):
        # Discrepancy pinned deliberately: `permission_classes` declares
        # IsAuthenticated + IsEmployee, but `get_permissions()` never reads
        # that attribute and returns AllowAny for create. Whoever tightens
        # this gets a red test instead of a silent contract change.
        response = self.client.post(
            LIST_URL,
            {"name": "Anonymous"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # JSON keeps the row active, so this asserts a project a real client
        # can see - not a row that only exists in the table
        project = Project.objects.get(name="Anonymous")
        self.assertTrue(project.is_active)

    def test_create_with_duplicate_name_returns_400(self):
        Project.objects.create(name="Apollo")
        self.client.force_authenticate(self.recruiter)
        response = self.client.post(LIST_URL, {"name": "Apollo"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Naming the field matters: any unrelated regression that turns some
        # other field required would also produce a bare 400
        self.assertIn("name", response.data)
        # `name` is unique at the model level; a second row would mean the
        # constraint was dropped without anyone noticing
        self.assertEqual(Project.objects.filter(name="Apollo").count(), 1)


class ProjectRetrieveTests(ProjectTestMixin, APITestCase):
    """
    `get_serializer_class()` switches on the action. Detail views must use
    the full `ProjectSerializer`; picking the list serializer here would
    drop `description` from every detail response.
    """

    def setUp(self):
        self.project = Project.objects.create(
            name="Hermes",
            description="Internal messaging",
        )
        self.detail_url = f"/api/projects/{self.project.pk}/"

    def test_retrieve_uses_full_serializer(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Internal messaging")
        # `detail` belongs to the list serializer only
        self.assertNotIn("detail", response.data)

    def test_retrieve_is_public_for_anonymous(self):
        # Pinned discrepancy: for read actions `get_permissions()` returns an
        # empty list, which DRF treats as "no checks at all". The equivalent
        # question endpoint answers 401 - the two apps disagree.
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Hermes")

    def test_partial_update_changes_row(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.patch(self.detail_url, {"name": "Hermes II"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Hermes II")
        # PATCH is partial, so the untouched flag must survive it
        self.assertTrue(self.project.is_active)

    def test_partial_update_is_open_to_anonymous(self):
        # The update branch of `get_permissions()` also returns AllowAny.
        # Pinned over HTTP, because the introspection tests below only show
        # what the source says, not that the request actually goes through.
        response = self.client.patch(self.detail_url, {"name": "Hijacked"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Hijacked")

    def test_put_without_is_active_deactivates_project(self):
        # The form-encoded boolean trap again, on the update path: a full
        # PUT that omits `is_active` silently retires the project. PATCH is
        # immune because DRF skips missing fields when partial=True.
        self.client.force_authenticate(self.recruiter)
        response = self.client.put(self.detail_url, {"name": "Hermes"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_active)


class ProjectSoftDeleteTests(ProjectTestMixin, APITestCase):
    """
    DELETE flips `is_active` instead of removing the row. Nothing filters
    that flag at the model layer - only `get_queryset()` does, and only for
    `list`. These tests pin the consequences of that asymmetry.
    """

    def setUp(self):
        self.project = Project.objects.create(
            name="Orion",
            description="Data warehouse",
        )
        # Positive control for the list assertions: with a single project in
        # the table, "deleted row is absent" would also hold for an endpoint
        # that returned nothing at all.
        self.untouched = Project.objects.create(name="Perseus")
        self.detail_url = f"/api/projects/{self.project.pk}/"

    def test_destroy_soft_deletes_and_keeps_row(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # The row must survive - perform_destroy only flips the flag
        project = Project.objects.get(pk=self.project.pk)
        self.assertFalse(project.is_active)

    def test_destroy_denied_for_anonymous(self):
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(Project.objects.get(pk=self.project.pk).is_active)

    def test_destroy_allowed_for_any_authenticated_role(self):
        # `IsEmployee` is an isinstance check against AUTH_USER_MODEL, so an
        # interviewer passes it exactly like a recruiter. Role-based reading
        # of this endpoint would be wrong.
        self.client.force_authenticate(self.interviewer)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.get(pk=self.project.pk).is_active)

    def test_second_delete_returns_204_not_404(self):
        # Deliberately different from the three form stages, where the
        # manager hides deleted rows and the second DELETE 404s. Here
        # `get_queryset()` filters only on `list`, so the row stays
        # reachable by pk forever.
        self.client.force_authenticate(self.recruiter)
        first = self.client.delete(self.detail_url)
        response = self.client.delete(self.detail_url)

        # Both codes are asserted: a first DELETE that started answering 200
        # would be a contract change this test exists to notice
        self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.get(pk=self.project.pk).is_active)

    def test_deleted_project_hidden_from_list_but_still_retrievable(self):
        self.client.force_authenticate(self.recruiter)
        self.client.delete(self.detail_url)

        list_response = self.client.get(LIST_URL)
        ids = [row["id"] for row in list_response.data["results"]]
        self.assertIn(self.untouched.pk, ids)
        self.assertNotIn(self.project.pk, ids)

        # Same asymmetry as above: retrieve bypasses the is_active filter
        retrieve_response = self.client.get(self.detail_url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertFalse(retrieve_response.data["is_active"])


class ProjectRestoreTests(ProjectTestMixin, APITestCase):
    """
    `restore` is the only writer that is not a standard CRUD verb. It is
    also the only place `ProjectRestoreSerializer` is reached, and its
    response nests the project under a `topic` key - a copy-paste artefact
    that clients already depend on.
    """

    def setUp(self):
        self.project = Project.objects.create(
            name="Vega",
            description="Reporting",
            is_active=False,
        )
        self.restore_url = f"/api/projects/{self.project.pk}/restore/"

    def test_restore_reactivates_project(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["message"],
            "Project 'Vega' restored successfully",
        )
        self.assertTrue(Project.objects.get(pk=self.project.pk).is_active)

    def test_restore_response_nests_project_under_topic_key(self):
        # Pinned discrepancy: the payload key says "topic" while the body is
        # a project. Renaming it is a breaking change, so it is recorded
        # rather than corrected here.
        self.client.force_authenticate(self.recruiter)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("topic", response.data)
        self.assertTrue(response.data["topic"]["is_active"])
        # ProjectRestoreSerializer is deliberately narrower than
        # ProjectSerializer - `description` must not leak into this response
        self.assertNotIn("description", response.data["topic"])

    def test_restore_of_active_project_returns_400(self):
        self.project.is_active = True
        self.project.save(update_fields=["is_active"])
        self.client.force_authenticate(self.recruiter)
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Project is already active")

    def test_restore_denied_for_anonymous(self):
        response = self.client.post(self.restore_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # A leaked restore would resurrect a project the team retired
        self.assertFalse(Project.objects.get(pk=self.project.pk).is_active)

    def test_restore_of_unknown_pk_returns_404(self):
        self.client.force_authenticate(self.recruiter)
        response = self.client.post("/api/projects/999999/restore/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # A deleted or renamed `restore` action would 404 identically, but
        # as an unrouted path - which renders HTML and carries no `.data`.
        # This assertion is what separates "route exists, object missing"
        # from "route is gone".
        self.assertIn("detail", response.data)


class ProjectListFilterTests(ProjectTestMixin, APITestCase):
    """
    `get_queryset()` hides inactive projects only when `is_active` is absent
    from the query string. Passing it explicitly must hand control back to
    django-filter, otherwise `?is_active=false` would return nothing.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Names must not be substrings of one another: SearchFilter runs
        # icontains, and "Inactive project" would match a search for
        # "Active project" and quietly make the search test meaningless.
        cls.active = Project.objects.create(name="Apollo payments")
        cls.other_active = Project.objects.create(name="Hermes messaging")
        cls.inactive = Project.objects.create(
            name="Retired warehouse",
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

    def test_list_uses_list_serializer_with_absolute_detail_link(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.get(LIST_URL)

        row = next(r for r in response.data["results"] if r["id"] == self.active.pk)
        self.assertEqual(
            row["detail"],
            f"http://testserver/api/projects/{self.active.pk}/",
        )
        # The list serializer must stay narrow - `description` is detail-only
        self.assertNotIn("description", row)

    def test_search_matches_name_fragment(self):
        # Two active projects exist, so a passing search must actually
        # exclude one of them rather than return everything visible.
        self.client.force_authenticate(self.interviewer)
        response = self.client.get(LIST_URL, {"search": "apollo"})

        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [self.active.pk])

    def test_list_ordering_by_name_descending(self):
        self.client.force_authenticate(self.interviewer)
        response = self.client.get(LIST_URL, {"ordering": "-name"})

        names = [row["name"] for row in response.data["results"]]
        # Model Meta orders ascending by name, so a request that is ignored
        # would return the reverse of this
        self.assertEqual(names, ["Hermes messaging", "Apollo payments"])

    def test_list_is_public_for_anonymous(self):
        # Pinned discrepancy, mirror of the retrieve case: the equivalent
        # question endpoint answers 401 here.
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Status alone would pass for an empty page; the anonymous client
        # must actually receive the data
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(self.active.pk, ids)


class ProjectPermissionWiringTests(APITestCase):
    """
    `get_permissions()` never consults `permission_classes`, so the declared
    IsAuthenticated + IsEmployee pair is dead code for every action. These
    tests inspect the returned instances directly, because over HTTP an
    empty permission list and `AllowAny` are indistinguishable - both let
    everything through - while in the source they are different branches.
    """

    def _permission_types(self, action):
        view = ProjectViewSet()
        view.action = action
        return [type(permission) for permission in view.get_permissions()]

    def test_is_authenticated_is_declared_but_never_applied(self):
        # `IsEmployee` is declared too, but unlike IsAuthenticated it does
        # survive - for destroy and restore. Only IsAuthenticated is dead
        # across the board, so the claim is narrowed to it.
        self.assertEqual(
            ProjectViewSet.permission_classes,
            [IsAuthenticated, IsEmployee],
        )
        for action in (
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "restore",
        ):
            self.assertNotIn(IsAuthenticated, self._permission_types(action))

    def test_read_actions_have_no_permission_checks(self):
        for action in ("list", "retrieve"):
            self.assertEqual(self._permission_types(action), [])

    def test_create_and_update_actions_are_open_to_anyone(self):
        for action in ("create", "update", "partial_update"):
            self.assertEqual(self._permission_types(action), [AllowAny])

    def test_destroy_and_restore_require_employee(self):
        for action in ("destroy", "restore"):
            self.assertEqual(self._permission_types(action), [IsEmployee])

    def test_action_set_to_none_falls_through_to_no_permissions(self):
        # DRF leaves `action` as None outside of dispatch; the second half
        # of the guard in `get_permissions()` exists for exactly that case.
        self.assertEqual(self._permission_types(None), [])

    def test_missing_action_attribute_falls_through_to_no_permissions(self):
        # A freshly constructed viewset has no `action` attribute at all -
        # this is the case the `hasattr` half of the guard covers, and the
        # None case above cannot reach it.
        view = ProjectViewSet()
        self.assertFalse(hasattr(view, "action"))
        self.assertEqual([type(p) for p in view.get_permissions()], [])


class ProjectModelTests(TestCase):
    """Plain model behaviour - no HTTP client is involved."""

    def test_str_returns_name(self):
        project = Project.objects.create(name="Lyra")
        self.assertEqual(str(project), "Lyra")
