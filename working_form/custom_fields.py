from django.db import models
from rest_framework import serializers


class M2MListField(serializers.ListField):
    """
    Custom field:
    1. Input (to_internal_value) take list ID [1, 2, 3].
    2. Output (to_representation) transform ManyRelatedManager to list ID [1, 2, 3].
    """

    def __init__(self, *args, **kwargs):
        """
        Override that child is Integer
        """
        kwargs["child"] = serializers.IntegerField(min_value=1)
        super().__init__(*args, **kwargs)

    def to_representation(self, data):
        """
        data: ManyRelatedManager (instance.interviewers)
        return: list of objects pks.
        """

        if isinstance(data, models.Manager):

            return [obj.pk for obj in data.all()]

        return super().to_representation(data)

    def to_internal_value(self, data):
        """
        data: list of ids.
        """
        return super().to_internal_value(data)
