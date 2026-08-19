from rest_framework import permissions


class IsManagerOrSuperuser(permissions.BasePermission):
    """
    Permission class that restricts access to users with specific roles.

    This permission allows access only to:
    1. Superusers (users with is_superuser=True) who have full system access
    2. Managers (users with role="MANAGER") who are Heads of Department

    This permission is used to protect administrative actions that should only
    be performed by users with management responsibilities.
    """

    # Custom error message displayed when permission is denied
    message = "You must be a Manager (Head of Department) to perform this action."

    def has_permission(self, request, view):
        """
        Check if the user has permission to perform the requested action.

        Args:
            request: The HTTP request object containing the user
            view: The view that the permission is being checked against

        Returns:
            bool: True if the user is authenticated and is either a superuser or has
                 the MANAGER role, False otherwise
        """
        # First check if user is authenticated and exists
        if not request.user.is_authenticated or not request.user:
            return False

        # Superusers always have permission
        if request.user.is_superuser:
            return True

        # Check if user has the MANAGER role
        return request.user.role == "MANAGER"
