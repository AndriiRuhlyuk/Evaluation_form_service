from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from .models import Employee
from .serializers import EmployeeSerializer, LogoutSerializer
from employee.permissions import IsAdminUserOrReadOnly


class CreateEmployeeView(generics.CreateAPIView):
    """
    API view for creating new employee accounts.

    Only administrators can create new employee accounts.
    Uses JWT authentication and the IsAdminUserOrReadOnly permission.
    """

    serializer_class = EmployeeSerializer  # Serializer for Employee model
    queryset = Employee.objects.all()  # All employees
    permission_classes = (IsAdminUserOrReadOnly,)  # Only admins can create
    authentication_classes = (JWTAuthentication,)  # JWT token authentication


class ManageEmployeeView(generics.RetrieveUpdateAPIView):
    """
    API view for retrieving and updating the currently authenticated employee's profile.

    Allows employees to view and update their own profile information.
    Uses JWT authentication and requires the user to be authenticated.
    """

    serializer_class = EmployeeSerializer  # Serializer for Employee model
    permission_classes = [IsAuthenticated]  # User must be authenticated
    authentication_classes = (JWTAuthentication,)  # JWT token authentication

    def get_object(self):
        """
        Returns the currently authenticated user as the object to be retrieved or updated.

        This ensures users can only manage their own profiles.

        Returns:
            Employee: The currently authenticated user
        """
        return self.request.user  # Return the current user


class EmployeeListView(generics.ListAPIView):
    """
    API view for listing all employees.

    Only administrators can access this view to see all employee accounts.
    Uses JWT authentication and requires admin privileges.
    """

    serializer_class = EmployeeSerializer  # Serializer for Employee model
    queryset = Employee.objects.all()  # All employees
    permission_classes = [IsAdminUser]  # Only admins can access
    authentication_classes = (JWTAuthentication,)  # JWT token authentication


class LogoutEmployeeView(generics.GenericAPIView):
    """
    API view for logging out employees by blacklisting their JWT tokens.

    Logs out the employee by blacklisting the provided refresh token.
    If 'all_tokens' is true, blacklists all refresh tokens for the user,
    effectively logging them out from all devices.

    Requires authentication via JWT.
    """

    authentication_classes = (JWTAuthentication,)  # JWT token authentication
    permission_classes = (IsAuthenticated,)  # User must be authenticated
    serializer_class = LogoutSerializer  # Serializer for logout data

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for logging out.

        Blacklists the provided refresh token or all tokens for the user.

        Args:
            request: The HTTP request object
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments

        Returns:
            Response: HTTP response with success or error message
        """
        # Validate the request data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get validated data
        refresh = serializer.validated_data["refresh"]  # The refresh token to blacklist
        all_tokens = serializer.validated_data[
            "all_tokens"
        ]  # Whether to blacklist all tokens

        if all_tokens:
            # Get all tokens for the current user
            tokens = OutstandingToken.objects.filter(user=self.request.user)
            if not tokens.exists():
                # No tokens found for this user
                return Response(
                    {"detail": "No active tokens found for this user"},
                    status=status.HTTP_204_NO_CONTENT,
                )
            # Blacklist all tokens
            for token in tokens:
                try:
                    RefreshToken(token.token).blacklist()
                except TokenError:
                    pass  # Skip tokens that can't be blacklisted
        else:
            # Blacklist only the provided refresh token
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                # Token couldn't be blacklisted
                return Response(
                    {"detail": "Failed to blacklist refresh token"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Return success response
        return Response(
            {"detail": "Successfully logged out"}, status=status.HTTP_204_NO_CONTENT
        )
