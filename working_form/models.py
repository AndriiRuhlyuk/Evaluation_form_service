from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count, Q
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
        JUNIOR = "junior", "Junior"
        MIDDLE = "middle", "Middle"
        SENIOR = "senior", "Senior"
        LEAD = "lead", "Lead"
        MANAGER = "manager", "Manager"

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
        settings.AUTH_USER_MODEL,
        related_name="interviewers",
        blank=True,
        help_text="The interviewers who will provide interview on the vacancy",
    )
    recruiters = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="recruiter_working_forms",
        blank=True,
        help_text="The recruiter(s) who is responding for hiring process.",
    )
    hiring_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="hiring_manager_working_forms",
        help_text="The hiring manager who is responding for make final decision about hiring.",
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
        settings.AUTH_USER_MODEL,
        related_name="approved_forms",
        blank=True,
        help_text="Users who have actually approved this form.",
    )
    approvers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="forms_to_approve",
        blank=True,
        help_text="Interviewers who approve current version of working form",
    )

    def _calculate_approval(self) -> bool:
        """
        Centralize logic for is_fully_approved.
        Checks if the number of users who approved matches the number of required approvers.
        """

        if "approvers" in self._prefetched_objects_cache:
            approvers_count = len(self.approvers.all())
        else:
            approvers_count = self.approvers.count()

        if "approved_by" in self._prefetched_objects_cache:
            approved_by_count = len(self.approved_by.all())
        else:
            approved_by_count = self.approved_by.count()

        if approvers_count == 0:
            return False

        return approvers_count == approved_by_count

    @property
    def is_fully_approved(self) -> bool:
        return self._calculate_approval()

    def save(self, *args, **kwargs) -> None:
        """
        Updates name and slug automatically if related fields change *on update*.
        Creation logic (name/slug generation) is handled by the
        service layer that calls .create().
        """

        if self.pk:

            project_part = f"({self.project}_{self.pk})" if self.project else ""
            new_name = (
                f"{self.get_level_display()} {self.vacancy} {project_part}".strip()
            )

            if self.name == new_name:

                super().save(*args, **kwargs)
                return

            self.name = new_name
            new_slug = slugify(self.name)

            self.slug = new_slug

        super().save(*args, **kwargs)

    def __str__(self):
        return f"[Working form] {self.level} {self.vacancy}"

    class Meta:
        verbose_name = "Working form"
        verbose_name_plural = "Working forms"


class WorkingFormTopicManager(models.Manager):
    """
    WorkingForm topic custom manager
    return topics with annotations:
        - topic_delete_votes
        - total_approvers_annotated
        - questions_count
        - candidate_for_deletion_count
    DRY:
    for queryset in _get_form_topics_prefetch (list/retrieve/update)
    for queryset in restore_topic (deleted topics list)
    for WorkingFormTopicViewSet get_queryset (list)
    """

    def get_annotated_list(self):

        return self.select_related("topic", "working_form").annotate(
            topic_delete_votes=Count("deleted_by", distinct=True),
            total_approvers_annotated=Count("working_form__approvers", distinct=True),
            questions_count=Count("items", filter=Q(items__is_removed=False)),
            candidate_for_deletion_count=Count(
                "items",
                filter=Q(items__deleted_by__isnull=False) & Q(items__is_removed=False),
            ),
        )


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
        settings.AUTH_USER_MODEL,
        related_name="deleted_working_form_topics",
        blank=True,
        help_text="Voted for deleting the topic by interviewers",
    )
    is_removed = models.BooleanField(
        default=False,
        help_text="Soft delete - form topic removed from working form but kept for history",
    )

    objects = WorkingFormTopicManager()

    def _calculate_effective_deletion(self, total_approvers=None, delete_votes=None):
        """
        Centralize logic for is_effectively_deleted.
        Checks if the topic is effectively deleted based on the number of approvers' votes.
        """

        if total_approvers is None:
            if "approvers" in self.working_form._prefetched_objects_cache:
                total_approvers = len(self.working_form.approvers.all())
            else:
                total_approvers = self.working_form.approvers.count()

        if delete_votes is None:
            if "deleted_by" in self._prefetched_objects_cache:
                delete_votes = len(self.deleted_by.all())
            else:
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


class WorkingFormItemManager(models.Manager):
    """
    WorkingForm topic custom manager
    for take 'full' objects WorkingFormItem.
    """

    def get_annotated_list(self):
        """
        return QuerySet with all annotate and prefetch,
        which needed for serializer and permission-classes.
        """
        return (
            self.select_related("form_topic__working_form")
            .prefetch_related(
                "deleted_by",
                "form_topic__working_form__approvers",
                "form_topic__working_form__approved_by",
            )
            .annotate(
                delete_votes=Count("deleted_by", distinct=True),
                total_approvers=Count(
                    "form_topic__working_form__approvers", distinct=True
                ),
            )
        )


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
        settings.AUTH_USER_MODEL,
        related_name="deleted_items",
        blank=True,
        help_text="Voted for deleting the item by approvers",
    )

    objects = WorkingFormItemManager()

    def _calculate_effective_deletion(
        self, total_approvers=None, delete_votes=None
    ) -> bool:
        """
        Centralize  logic for is_effectively_deleted.
        Checks if the item is effectively deleted based on the number of approvers' votes.
        """

        if total_approvers is None:
            if "approvers" in self.form_topic.working_form._prefetched_objects_cache:
                total_approvers = len(self.form_topic.working_form.approvers.all())
            else:
                total_approvers = self.form_topic.working_form.approvers.count()

        if delete_votes is None:
            if "deleted_by" in self._prefetched_objects_cache:
                delete_votes = len(self.deleted_by.all())
            else:
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
