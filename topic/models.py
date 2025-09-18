from django.db import models


class Topic(models.Model):
    """Topic model"""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Topic"
        verbose_name_plural = "Topics"
        ordering = ["name"]

    def __str__(self):
        return self.name
