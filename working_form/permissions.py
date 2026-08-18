from rest_framework import permissions
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem


def _get_form_from_obj(obj) -> WorkingForm | None:
    """
    Helper function to extract the WorkingForm instance from various object types.

    This utility function handles the different relationships between WorkingForm
    and its related models, allowing permission classes to work with any object
    type that is associated with a WorkingForm.

    Args:
        obj: The object to extract the WorkingForm from (can be WorkingForm,
             WorkingFormTopic, or WorkingFormItem)

    Returns:
        WorkingForm: The associated WorkingForm instance, or None if not found
    """
    # If the object is already a WorkingForm, return it directly
    if isinstance(obj, WorkingForm):
        return obj
    # If the object is a WorkingFormTopic, get its parent WorkingForm
    if isinstance(obj, WorkingFormTopic):
        return obj.working_form
    # If the object is a WorkingFormItem, navigate through its topic to get the WorkingForm
    if isinstance(obj, WorkingFormItem):
        return obj.form_topic.working_form
    # If the object is not related to a WorkingForm, return None
    return None


class CanInteractWithWorkingForm(permissions.BasePermission):
    """
    Permission class that enforces business rules for working form interaction.

    This permission implements three core business rules:
    1. The user must be either an approver for this form or a superuser
    2. By default, the form's status must not be 'Approved'
    3. By default, the user must not have personally approved the form

    Special cases:
    - For the 'unapprove' action, rules 2 and 3 are skipped (allowing approved forms to be unapproved)
    - For the 'approve' action, rule 3 is skipped (allowing users to approve even if they've already approved)

    This permission ensures that only authorized users can interact with forms,
    and that approved forms are protected from changes unless explicitly unapproved.
    """

    message = "You do not have permission to perform this action."

    def has_object_permission(self, request, view, obj):
        """
        Check if the user has permission to interact with the given object.

        This method implements the business rules described in the class docstring,
        with appropriate error messages for each failure case.

        Args:
            request: The HTTP request
            view: The view being accessed
            obj: The object being accessed (WorkingForm, WorkingFormTopic, or WorkingFormItem)

        Returns:
            bool: True if permission is granted, False otherwise
        """
        # Get the associated WorkingForm instance
        form = _get_form_from_obj(obj)
        if not form:
            return False

        # Check if user is authenticated
        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        # Check if user is a superuser or an approver for this form
        is_superuser = user.is_superuser  # User has admin privileges
        approver_ids = {u.pk for u in form.approvers.all()}  # Set of all approver IDs
        is_approver = user.pk in approver_ids  # Whether this user is an approver

        # Rule 1: User must be an approver or superuser
        if not (is_approver or is_superuser):
            self.message = (
                "You must be an Approver or Recruiter to perform this action."
            )
            return False

        # Special case: 'unapprove' action skips remaining checks
        if view.action == "unapprove":
            return True

        # Rule 2: Form must not be approved (unless special case)
        if form.status == WorkingForm.Status.APPROVED:
            self.message = "Changes are not allowed for an approved form. Please un-approve it first."
            return False

        # Special case: 'approve' action skips the personal approval check
        if view.action == "approve":
            return True

        # Rule 3: User must not have personally approved the form
        approved_by_ids = {
            u.pk for u in form.approved_by.all()
        }  # Set of users who approved
        is_personally_approved = (
            user.pk in approved_by_ids
        )  # Whether this user approved

        if is_personally_approved:
            self.message = "You cannot make changes after you have personally approved the form. Please un-approve it first."
            return False

        # All checks passed
        return True


class CanEditWorkingForm(permissions.BasePermission):
    """
    Permission class that enforces business rules for editing working forms.

    This permission implements two core business rules:
    1. The user must be either a superuser OR a recruiter who is assigned to this form
    2. The form's status must not be 'Approved'

    This permission is more restrictive than CanInteractWithWorkingForm, as it
    limits editing capabilities to recruiters and superusers, while interaction
    permissions are granted to approvers as well.
    """

    message = "You do not have permission to perform this action."

    def has_object_permission(self, request, view, obj):
        """
        Check if the user has permission to edit the given object.

        This method implements the business rules described in the class docstring,
        with appropriate error messages for each failure case.

        Args:
            request: The HTTP request
            view: The view being accessed
            obj: The object being edited (WorkingForm, WorkingFormTopic, or WorkingFormItem)

        Returns:
            bool: True if permission is granted, False otherwise
        """
        # Get the associated WorkingForm instance
        form = _get_form_from_obj(obj)
        if not form:
            return False

        # Check if user is authenticated
        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        # Check if user is a superuser
        is_superuser = user.is_superuser  # User has admin privileges

        # Check if user is an assigned recruiter for this form
        is_assigned_recruiter = False
        if user.role == "RECRUITER":
            # Optimize by using prefetch cache if available
            cache = getattr(form, "_prefetched_objects_cache", None)
            if cache is not None and "recruiters" in cache:
                # If recruiters are prefetched, check in memory
                is_assigned_recruiter = user.pk in {r.pk for r in form.recruiters.all()}
            else:
                # Otherwise, query the database
                is_assigned_recruiter = form.recruiters.filter(pk=user.pk).exists()

        # Rule 1: User must be an assigned recruiter or superuser
        if not (is_assigned_recruiter or is_superuser):
            self.message = (
                "You must be an assigned Recruiter or a Superuser to edit this form."
            )
            return False

        # Rule 2: Form must not be approved
        if form.status == WorkingForm.Status.APPROVED:
            self.message = "Changes are not allowed for an approved form. Please un-approve it first."
            return False

        # All checks passed
        return True


class IsRecruiter(permissions.BasePermission):
    """
    Permission class that restricts access to recruiters and superusers.

    This permission is used for views that should only be accessible to users
    with the 'RECRUITER' role or to superusers. Unlike the other permission
    classes, this one checks general permission rather than object-specific
    permission.
    """

    message = "You must be a Recruiter to perform this action."

    def has_permission(self, request, view):
        """
        Check if the user has the RECRUITER role or is a superuser.

        This method implements a simple role check without considering
        specific objects.

        Args:
            request: The HTTP request
            view: The view being accessed

        Returns:
            bool: True if permission is granted, False otherwise
        """
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusers always have permission
        if request.user.is_superuser:
            return True

        # Otherwise, check if user has the RECRUITER role
        return request.user.role == "RECRUITER"


class CanCreateEvaluationForm(permissions.BasePermission):
    """
    Permission class for creating evaluation forms from working forms.

    This permission implements two core business rules:
    1. The user must be either a superuser OR a recruiter who is assigned to this form
    2. The working form's status must be 'APPROVED'

    This permission ensures that evaluation forms can only be created from
    approved working forms, and only by authorized recruiters or superusers.
    """

    message = "Action not allowed."

    def has_object_permission(self, request, view, obj):
        """
        Check if the user has permission to create an evaluation form from this object.

        This method implements the business rules described in the class docstring,
        with appropriate error messages for each failure case.

        Args:
            request: The HTTP request
            view: The view being accessed
            obj: The working form object to create an evaluation from

        Returns:
            bool: True if permission is granted, False otherwise
        """
        # Get the associated WorkingForm instance
        form = _get_form_from_obj(obj)
        if not form:
            return False

        # Check if user is authenticated
        user = request.user
        if not user or user.is_anonymous:
            self.message = "Authentication required."
            return False

        # Check if user is a superuser
        is_superuser = user.is_superuser  # User has admin privileges

        # Check if user is an assigned recruiter for this form
        is_assigned_recruiter = False
        if user.role == "RECRUITER":
            # Optimize by using prefetch cache if available
            cache = getattr(form, "_prefetched_objects_cache", None)
            if cache is not None and "recruiters" in cache:
                # If recruiters are prefetched, check in memory
                is_assigned_recruiter = user.pk in {r.pk for r in form.recruiters.all()}
            else:
                # Otherwise, query the database
                is_assigned_recruiter = form.recruiters.filter(pk=user.pk).exists()

        # Rule 1: User must be an assigned recruiter or superuser
        if not (is_assigned_recruiter or is_superuser):
            self.message = "You must be an assigned Recruiter or a Superuser to create an evaluation."
            return False

        # Rule 2: Form must be approved
        if form.status != WorkingForm.Status.APPROVED:
            self.message = "An Evaluation Form can only be created from an 'Approved' Working Form."
            return False

        # All checks passed
        return True
