from employee import permissions
from employee.models import Employee


class IsEmployee(permissions.BasePermission):
    """Only employee can create, change and delete questions"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return isinstance(request.user, Employee)
