from django.db import models


class Project(models.Model):
    """
    Project Model represents a project entity in the evaluation form system.

    This model stores information about projects that candidates can be evaluated against.
    Projects can be active or inactive, allowing for soft deletion functionality.
    """

    # Name of the project, must be unique
    name = models.CharField(max_length=100, unique=True)
    # Optional description providing details about the project
    description = models.TextField(blank=True, null=True)
    # Flag indicating whether the project is active (True) or soft-deleted (False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ["name"]  # Default ordering by project name

    def __str__(self):
        """
        Returns a string representation of the project.

        Returns:
            str: The name of the project
        """
        return self.name
