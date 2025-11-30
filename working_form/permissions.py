from rest_framework import permissions
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem


def _get_form_from_obj(obj) -> WorkingForm | None:
    """Function-helper, to get WorkingForm from any object."""
    if isinstance(obj, WorkingForm):
        return obj
    if isinstance(obj, WorkingFormTopic):
        return obj.working_form
    if isinstance(obj, WorkingFormItem):
        return obj.form_topic.working_form
    return None


class CanInteractWithWorkingForm(permissions.BasePermission):
    """
    Permission class, that realized 3 business rules:
    1. [Regular] User - approver OR  superuser
    2. [On default] Form Status is NOT 'Approved'.
    3. [On default] User NOT approves form.

    For action 'unapprove', rules 2 і 3 is skipped.
    For action 'approve', rule 3 is skipped (another logic).
    """

    message = "You do not have permission to perform this action."

    def has_object_permission(self, request, view, obj):
        form = _get_form_from_obj(obj)
        if not form:
            return False

        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        is_superuser = user.is_superuser
        approver_ids = {u.pk for u in form.approvers.all()}
        is_approver = user.pk in approver_ids

        if not (is_approver or is_superuser):
            self.message = (
                "You must be an Approver or Recruiter to perform this action."
            )
            return False

        if view.action == "unapprove":
            return True

        if form.status == WorkingForm.Status.APPROVED:
            self.message = "Changes are not allowed for an approved form. Please un-approve it first."
            return False

        if view.action == "approve":
            return True

        approved_by_ids = {u.pk for u in form.approved_by.all()}
        is_personally_approved = user.pk in approved_by_ids

        if is_personally_approved:
            self.message = "You cannot make changes after you have personally approved the form. Please un-approve it first."
            return False

        return True


class CanEditWorkingForm(permissions.BasePermission):
    """
    Permission class, that realized 2 business rules:
    1. User - Superuser OR (has role 'RECRUITER' AND is in  'recruiters')
    2. STATUS WorkingForm NOT 'Approved'.
    """

    message = "You do not have permission to perform this action."

    def has_object_permission(self, request, view, obj):
        form = _get_form_from_obj(obj)
        if not form:
            return False

        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        is_superuser = user.is_superuser

        is_assigned_recruiter = False
        if user.role == "RECRUITER":
            if "recruiters" in form._prefetched_objects_cache:
                recruiter_ids = {r.pk for r in form.recruiters.all()}
                is_assigned_recruiter = user.pk in recruiter_ids
            else:
                is_assigned_recruiter = form.recruiters.filter(pk=user.pk).exists()

        if not (is_assigned_recruiter or is_superuser):
            self.message = (
                "You must be an assigned Recruiter or a Superuser to edit this form."
            )
            return False

        if form.status == WorkingForm.Status.APPROVED:
            self.message = "Changes are not allowed for an approved form. Please un-approve it first."
            return False

        return True


class IsRecruiter(permissions.BasePermission):
    """
    Grants permission only to users with the 'RECRUITER' role
    or to superusers.
    """

    message = "You must be a Recruiter to perform this action."

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        return request.user.role == "RECRUITER"


class CanCreateEvaluationForm(permissions.BasePermission):
    """
    Permission to create EvaluationForm, if:
    1. User: Superuser or ('RECRUITER' and in 'recruiters')
    2. Status WorkingForm - 'APPROVED'.
    """

    message = "Action not allowed."

    def has_object_permission(self, request, view, obj):
        form = _get_form_from_obj(obj)
        if not form:
            return False

        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        is_superuser = user.is_superuser
        is_assigned_recruiter = False

        if user.role == "RECRUITER":
            if "recruiters" in form._prefetched_objects_cache:
                recruiter_ids = {r.pk for r in form.recruiters.all()}
                is_assigned_recruiter = user.pk in recruiter_ids
            else:
                is_assigned_recruiter = form.recruiters.filter(pk=user.pk).exists()

        if not (is_assigned_recruiter or is_superuser):
            self.message = "You must be an assigned Recruiter or a Superuser to create an evaluation."
            return False

        if form.status != WorkingForm.Status.APPROVED:
            self.message = "An Evaluation Form can only be created from an 'Approved' Working Form."
            return False

        return True
