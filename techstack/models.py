from django.db import models


class TechStack(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Tech Stack"
        verbose_name_plural = "Tech Stacks"
        ordering = ["name"]

    def __str__(self):
        return self.name
