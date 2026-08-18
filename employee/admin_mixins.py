import inspect


class ManagerPermissionMixin:
    """
    Permission mixin for Django Admin.
    Implements a role-based permission system for the Django admin interface.

    Key features:
    - Grants full access (add, change, delete, view) to Managers or Superusers.
    - Grants read-only access (view) to any other authenticated user.

    This mixin can be added to any ModelAdmin class to implement these permission rules.
    """

    def _is_manager_or_superuser(self, request):
        """
        Private helper method to check if the user is a manager or superuser.

        Args:
            request: The HTTP request object containing the user

        Returns:
            bool: True if the user is a manager or superuser, False otherwise
        """
        if not request.user.is_authenticated:  # Check if user is authenticated
            return False
        if request.user.is_superuser:  # Check if user is a superuser
            return True
        return (
            getattr(request.user, "role", None) == "MANAGER"
        )  # Check if user has manager role

    def _call_parent_permission(self, method_name, request, obj=None):
        """
        Helper method to call the parent class's permission method with the correct arguments.
        Uses introspection to determine the correct signature for the parent method.

        Args:
            method_name: The name of the permission method to call
            request: The HTTP request object
            obj: The object being checked for permissions (optional)

        Returns:
            bool: Result of the parent permission method
        """
        parent_method = getattr(super(), method_name)  # Get the parent method
        sig = inspect.signature(parent_method)  # Get the method signature

        # Call the parent method with the appropriate arguments based on its signature
        if "obj" in sig.parameters:
            return parent_method(request, obj)
        return parent_method(request)

    def has_view_permission(self, request, obj=None):
        """
        Determines if the user can view the change list or a specific object.
        Allows any authenticated user for safe, read-only access.

        Args:
            request: The HTTP request object
            obj: The object being viewed (optional)

        Returns:
            bool: True if the user can view, False otherwise
        """
        return request.user.is_authenticated  # Any authenticated user can view

    def has_delete_permission(self, request, obj=None):
        """
        Determines if the user can delete objects.
        Only managers and superusers can delete objects.

        Args:
            request: The HTTP request object
            obj: The object being deleted (optional)

        Returns:
            bool: True if the user can delete, False otherwise
        """
        if self._is_manager_or_superuser(request):  # Managers and superusers can delete
            return True
        # Fall back to parent class behavior
        return self._call_parent_permission("has_delete_permission", request, obj)

    def has_change_permission(self, request, obj=None):
        """
        Determines if the user can edit a specific object or access the change form.
        Only managers and superusers can edit objects.

        Args:
            request: The HTTP request object
            obj: The object being edited (optional)

        Returns:
            bool: True if the user can edit, False otherwise
        """
        if self._is_manager_or_superuser(request):  # Managers and superusers can edit
            return True
        # Fall back to parent class behavior
        return self._call_parent_permission("has_change_permission", request, obj)

    def has_add_permission(self, request, obj=None):
        """
        Determines if the user can add new objects in this admin.
        Only managers and superusers can add objects.

        Args:
            request: The HTTP request object
            obj: The parent object if applicable (optional)

        Returns:
            bool: True if the user can add, False otherwise
        """
        if self._is_manager_or_superuser(request):  # Managers and superusers can add
            return True
        # Fall back to parent class behavior
        return self._call_parent_permission("has_add_permission", request, obj)

    def has_module_permission(self, request):
        """
        Controls whether the app/module appears in the admin index.
        Allows any authenticated user to see the module in the admin index.

        Args:
            request: The HTTP request object

        Returns:
            bool: True if the module should be visible, False otherwise
        """
        return (
            request.user.is_authenticated
        )  # Any authenticated user can see the module
