from django.db import models
from django.contrib.auth.models import User

from techstack.models import TechStack
from django.utils.text import slugify
from topic.models import Topic


class BaseForm(models.Model):
    """Base abstract model for all forms"""

    name = models.CharField(max_length=500)
    manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="forms"
    )
    tech_stack = models.ForeignKey(
        TechStack, on_delete=models.PROTECT, related_name="forms"
    )
    topics = models.ManyToManyField(Topic, related_name="template_forms", blank=True)
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

    text_snapshot = models.TextField()
    difficulty_snapshot = models.IntegerField()
    source_snapshot = models.CharField(max_length=25)
    topic_snapshot = models.CharField(max_length=125)
    max_score_snapshot = models.IntegerField()

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
        User,
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


class TemplateFormItems(BaseFormItems):
    """Model for Template Form Item"""

    form = models.ForeignKey(
        TemplateForm, on_delete=models.CASCADE, related_name="items"
    )

    def __str__(self):
        return f"[{self.form.name}] {self.text_snapshot[:60]}..."
