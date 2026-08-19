from employee import permissions
from employee.models import Employee


class IsEmployee(permissions.BasePermission):
    """
    Permission class that restricts access to employees only.

    This permission ensures that only authenticated users with an Employee model instance
    can create, update, and delete topics. This is a security measure to prevent
    unauthorized users from modifying the topic data that is used in evaluation forms.
    """

    def has_permission(self, request, view):
        """
        Check if the user has permission to perform the requested action.

        Args:
            request: The HTTP request object containing user information
            view: The view that the permission is being checked against

        Returns:
            bool: True if the user is authenticated and is an Employee, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            # Reject unauthenticated users
            return False
        # Check if the user is an instance of Employee model
        return isinstance(request.user, Employee)
