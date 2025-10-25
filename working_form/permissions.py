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
    Permission class, that realized 4 business rules:
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
        is_approver = form.approvers.filter(pk=user.pk).exists()

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

        if form.approved_by.filter(pk=user.pk).exists():
            self.message = "You cannot make changes after you have personally approved the form. Please un-approve it first."
            return False

        return True
