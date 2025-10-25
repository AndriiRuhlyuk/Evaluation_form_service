from django.conf import settings
from django.db import models

from techstack.models import TechStack
from django.utils.text import slugify
from topic.models import Topic


class BaseForm(models.Model):
    """Base abstract model for all forms"""

    name = models.CharField(max_length=500)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_forms",
    )
    tech_stack = models.ForeignKey(
        TechStack, on_delete=models.PROTECT, related_name="%(class)s_forms"
    )
    topics = models.ManyToManyField(
        Topic, through="FormTopic", related_name="%(class)s_forms", blank=True
    )
    slug = models.SlugField(max_length=500, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """
        Generate Slug (name field) before saving
        """
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TemplateForm(BaseForm):
    """Model for Template Form"""

    def __str__(self):
        return self.name


class BaseFormItems(models.Model):
    """Base abstract model for all forms items"""

    class Difficulty(models.IntegerChoices):
        EASY = 1, "Easy"
        MEDIUM = 2, "Medium"
        HARD = 3, "Hard"

    text_snapshot = models.TextField(blank=True, null=True)
    difficulty_snapshot = models.IntegerField(
        choices=Difficulty.choices, blank=True, null=True
    )
    source_snapshot = models.CharField(max_length=25, blank=True, null=True)
    topic_snapshot = models.CharField(max_length=125, blank=True, null=True)
    max_score_snapshot = models.IntegerField(blank=True, null=True)

    origin_question = models.ForeignKey(
        "question.Question",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Link to the original question. Null for custom questions",
    )
    is_removed = models.BooleanField(
        default=False,
        help_text="Soft delete - question removed from form but kept for history",
    )

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_added_items",
        help_text="Who added this question to THIS form",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="When this question was added to THIS form"
    )

    class Meta:
        abstract = True
        ordering = (
            "difficulty_snapshot",
            "topic_snapshot",
        )


class FormTopic(models.Model):
    """Through-model for M2M"""

    form = models.ForeignKey(
        TemplateForm, on_delete=models.CASCADE, related_name="form_topics"
    )
    topic = models.ForeignKey(
        Topic, on_delete=models.CASCADE, related_name="form_topics"
    )

    class Meta:
        unique_together = ("form", "topic")

    def __str__(self):
        return f"{self.form.name} - {self.topic.name}"


class TemplateFormItems(BaseFormItems):
    """Model for Template Form Item"""

    form_topic = models.ForeignKey(
        FormTopic,
        on_delete=models.CASCADE,
        related_name="items",
    )

    @property
    def form(self):
        return self.form_topic.form

    class Meta:
        verbose_name_plural = "Template Form Items"

    def save(self, *args, **kwargs):
        """
        Recalculate max_score_snapshot before saving if difficulty_snapshot is set.
        """

        if self.form_topic and self.form_topic.topic:
            self.topic_snapshot = self.form_topic.topic.name

        if self.origin_question:

            self.source_snapshot = self.origin_question.source
            if not self.text_snapshot:
                self.text_snapshot = self.origin_question.question_text

            if self.difficulty_snapshot is None:
                self.difficulty_snapshot = self.origin_question.difficulty

        if self.difficulty_snapshot:

            self.max_score_snapshot = self.difficulty_snapshot * 3
        else:

            self.max_score_snapshot = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.form_topic.topic.name}] {self.text_snapshot[:60]}..."


class ReadOnlyTemplateForm(TemplateForm):
    class Meta:
        proxy = True
        verbose_name = "Template Form (Read-Only)"
        verbose_name_plural = "Template Forms (Read-Only)"


class ReadOnlyFormTopic(FormTopic):
    class Meta:
        proxy = True
        verbose_name = "Form Topic (Read-Only)"
        verbose_name_plural = "Form Topics (Read-Only)"
