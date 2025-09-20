from django.db import models
from django.contrib.auth.models import User

from topic.models import Topic


class Question(models.Model):

    class QuestionDifficulty(models.IntegerChoices):
        EASY = 1, "Easy"
        MEDIUM = 2, "Medium"
        HARD = 3, "Hard"

    class QuestionSource(models.TextChoices):
        TEMPLATE = "template", "Template"
        MANUAL = "manual", "Interviewer"
        GENERATED = "generated", "Added by AI"

    question_text = models.TextField()
    difficulty = models.IntegerField(
        choices=QuestionDifficulty.choices,
        default=QuestionDifficulty.EASY,
    )
    source = models.TextField(
        choices=QuestionSource.choices,
        default=QuestionSource.TEMPLATE,
    )
    is_active = models.BooleanField(default=True)
    topic = models.ForeignKey(
        Topic,
        on_delete=models.PROTECT,
        related_name="questions",
    )
    question_author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="questions",
        null=True,
        blank=True,
    )
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Question"
        verbose_name_plural = "Questions"
        ordering = ("topic", "-usage_count", "created_at")

    @property
    def max_score(self):
        """Max score for question."""
        return self.difficulty * 3

    def increment_usage(self):
        """Increase question usage."""
        self.usage_count += 1
        self.save(update_fields=["usage_count"])
