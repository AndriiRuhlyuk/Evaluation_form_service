from employee import permissions
from employee.models import Employee


class IsEmployee(permissions.BasePermission):
    """
    Permission class that restricts access to employees only.

    This permission ensures that only authenticated users with Employee model instances
    can create, change, and delete projects. It's used to protect project management
    endpoints from unauthorized access.
    """

    def has_permission(self, request, view):
        """
        Check if the request user has permission to perform the requested action.

        Args:
            request: The HTTP request object containing user information
            view: The view that the permission is being checked against

        Returns:
            bool: True if user is authenticated and is an Employee, False otherwise
        """
        # Check if user exists and is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        # Check if the authenticated user is an Employee instance
        return isinstance(request.user, Employee)
