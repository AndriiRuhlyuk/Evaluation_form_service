from rest_framework import permissions


class IsManagerOrSuperuser(permissions.BasePermission):
    """
    Permission, for users:
    1. 'Is_superuser'.
    OR
    2. 'MANAGER' (Head of Department).
    """

    message = "You must be a Manager (Head of Department) to perform this action."

    def has_permission(self, request, view):

        if not request.user.is_authenticated or not request.user:
            return False

        if request.user.is_superuser:
            return True

        return request.user.role == "MANAGER"
