from django.conf import settings
from django.db import models
from django.utils import timezone

from question.models import Question
from techstack.models import TechStack
from django.utils.text import slugify
from topic.models import Topic


class SoftDeleteManager(models.Manager):
    """
    Default manager for all `BaseForm` descendants.

    Implements the soft deletion pattern by filtering out deleted records:
    by default, returns only objects whose `is_deleted` field is False.
    Use `all_objects` (a plain `models.Manager`) to reach deleted rows,
    e.g. for slug-uniqueness checks or admin restore views.
    """

    def get_queryset(self):
        """
        Overrides the default queryset by adding an `is_deleted=False` filter.

        Returns:
            QuerySet: A filtered queryset containing only non-deleted forms.
        """
        return super().get_queryset().filter(is_deleted=False)


class BaseForm(models.Model):
    """
    An abstract base model that provides shared fields and functionality for
    form-like structures within the application.

    This model is intended to be inherited by concrete form models
    (e.g., TemplateForm, WorkingForm) and does not create a separate database
    table. It encapsulates common attributes such as the name, associated
    manager, technology stack, and timestamp fields.

    A key feature is the automatic generation of a URL-friendly `slug` from
    the `name` field on the first save, ensuring a unique identifier for each
    form instance.

    Attributes:
        - name (CharField): A human-readable name of the form.
        - manager (ForeignKey): The user responsible for managing the form.
            The reverse relation is dynamically named using `%(class)s_forms`.
        - tech_stack (ForeignKey): The technology stack associated with the form.
            Deletion is protected (PROTECT) to prevent data loss.
        - slug (SlugField): A unique, URL-friendly identifier.
        - created_at (DateTimeField): Timestamp when the form was created.
        - updated_at (DateTimeField): Timestamp of the last update.
    """

    # Name of the form
    # Example: "Java Developer Interview", "Python Backend Assessment"
    name = models.CharField(max_length=500)

    # User who manages this form
    # Example: User(id=1, username="john.doe", email="john.doe@example.com")
    # When the user is deleted, this field becomes NULL
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_forms",  # Dynamically creates relationship name like "templateform_forms"
    )

    # Technology stack associated with this form
    # Example: TechStack(id=1, name="Java"), TechStack(id=2, name="Python")
    # Protected from deletion to prevent orphaned forms
    tech_stack = models.ForeignKey(
        TechStack, on_delete=models.PROTECT, related_name="%(class)s_forms"
    )

    # URL-friendly identifier generated from the name
    # Example: "java-developer-interview", "python-backend-assessment"
    slug = models.SlugField(max_length=500, blank=True, unique=True)

    # Timestamp when the form was created
    # Example: datetime(2023, 5, 10, 9, 30, 0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Timestamp when the form was last updated
    # Example: datetime(2023, 5, 15, 14, 45, 0)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft delete flag: True hides the form from the default manager
    # Example: False (visible form), True (deleted, restorable via admin)
    is_deleted = models.BooleanField(default=False, db_index=True)

    # Timestamp when the form was soft-deleted, NULL for live forms
    # Example: datetime(2023, 6, 1, 12, 0, 0)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # User who performed the soft delete, NULL for live forms
    # SET_NULL keeps the deletion record even if the user is removed
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_deleted",  # Dynamically creates names like "templateform_deleted"
    )

    # First declared manager becomes the default: hides soft-deleted rows
    objects = SoftDeleteManager()
    # Unfiltered manager: slug-uniqueness checks and admin restore need deleted rows too
    all_objects = models.Manager()

    class Meta:
        abstract = True

    @staticmethod
    def generate_unique_slug(name, queryset):
        """
        Generates a unique slug for the given name within the specified queryset.

        Args:
            name (str): The name to generate the slug from.
                       Example: "Java Developer Interview"
            queryset (QuerySet): The queryset to check for existing slugs.
                                Example: TemplateForm.objects.all()

        Returns:
            str: A unique slug derived from the name.
                Example: "java-developer-interview" or "java-developer-interview-1" if the first one exists
        """
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        while queryset.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        """
        Generates a slug from the name field before saving if it does not already exist.

        Args:
            *args: Variable length argument list passed to the parent save method.
            **kwargs: Arbitrary keyword arguments passed to the parent save method.
                     Example: {"force_insert": True}

        Example:
            form = TemplateForm(name="Java Developer Interview", tech_stack=tech_stack)
            form.save()  # Will generate slug "java-developer-interview" before saving
        """
        if not self.slug:
            # all_objects: a soft-deleted form still reserves its slug, otherwise
            # reusing its name would raise IntegrityError on the unique constraint
            self.slug = self.generate_unique_slug(
                self.name, self.__class__.all_objects.all()
            )
        super().save(*args, **kwargs)

    def soft_delete(self, user):
        """
        Marks the form as deleted instead of removing the database row.

        Stores the audit trail (who and when) and saves only the three
        soft-delete fields. `update_fields` is critical here: subclasses
        (e.g. WorkingForm) regenerate name/slug on a full save of an
        existing object, which would rename the form on deletion.

        Args:
            user: The user performing the deletion, stored in `deleted_by`.
        """
        self.is_deleted = True
        self.deleted_by = user
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_by", "deleted_at"])

    def restore(self):
        """
        Reverses a soft delete, making the form visible to `objects` again.

        Clears the audit fields and saves via `update_fields` for the same
        reason as `soft_delete` - to avoid name/slug regeneration.
        """
        self.is_deleted = False
        self.deleted_by = None
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_by", "deleted_at"])


class TemplateForm(BaseForm):
    """
    Model representing a reusable template for creating evaluation forms.

    `TemplateForm` serves as the primary blueprint that groups a set of topics
    and their associated questions. It inherits core fields from `BaseForm` and
    adds extended logic for managing content versions through a draft mechanism.

    This mechanism allows modifications to the form (such as adding or removing
    topics and questions) to be saved as a draft (`draft_data`) without affecting
    the published, active version. This ensures stability for forms that are
    already in use.

    Attributes:
        - topics (ManyToManyField): A many-to-many relationship with `Topic` models,
            implemented via the `TemplateFormTopic` through model.
        - draft_data (JSONField): A field for storing unpublished changes
            in a structured JSON format.
        - has_unpublished_changes (BooleanField): A flag indicating the presence
            of draft changes that have not yet been applied.
        - draft_updated_at (DateTimeField): Timestamp of the last draft update.
    """

    # Topics associated with this template form
    # Example: [Topic(id=1, name="ORM"), Topic(id=2, name="REST API")]
    # Implemented through the TemplateFormTopic model to store additional data
    topics = models.ManyToManyField(
        Topic, through="TemplateFormTopic", related_name="template_forms", blank=True
    )

    # JSON data containing unpublished changes to the form
    # Example: {"name": "Updated Java Interview", "topics_with_questions": [...]}
    # Stores draft state that hasn't been applied to the actual form yet
    draft_data = models.JSONField(
        null=True, blank=True, help_text="Unpublished changes"
    )

    # Flag indicating if there are unpublished changes
    # Example: True (meaning there are draft changes), False (no draft changes)
    has_unpublished_changes = models.BooleanField(
        default=False, help_text="Flag for unpublished changes"
    )

    # Timestamp of when the draft was last updated
    # Example: datetime(2023, 5, 15, 14, 30, 45)
    # NULL if no draft has been saved
    draft_updated_at = models.DateTimeField(
        null=True, blank=True, help_text="When draft was last updated"
    )

    class Meta:
        # -pk, бо created_at це auto_now_add: клонування створює пачку форм з
        # однаковою міткою, і без унікального тайбрейкера порядок у межах пачки
        # лишається на розсуд планувальника запитів.
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        """
        String representation of the TemplateForm, indicating draft status.

        Returns:
            str: The name of the form, with " (Has Draft)" appended if there are unpublished changes.
                Example: "Java Developer Interview" or "Java Developer Interview (Has Draft)"
        """
        status = " (Has Draft)" if self.has_unpublished_changes else ""
        return f"{self.name}{status}"


class BaseFormItems(models.Model):
    """
    Abstract base model for form items, typically representing questions.

    This model implements the core "snapshot" concept. Fields with the
    `_snapshot` suffix store a copy of the original question data at the time
    it is added to the form. This guarantees that the form content remains
    historically accurate and unchanged, even if the original question is
    later modified or deleted.

    The model supports two usage scenarios:
    1. Referencing an existing question via the `origin_question` field.
    2. Creating a custom question directly within the form (in this case,
       `origin_question` remains `NULL`).

    A "soft delete" mechanism is also implemented via the `is_removed` flag,
    allowing the form to preserve a history of changes.

    Attributes:
        - text_snapshot (TextField): Snapshot of the question text.
        - difficulty_snapshot (IntegerField): Snapshot of the question difficulty.
        - source_snapshot (CharField): Snapshot of the question source (e.g., 'TEMPLATE').
        - topic_snapshot (CharField): Snapshot of the name of the topic
            to which the question belongs.
        - max_score_snapshot (IntegerField): Snapshot of the maximum score for the question.
        - origin_question (ForeignKey): Reference to the original `question.Question` object.
            May be `NULL` if the question was created specifically for this form.
        - is_removed (BooleanField): Flag for "soft deletion". `True` if the question
            was removed from the form but preserved for history.
        - added_by (ForeignKey): The user who added this item to the form.
        - created_at (DateTimeField): Timestamp when the item was added to the form.
    """

    # Enumeration of difficulty levels for questions
    # Used for both storing and displaying difficulty values
    class Difficulty(models.IntegerChoices):
        EASY = 1, "Easy"  # Easiest questions, basic knowledge
        MEDIUM = 2, "Medium"  # Intermediate difficulty, requires deeper understanding
        HARD = 3, "Hard"  # Most difficult questions, advanced topics

    # Text of the question
    # Example: "What is dependency injection?", "Explain the difference between REST and SOAP"
    text_snapshot = models.TextField(blank=True, null=True)

    # Difficulty level of the question
    # Example: 1 (Easy), 2 (Medium), 3 (Hard)
    # Stored as integer but displayed using the Difficulty choices
    difficulty_snapshot = models.IntegerField(
        choices=Difficulty.choices, blank=True, null=True
    )

    # Source of the question
    # Example: "TEMPLATE", "CUSTOM", "LIBRARY"
    # Indicates where the question originated from
    source_snapshot = models.CharField(max_length=25, blank=True, null=True)

    # Name of the topic this question belongs to
    # Example: "ORM", "REST API", "Authentication"
    # Denormalized from the related Topic model for historical accuracy
    topic_snapshot = models.CharField(max_length=125, blank=True, null=True)

    # Maximum score possible for this question
    # Example: 3 (for Easy), 6 (for Medium), 9 (for Hard)
    # Typically calculated as difficulty_snapshot * SCORE_MULTIPLIER
    max_score_snapshot = models.IntegerField(blank=True, null=True)

    # Reference to the original question this item was based on
    # Example: Question(id=42, question_text="What is dependency injection?")
    # NULL if the question was created specifically for this form
    origin_question = models.ForeignKey(
        "question.Question",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Link to the original question. Null for custom questions",
    )

    # Flag indicating if this question has been removed from the form
    # Example: False (active question), True (removed question)
    # Used for "soft deletion" to preserve history
    is_removed = models.BooleanField(
        default=False,
        help_text="Soft delete - question removed from form but kept for history",
    )

    # User who added this question to the form
    # Example: User(id=1, username="john.doe", email="john.doe@example.com")
    # NULL if the user has been deleted
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_added_items",  # Creates names like "templateformitems_added_items"
        help_text="Who added this question to THIS form",
    )

    # Timestamp when this question was added to the form
    # Example: datetime(2023, 5, 12, 10, 15, 0)
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="When this question was added to THIS form"
    )

    class Meta:
        abstract = True
        ordering = (
            "difficulty_snapshot",
            "topic_snapshot",
        )


class TemplateFormTopic(models.Model):
    """
    Through model for the many-to-many relationship between `TemplateForm`
    and `Topic`.

    This model creates an explicit association between a specific form template
    and a topic, allowing topics to belong to multiple templates and templates
    to contain multiple topics. It serves as the parent object for
    `TemplateFormItems`, grouping questions by topic within a single form.

    The `unique_together` constraint ensures that the same topic cannot be
    added to the same form more than once.

    Attributes:
        - form (ForeignKey): Reference to a `TemplateForm` instance.
        - topic (ForeignKey): Reference to a `Topic` instance.
    """

    # Reference to the template form this topic belongs to
    # Example: TemplateForm(id=1, name="Java Developer Interview")
    # When the form is deleted, all associated topics are also deleted (CASCADE)
    form = models.ForeignKey(
        TemplateForm, on_delete=models.CASCADE, related_name="form_topics"
    )

    # Reference to the topic associated with this form
    # Example: Topic(id=1, name="ORM")
    # When the topic is deleted, all associated form topics are also deleted (CASCADE)
    topic = models.ForeignKey(
        Topic, on_delete=models.CASCADE, related_name="form_topics"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["form", "topic"], name="unique_form_topic_pair"
            )
        ]

    def __str__(self):
        """
        Returns:
            str: A string in the format "Form name - Topic name".
                Example: "Java Developer Interview - ORM"

        This string representation is useful for identifying form-topic relationships
        in the admin interface and in debugging.
        """
        return f"{self.form.name} - {self.topic.name}"


class TemplateFormItems(BaseFormItems):
    """
    A concrete implementation of a form item for `TemplateForm`.

    This model inherits the snapshot functionality from `BaseFormItems` and
    links a question to a specific topic within a form template via the
    `form_topic` foreign key.

    Attributes:
        - form_topic (ForeignKey): Relationship to the `TemplateFormTopic` object,
            which defines the topic and form to which this item belongs.
    """

    # Reference to the form topic this item belongs to
    # Example: TemplateFormTopic(form=TemplateForm(id=1), topic=Topic(id=1))
    # Links this question to both a specific form and a specific topic
    # When the form topic is deleted, all associated items are also deleted (CASCADE)
    form_topic = models.ForeignKey(
        TemplateFormTopic,
        on_delete=models.CASCADE,
        related_name="items",  # Allows access to items via form_topic.items.all()
    )

    @property
    def form(self):
        """
        A property that provides convenient access to the parent `TemplateForm` object.
        This is a shortcut to avoid having to write self.form_topic.form each time.

        Returns:
            TemplateForm: The form instance to which this item belongs.
                         Example: TemplateForm(id=1, name="Java Developer Interview")

        Example:
            # Instead of:
            template = item.form_topic.form

            # You can use:
            template = item.form
        """
        return self.form_topic.form

    class Meta:
        verbose_name_plural = "Template Form Items"

    def save(self, *args, **kwargs):
        """
        Populates snapshot fields before saving the item.

        This method automates data denormalization by copying attributes from
        related objects (`Topic`, `Question`) into the `_snapshot` fields.
        This ensures the form data remains consistent over time.

        Execution logic:
        1. Sets `topic_snapshot` from the name of the topic associated with `form_topic`.
        2. If `origin_question` exists:
           - Copies `source`, `question_text`, and `difficulty` if the corresponding
             snapshot fields have not yet been populated.
        3. Calculates `max_score_snapshot` based on `difficulty_snapshot`
           (typically, the difficulty multiplied by a constant).

        Args:
            *args: Variable length argument list passed to the parent save method.
            **kwargs: Arbitrary keyword arguments passed to the parent save method.
                     Example: {"force_insert": True}

        Example:
            # Creating a new item from an existing question
            item = TemplateFormItems(
                form_topic=form_topic,
                origin_question=question
            )
            item.save()  # Will populate all snapshot fields automatically

            # Creating a custom question
            item = TemplateFormItems(
                form_topic=form_topic,
                text_snapshot="What is dependency injection?",
                difficulty_snapshot=2,
                source_snapshot="CUSTOM"
            )
            item.save()  # Will calculate max_score_snapshot automatically
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

            self.max_score_snapshot = (
                self.difficulty_snapshot * Question.SCORE_MULTIPLIER
            )
        else:

            self.max_score_snapshot = None

        super().save(*args, **kwargs)

    def __str__(self):
        """
        Returns:
            str: A string in the format "[Topic name] Beginning of the question text...".
                Example: "[ORM] What is an ORM and how does it work?..."

        This string representation is useful for identifying items in the admin interface
        and in debugging, as it shows both the topic and the beginning of the question.
        """
        return f"[{self.form_topic.topic.name}] {self.text_snapshot[:60]}..."


class ReadOnlyTemplateForm(TemplateForm):
    """
    A read-only proxy model for `TemplateForm`.

    This model provides an alternative interface for `TemplateForm` in the Django
    admin panel, intended exclusively for viewing purposes. It does not create
    a new database table (`proxy = True`), but instead offers a different admin
    configuration (e.g., with editing permissions disabled) for the same table.
    """

    class Meta:
        proxy = True
        verbose_name = "Template Form (Read-Only)"
        verbose_name_plural = "Template Forms (Read-Only)"


class ReadOnlyFormTopic(TemplateFormTopic):
    """
    A read-only proxy model for `TemplateFormTopic`.

    Similar to `ReadOnlyTemplateForm`, this proxy model is used to provide a
    separate, restricted view of the `TemplateFormTopic` relationship in the
    Django admin panel, typically for displaying a list of topics and their
    questions without edit permissions.
    """

    class Meta:
        proxy = True
        verbose_name = "Form Topic (Read-Only)"
        verbose_name_plural = "Form Topics (Read-Only)"
