from django.conf import settings
from django.db import models, IntegrityError
from django.db.models import Count, Q

from template_form.models import BaseForm, BaseFormItems, TemplateForm
from topic.models import Topic
from working_form.utils import prefetch_count, EffectiveDeletionMixin


class WorkingForm(BaseForm):
    """
    A working form model for a specific vacancy.

    This model represents a "live" version of a form that can be updated
    and approved by responsible users (approvers). It is created based on
    `TemplateForm` and contains all the necessary information for conducting
    an interview: vacancy title, level, project, a list of interviewers,
    recruiters, as well as topics and questions for discussion.

    The WorkingForm serves as the central entity for managing interview templates
    before they are used for actual candidate evaluations. It goes through an approval
    workflow where designated approvers must review and approve the form before it
    can be used for interviews.
    """

    class Status(models.TextChoices):
        """
        Working form status choices.

        Defines the possible states of a working form in its lifecycle:
        - IN_PROGRESS: Form is being edited and awaiting approval
        - APPROVED: Form has been reviewed and approved by all required approvers
        """

        IN_PROGRESS = (
            "in_progress",
            "In Progress",
        )  # Form is being edited and awaiting approval
        APPROVED = "approved", "Approved"  # Form has been approved and ready for use

    class Level(models.TextChoices):
        """
        Vacancy level choices.

        Defines the seniority levels for the vacancy this form is associated with.
        Used for categorizing forms and determining the appropriate difficulty level
        of questions.
        """

        JUNIOR = "junior", "Junior"  # Entry-level position
        MIDDLE = "middle", "Middle"  # Mid-level position
        SENIOR = "senior", "Senior"  # Senior-level position
        LEAD = "lead", "Lead"  # Team lead position
        MANAGER = "manager", "Manager"  # Management position

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
    project = models.ForeignKey(
        "project.Project",
        on_delete=models.PROTECT,
        related_name="working_forms",
        help_text="The project for this working form",
    )
    interviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="interviewer_working_forms",
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
        blank=True,
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
        db_index=True,
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
    # is_deleted / deleted_at / deleted_by and both managers (objects filtered,
    # all_objects unfiltered) are inherited from BaseForm

    def _calculate_approval(self) -> bool:
        """
        Checks whether the form has been fully approved.

        Compares the number of users who have approved the form with the total
        number of required approvers. Uses cached data, if available, to avoid
        unnecessary database queries.

        Returns:
            bool: True if the number of approvals equals the number of approvers
                  (and the number of approvers is greater than 0), otherwise False.
        """

        approvers_count = prefetch_count(
            self, "approvers"
        )  # Total number of required approvers
        approved_by_count = prefetch_count(
            self, "approved_by"
        )  # Number of users who have approved

        if approvers_count == 0:
            return False  # Can't be approved if there are no approvers

        return (
            approvers_count == approved_by_count
        )  # Fully approved when all approvers have approved

    @property
    def is_fully_approved(self) -> bool:
        """
        A property indicating whether the form is fully approved.

        This is a convenience property that delegates to _calculate_approval().

        Returns:
            bool: True if all required approvers have approved the form, False otherwise.
        """
        return self._calculate_approval()

    @staticmethod
    def _build_base_name(level, vacancy, project, created_date):
        """
        Helper method to create the base part of the form name.

        Constructs a standardized name format for working forms based on their attributes.

        Args:
            level (str): The seniority level of the vacancy
            vacancy (str): The name of the vacancy
            project (str): The project name
            created_date (datetime): The creation date of the form

        Returns:
            str: The base name string without sequence number
        """

        level_display = dict(WorkingForm.Level.choices).get(
            level, level.capitalize()
        )  # Get human-readable level
        date_str = created_date.strftime("%d.%m.%Y")  # Format date as DD.MM.YYYY
        return f"Working form: {level_display} {vacancy} ({project}) {date_str}"

    @staticmethod
    def build_name(level, vacancy, project, created_date, sequence_number):
        """
        Creates the full form name with a sequence number.

        Args:
            level (str): The seniority level of the vacancy
            vacancy (str): The name of the vacancy
            project (str): The project name
            created_date (datetime): The creation date of the form
            sequence_number (int): The sequence number to append to the name

        Returns:
            str: The complete form name with sequence number
        """

        base = WorkingForm._build_base_name(
            level, vacancy, project, created_date
        )  # Get base name
        return f"{base} #{sequence_number}"  # Append sequence number

    @staticmethod
    def next_sequence_number(level, vacancy, project, created_date, exclude_pk=None):
        """
        Calculates the next sequence number for a form with the same attributes.

        This is necessary for name uniqueness, e.g., '... #1', '... #2'.
        Counts existing forms with the same base name and returns the next available number.

        Args:
            level (str): The seniority level of the vacancy
            vacancy (str): The name of the vacancy
            project (str): The project name
            created_date (datetime): The creation date of the form
            exclude_pk (int, optional): Primary key to exclude from the count (for updates)

        Returns:
            int: The next available sequence number
        """

        base_name = WorkingForm._build_base_name(level, vacancy, project, created_date)
        qs = WorkingForm.all_objects.filter(name__startswith=base_name)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs.count() + 1

    @classmethod
    def generate_name_and_slug(
        cls, level, vacancy, project, created_date, exclude_pk=None
    ):
        """
        Generates a unique name and slug for a new WorkingForm instance.

        This method is used when creating a new WorkingForm to ensure that
        the name and slug are unique based on the provided attributes.

        Args:
            level (str): The seniority level of the vacancy
            vacancy (str): The name of the vacancy
            project (object): The project object
            created_date (datetime): The creation date of the form
            exclude_pk (int, optional): Primary key to exclude from uniqueness check

        Returns:
            tuple: A tuple containing (name, slug) for the form
        """

        project_display = str(project)  # Convert project object to string for display
        seq = cls.next_sequence_number(
            level, vacancy, project_display, created_date, exclude_pk=exclude_pk
        )  # Get next available sequence number
        name = cls.build_name(
            level, vacancy, project_display, created_date, seq
        )  # Build full name with sequence
        qs = cls.all_objects.all()  # Get all objects for slug uniqueness check
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)  # Exclude current object when updating
        slug = cls.generate_unique_slug(name, qs)  # Generate unique URL-friendly slug
        return name, slug

    def save(self, *args, **kwargs) -> None:
        """
        Overrides the save method to automatically generate the name and slug.

        When updating an existing object, a unique name and slug are generated
        based on the level, vacancy, project, and creation date. Handles potential
        IntegrityError due to race conditions by retrying up to 3 times.

        Args:
            *args: Variable length argument list passed to parent save method
            **kwargs: Arbitrary keyword arguments passed to parent save method

        Raises:
            IntegrityError: If name/slug uniqueness cannot be achieved after 3 attempts
        """

        update_fields = kwargs.get(
            "update_fields"
        )  # Check if specific fields are being updated

        if self.pk and not update_fields:
            # For existing objects without specific update_fields, regenerate name and slug
            for attempt in range(3):  # Try up to 3 times to handle race conditions
                self._generate_name_and_slug()  # Generate new name and slug
                try:
                    models.Model.save(self, *args, **kwargs)  # Try to save
                    return
                except IntegrityError:  # Handle name/slug collision
                    if attempt == 2:  # If this was the last attempt
                        raise  # Re-raise the exception
        else:
            # For new objects or updates with specific fields
            super().save(*args, **kwargs)

    def _generate_name_and_slug(self):
        """
        Helper method to generate a new name and slug for this instance.

        Uses the class method generate_name_and_slug and updates the instance
        attributes if the generated name differs from the current one.
        """
        new_name, new_slug = WorkingForm.generate_name_and_slug(
            self.level, self.vacancy, self.project, self.created_at, exclude_pk=self.pk
        )
        if self.name != new_name:
            self.name = new_name  # Update name if different
            self.slug = new_slug  # Update slug if name changed

    def __str__(self):
        """
        String representation of the object.

        Returns:
            str: A human-readable string identifying this working form
        """

        return f"[Working form] {self.level} {self.vacancy}"

    class Meta:
        verbose_name = "Working form"
        verbose_name_plural = "Working forms"
        # Цей Meta не наслідує BaseForm.Meta, тому ordering тут потрібен свій -
        # інакше модель лишилася б без сортування, а решта пайплайну з ним.
        ordering = ["-created_at", "-pk"]


class WorkingFormTopicQuerySet(models.QuerySet):
    """
    Custom QuerySet with annotation methods for WorkingFormTopic.

    Provides specialized query methods for WorkingFormTopic objects,
    particularly for annotating topics with additional information
    needed for the UI and business logic.
    """

    def get_annotated_list(self):
        """
        Returns a queryset of topics with annotations.

        Enhances the queryset with calculated fields that provide information
        about the topic's status, approval process, and question statistics.

        Annotations include:
        - topic_delete_votes: number of votes to delete the topic.
        - total_approvers_annotated: total number of approvers.
        - questions_count: number of active questions in the topic.
        - candidate_for_deletion_count: number of questions that are candidates for deletion.

        Returns:
            QuerySet: An annotated queryset with additional calculated fields
        """

        return self.select_related("topic", "working_form").annotate(
            topic_delete_votes=Count(
                "deleted_by", distinct=True
            ),  # Count of users who voted to delete this topic
            total_approvers_annotated=Count(
                "working_form__approvers", distinct=True
            ),  # Total approvers for the form
            questions_count=Count(
                "items", filter=Q(items__is_removed=False), distinct=True
            ),  # Count of active questions in this topic
            candidate_for_deletion_count=Count(
                "items",
                filter=Q(items__deleted_by__isnull=False) & Q(items__is_removed=False),
                distinct=True,
            ),  # Count of questions with deletion votes but not yet removed
        )


class WorkingFormTopicManager(models.Manager):
    """
    Custom manager for the WorkingFormTopic model.

    Implements the soft deletion pattern by filtering out deleted records.
    By default, returns only objects that have not been soft-deleted
    (where is_removed=False).
    """

    def get_queryset(self):
        """
        Overrides the default queryset to filter out soft-deleted topics.

        Returns:
            QuerySet: A filtered queryset containing only non-removed topics
        """
        return WorkingFormTopicQuerySet(self.model, using=self._db).filter(
            is_removed=False  # Only include topics that haven't been soft-deleted
        )

    def get_annotated_list(self):
        """
        Convenience method to get an annotated list of non-removed topics.

        Delegates to the queryset's get_annotated_list method after applying
        the is_removed=False filter.

        Returns:
            QuerySet: An annotated queryset of non-removed topics
        """
        return self.get_queryset().get_annotated_list()


class WorkingFormTopic(EffectiveDeletionMixin, models.Model):
    """
    Intermediate model for the relationship between WorkingForm and Topic.

    Represents a topic in the context of a specific working form. Allows
    tracking of votes for deleting the topic and its status. This model
    implements the many-to-many relationship between WorkingForm and Topic
    with additional attributes specific to that relationship.

    The class inherits from EffectiveDeletionMixin which provides functionality
    for determining when a topic should be considered effectively deleted based
    on the number of deletion votes.
    """

    working_form = models.ForeignKey(
        WorkingForm,
        on_delete=models.CASCADE,  # If the working form is deleted, delete all its topics
        related_name="form_topics",  # Access from WorkingForm via form_topics
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.PROTECT,  # Prevent deletion of topics that are used in forms
        related_name="working_form_topics",  # Access from Topic via working_form_topics
    )
    deleted_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="deleted_working_form_topics",  # Access from User via deleted_working_form_topics
        blank=True,
        help_text="Voted for deleting the topic by interviewers",
    )
    is_removed = models.BooleanField(
        default=False,
        help_text="Soft delete - form topic removed from working form but kept for history",
    )

    objects = (
        WorkingFormTopicManager()
    )  # Default manager that filters out removed topics
    all_objects = (
        WorkingFormTopicQuerySet.as_manager()
    )  # Manager that includes all topics, even removed ones

    def _get_working_form(self):
        """
        Implementation of the abstract method from EffectiveDeletionMixin.

        Returns the working form associated with this topic, used by the mixin
        to determine the approvers for deletion voting.

        Returns:
            WorkingForm: The working form this topic belongs to
        """
        return self.working_form

    def __str__(self):
        """
        String representation of the object.

        Returns:
            str: A human-readable string identifying this working form topic
        """
        return f"{self.working_form} - {self.topic}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["working_form", "topic"],
                name="unique_working_form_topic_pair",
            )
        ]
        verbose_name = "Topic of working form"
        verbose_name_plural = "Topics of working form"


class WorkingFormItemQuerySet(models.QuerySet):
    """
    Custom QuerySet with annotation methods for WorkingFormItem.

    Provides specialized query methods for WorkingFormItem objects,
    particularly for annotating items with additional information
    needed for the UI and business logic around deletion voting.
    """

    def get_annotated_list(self):
        """
        Returns a QuerySet with form items and related data.

        Uses prefetch_related and annotate to minimize DB queries and optimize
        performance when retrieving items with their deletion status information.

        Adds annotations:
        - delete_votes: number of votes to delete the item.
        - total_approvers: total number of approvers in the form.

        Returns:
            QuerySet: An annotated queryset with additional calculated fields
        """

        return (
            self.select_related(
                "form_topic__working_form"
            )  # Efficiently load related objects
            .prefetch_related(
                "deleted_by",  # Prefetch users who voted to delete
                "form_topic__working_form__approvers",  # Prefetch approvers
                "form_topic__working_form__approved_by",  # Prefetch users who approved
            )
            .annotate(
                delete_votes=Count("deleted_by", distinct=True),  # Count deletion votes
                total_approvers=Count(
                    "form_topic__working_form__approvers", distinct=True
                ),  # Count total approvers
            )
        )


class WorkingFormItemManager(models.Manager):
    """
    Custom manager for the WorkingFormItem model.

    Implements the soft deletion pattern by filtering out deleted records.
    By default, returns only objects that have not been soft-deleted
    (where is_removed=False).
    """

    def get_queryset(self):
        """
        Overrides the default queryset to filter out soft-deleted items.

        Returns:
            QuerySet: A filtered queryset containing only non-removed items
        """
        return WorkingFormItemQuerySet(self.model, using=self._db).filter(
            is_removed=False  # Only include items that haven't been soft-deleted
        )

    def get_annotated_list(self):
        """
        Convenience method to get an annotated list of non-removed items.

        Delegates to the queryset's get_annotated_list method after applying
        the is_removed=False filter.

        Returns:
            QuerySet: An annotated queryset of non-removed items
        """
        return self.get_queryset().get_annotated_list()


class WorkingFormItem(EffectiveDeletionMixin, BaseFormItems):
    """
    Model for an item (question) within a working form topic.

    Represents a specific question or point for discussion within a topic.
    This model stores a snapshot of the question at the time it was added
    to the working form, allowing it to be modified independently from the
    original question.

    Snapshot-fields are filled in working_form.services.py (add_question_to_topic)

    The class inherits from:
    - EffectiveDeletionMixin: Provides functionality for determining when an item
      should be considered effectively deleted based on the number of deletion votes.
    - BaseFormItems: Provides common fields for form items like text_snapshot,
      difficulty_snapshot, etc.

    Allows tracking of votes for deleting this item, with the actual deletion
    occurring when enough approvers vote for deletion.
    """

    form_topic = models.ForeignKey(
        WorkingFormTopic,
        on_delete=models.CASCADE,  # If the topic is deleted, delete all its items
        related_name="items",  # Access from WorkingFormTopic via items
    )

    deleted_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="deleted_items",  # Access from User via deleted_items
        blank=True,
        help_text="Voted for deleting the item by approvers",
    )

    objects = WorkingFormItemManager()  # Default manager that filters out removed items
    all_objects = (
        WorkingFormItemQuerySet.as_manager()
    )  # Manager that includes all items, even removed ones

    def _get_working_form(self):
        """
        Implementation of the abstract method from EffectiveDeletionMixin.

        Returns the working form associated with this item's topic, used by the mixin
        to determine the approvers for deletion voting.

        Returns:
            WorkingForm: The working form this item belongs to
        """
        return self.form_topic.working_form

    def __str__(self):
        """
        String representation of the object.

        Returns a string containing the topic name and the first 60 characters
        of the question text (or a placeholder if empty).

        Returns:
            str: A human-readable string identifying this item
        """
        return f"[{self.form_topic.topic}] {self.text_snapshot[:60] if self.text_snapshot else '—'}"

    class Meta:
        verbose_name = "Snapshot-item of working form"
        verbose_name_plural = "Snapshot-items of working form"
