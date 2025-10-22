from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify

from template_form.models import BaseForm, BaseFormItems, TemplateForm
from topic.models import Topic


class WorkingForm(BaseForm):
    """
    WorkingForm for every vacancy. Can be updated by approvers.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        APPROVED = "approved", "Approved"
        EVALUATED = "evaluated", "Evaluated"

    class Level(models.TextChoices):
        JUNIOR = "Junior", "Junior"
        MIDDLE = "Middle", "Middle"
        SENIOR = "Senior", "Senior"
        LEAD = "Lead", "Lead"
        MANAGER = "Manager", "Manager"

    template_origin = models.ForeignKey(
        TemplateForm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="working_forms",
        help_text="The template to use for this working form",
    )
    vacancy = models.CharField(
        max_length=255, help_text="The vacancy name. For example: 'Python Engineer'"
    )
    level = models.CharField(
        max_length=20, choices=Level.choices, help_text="The level of the vacancy"
    )
    project = models.CharField(
        max_length=255,
        blank=True,
        help_text="The project name",
    )
    interviewers = models.ManyToManyField(
        User,
        related_name="interviewers",
        blank=True,
        help_text="The interviewers who will provide interview on the vacancy",
    )
    topics = models.ManyToManyField(
        Topic,
        through="WorkingFormTopic",
        related_name="working_forms",
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
        help_text="The status of the working form",
    )
    approved_by = models.ManyToManyField(
        User,
        related_name="approvable_working_forms",
        blank=True,
        help_text="Users who have actually approved this form.",
    )
    approvers = models.ManyToManyField(
        User,
        related_name="approved_working_forms",
        blank=True,
        help_text="Interviewers who approve current version of working form",
    )

    def _calculate_approval(self, approvers_count=None, approved_by_count=None) -> bool:
        """
        Centralize logic for is_fully_approved.
        Checks if the number of users who approved matches the number of required approvers.
        """

        if approvers_count is None:
            approvers_count = self.approvers.count()
        if approved_by_count is None:
            approved_by_count = self.approved_by.count()

        if approvers_count == 0:
            return False

        return approved_by_count == approvers_count

    @property
    def is_fully_approved(self) -> bool:
        return self._calculate_approval()

    def save(self, *args, **kwargs) -> None:
        """
        Save Working Form Instance with generated name and slug
        """
        if not self.pk:
            project_part = f"({self.project})" if self.project else ""
            self.name = (
                f"{self.get_level_display()} {self.vacancy} {project_part}".strip()
            )
        if not self.slug:
            self.slug = slugify(self.name)

        if WorkingForm.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
            original_slug = self.slug
            counter = 1
            while (
                WorkingForm.objects.filter(slug=self.slug).exclude(pk=self.pk).exists()
            ):
                self.slug = f"{original_slug}-{counter}"
                counter += 1

        super().save(*args, **kwargs)

    def __str__(self):
        return f"[Working form] {self.level} {self.vacancy}"

    class Meta:
        verbose_name = "Working form"
        verbose_name_plural = "Working forms"


class WorkingFormTopic(models.Model):
    """
    WorkingForm Topic for every Working Form.
    Can be deleted (voted) or created by approvers.
    """

    working_form = models.ForeignKey(
        WorkingForm,
        on_delete=models.CASCADE,
        related_name="form_topics",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.PROTECT,
        related_name="working_form_topics",
        null=True,
    )
    deleted_by = models.ManyToManyField(
        User,
        related_name="deleted_working_form_topics",
        blank=True,
        help_text="Voted for deleting the topic by interviewers",
    )
    is_removed = models.BooleanField(
        default=False,
        help_text="Soft delete - form topic removed from working form but kept for history",
    )

    def _calculate_effective_deletion(self, total_approvers=None, delete_votes=None):
        """
        Centralize logic for is_effectively_deleted.
        Checks if the topic is effectively deleted based on the number of approvers' votes.
        """

        if total_approvers is None:
            total_approvers = self.working_form.approvers.count()
        if delete_votes is None:
            delete_votes = self.deleted_by.count()

        if total_approvers == 0:
            return False
        return delete_votes > total_approvers / 2

    @property
    def is_effectively_deleted(self) -> bool:
        return self._calculate_effective_deletion()

    class Meta:
        unique_together = ("working_form", "topic")
        verbose_name = "Topic of working form"
        verbose_name_plural = "Topics of working form"


class WorkingFormItem(BaseFormItems):
    """
    WorkingForm Item for every Working Form Topic.
    Can be deleted (voted) or created by approvers.
    """

    form_topic = models.ForeignKey(
        WorkingFormTopic,
        on_delete=models.CASCADE,
        related_name="items",
    )

    deleted_by = models.ManyToManyField(
        User,
        related_name="deleted_items",
        blank=True,
        help_text="Voted for deleting the item by approvers",
    )

    def _calculate_effective_deletion(self, total_approvers=None, delete_votes=None):
        """
        Centralize  logic for is_effectively_deleted.
        Checks if the item is effectively deleted based on the number of approvers' votes.
        """

        if total_approvers is None:
            total_approvers = self.form_topic.working_form.approvers.count()
        if delete_votes is None:
            delete_votes = self.deleted_by.count()

        if total_approvers == 0:
            return False
        return delete_votes > total_approvers / 2

    @property
    def is_effectively_deleted(self) -> bool:
        return self._calculate_effective_deletion()

    class Meta:
        verbose_name = "Snapshot-item of working form"
        verbose_name_plural = "Snapshot-items of working form"
