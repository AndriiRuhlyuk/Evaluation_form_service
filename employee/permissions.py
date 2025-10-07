from rest_framework.permissions import BasePermission


class IsAdminUserOrReadOnly(BasePermission):
    """Only admin can create or change users"""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(request.user and request.user.is_staff)
