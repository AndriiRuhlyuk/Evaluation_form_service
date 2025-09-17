from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from techstack.models import TechStack
from techstack.serializers import TechStackSerializer, TechStackListSerializer


class TechStackViewSet(viewsets.ModelViewSet):
    queryset = TechStack.objects.filter(is_active=True)
    serializer_class = TechStackSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active"]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]

    def get_serializer_class(self):
        if self.action == "list":
            return TechStackListSerializer
        return TechStackSerializer
