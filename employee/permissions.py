from rest_framework.permissions import BasePermission


class IsAdminUserOrReadOnly(BasePermission):
    """
    Permission class that allows read-only access to all users but restricts write operations to admin users.

    This permission is useful for API endpoints where you want to allow anyone to view data,
    but only administrators should be able to create, update, or delete data.
    """

    def has_permission(self, request, view):
        """
        Determine if the user has permission to perform the requested action.

        Args:
            request: The HTTP request object
            view: The view that the permission is being checked against

        Returns:
            bool: True if the user has permission, False otherwise

        Logic:
            - Allow GET, HEAD, and OPTIONS requests for all users (read-only operations)
            - For other methods (POST, PUT, PATCH, DELETE), only allow if user is staff
        """
        if request.method in ("GET", "HEAD", "OPTIONS"):  # Safe methods (read-only)
            return True
        return bool(
            request.user and request.user.is_staff
        )  # Check if user is staff for write operations
