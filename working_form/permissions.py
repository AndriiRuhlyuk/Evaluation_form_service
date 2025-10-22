from rest_framework import permissions
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem


class CanEditForm(permissions.BasePermission):
    """
    Permission to form if:
    - User is admin
    - Working Form hasn't APPROVED status (global blocked)
    - Employee is not in 'approved_by' (individual blocked)
    """

    message = "You cannot edit a form you have already approved, or that is globally approved."

    def get_form_object(self, obj):
        """Function-helper for getting form object."""

        if isinstance(obj, WorkingForm):
            return obj
        if isinstance(obj, WorkingFormTopic):
            return obj.working_form
        if isinstance(obj, WorkingFormItem):
            return obj.form_topic.working_form
        return None

    def has_object_permission(self, request, view, obj):
        """
        - admin always has permission
        - global block
        - individual block (no in M2M list 'approved_by'
        """

        if request.user.is_staff:
            return True

        form = self.get_form_object(obj)
        if not form:
            return False

        if form.status == WorkingForm.Status.APPROVED:
            self.message = "Cannot edit. Form is globally approved."
            return False

        if form.approved_by.filter(pk=request.user.pk).exists():
            self.message = "You cannot edit a form you have already approved. Press 'Unapprove' first."
            return False

        return True
