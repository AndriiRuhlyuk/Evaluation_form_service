from django.db import models


class Topic(models.Model):
    """
    Topic model represents a subject area or category for questions in the evaluation system.

    Topics are used to organize questions into logical groups, making it easier to find
    and manage related questions. Each topic can have multiple questions associated with it.
    Topics can be activated or deactivated as needed.
    """

    name = models.CharField(
        max_length=100, unique=True
    )  # The unique name of the topic (e.g., "Python", "DevOps")
    description = models.TextField(
        blank=True
    )  # Optional detailed description of what the topic covers
    is_active = models.BooleanField(
        default=True
    )  # Flag indicating whether this topic is currently in use
    created_at = models.DateTimeField(
        auto_now_add=True
    )  # Timestamp when the topic was first created
    updated_at = models.DateTimeField(
        auto_now=True
    )  # Timestamp when the topic was last updated

    class Meta:
        verbose_name = "Topic"
        verbose_name_plural = "Topics"
        ordering = ["name"]  # Default ordering by name in alphabetical order

    def __str__(self):
        """
        Returns a string representation of the Topic instance.

        Returns:
            str: The name of the topic
        """
        return self.name
