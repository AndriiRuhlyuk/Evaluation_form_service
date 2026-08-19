from employee import permissions
from employee.models import Employee


class IsEmployee(permissions.BasePermission):
    """
    Permission class that allows access only to authenticated Employee users.

    This permission is used to restrict access to question management endpoints
    to ensure that only actual employees (not regular users or anonymous users)
    can create, modify, or delete questions in the system.
    """

    def has_permission(self, request, view):
        """
        Check if the user has permission to perform the requested action.

        This method performs two checks:
        1. Verifies that the user is authenticated
        2. Verifies that the user is an instance of the Employee model

        Args:
            request: The HTTP request object
            view: The view that the permission is being checked against

        Returns:
            bool: True if the user is an authenticated Employee, False otherwise
        """
        # First check if user exists and is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Then check if user is an Employee instance
        return isinstance(request.user, Employee)
