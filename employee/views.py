from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Employee
from .serializers import EmployeeSerializer
from .permissions import IsAdminUserOrReadOnly


class CreateEmployeeView(generics.CreateAPIView):
    """Create user - only admin"""

    serializer_class = EmployeeSerializer
    queryset = Employee.objects.all()
    permission_classes = (IsAdminUserOrReadOnly,)
    authentication_classes = (JWTAuthentication,)


class ManageEmployeeView(generics.RetrieveUpdateAPIView):

    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = (JWTAuthentication,)

    def get_object(self):
        return self.request.user


class EmployeeListView(generics.ListAPIView):

    serializer_class = EmployeeSerializer
    queryset = Employee.objects.all()
    permission_classes = [IsAdminUser]
    authentication_classes = (JWTAuthentication,)
