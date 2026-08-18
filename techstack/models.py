from django.db import models


class TechStack(models.Model):
    """
    TechStack Model represents a technology stack used in candidate evaluation forms.

    This model stores information about different technology stacks (like Python, Java, React, etc.)
    that can be associated with working forms and evaluation forms. It allows for organizing
    and categorizing forms based on the required technical skills.
    """

    name = models.CharField(
        max_length=100, unique=True
    )  # The name of the technology stack (e.g., "Python", "React")
    description = models.TextField(
        blank=True, null=True
    )  # Optional detailed description of the technology stack
    is_active = models.BooleanField(
        default=True
    )  # Flag indicating whether this tech stack is currently in use

    class Meta:
        verbose_name = "Tech Stack"
        verbose_name_plural = "Tech Stacks"
        ordering = ["name"]  # Default ordering by name in alphabetical order

    def __str__(self):
        """
        Returns a string representation of the TechStack instance.

        Returns:
            str: The name of the technology stack
        """
        return self.name
