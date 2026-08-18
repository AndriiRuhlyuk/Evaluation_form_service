from django.db import models
from rest_framework import serializers


class M2MListField(serializers.ListField):
    """
    Custom field for handling Many-to-Many relationships in Django REST Framework.

    This field simplifies the serialization and deserialization of Many-to-Many relationships
    by converting between Django's ManyRelatedManager objects and simple lists of IDs.

    Business Logic:
    - When deserializing (input), it accepts a list of IDs [1, 2, 3] and validates them as integers.
    - When serializing (output), it transforms a ManyRelatedManager object into a list of primary keys [1, 2, 3].

    This is particularly useful for API endpoints that need to handle M2M relationships in a simple format.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the M2MListField with an IntegerField as its child.

        This constructor ensures that all items in the list are validated as integers
        with a minimum value of 1, which is appropriate for database primary keys.

        Args:
            *args: Variable length argument list passed to the parent class.
            **kwargs: Arbitrary keyword arguments passed to the parent class.
        """
        # Set the child serializer to IntegerField with minimum value of 1 to ensure valid IDs
        kwargs["child"] = serializers.IntegerField(min_value=1)
        super().__init__(*args, **kwargs)

    def to_representation(self, data):
        """
        Convert a Django ManyRelatedManager object to a list of primary keys.

        This method is called during serialization to transform the database objects
        into a format suitable for API responses.

        Args:
            data: A ManyRelatedManager instance (e.g., instance.interviewers) or other data.

        Returns:
            A list of primary keys (integers) representing the related objects.
        """
        # Check if the data is a Django Manager (which ManyRelatedManager is)
        if isinstance(data, models.Manager):
            # Extract the primary key from each related object
            return [obj.pk for obj in data.all()]

        # If not a Manager, use the parent class's implementation
        return super().to_representation(data)

    def to_internal_value(self, data):
        """
        Process the incoming data during deserialization.

        This method validates that the input is a list of valid integers
        that can be used as primary keys for the related model.

        Args:
            data: A list of IDs (integers) representing the related objects.

        Returns:
            The validated list of IDs.
        """
        # Use the parent class's implementation to validate the list of IDs
        return super().to_internal_value(data)
