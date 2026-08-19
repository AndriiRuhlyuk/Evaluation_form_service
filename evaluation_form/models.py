from datetime import timedelta  # Used for time calculations, e.g., timedelta(hours=1)

from django.db import models  # Core Django ORM functionality
from django.conf import settings  # Access to Django settings, e.g., AUTH_USER_MODEL
from django.utils import timezone  # Timezone utilities, e.g., timezone.now()
from django.utils.text import (
    slugify,
)  # Converts strings to URL-friendly format, e.g., "Test Name" -> "test-name"

from question.models import Question  # Question model for evaluation items
from template_form.models import (
    BaseForm,
)  # Base form model that EvaluationForm inherits from
from topic.models import Topic  # Topic model for organizing questions
from working_form.models import (
    WorkingForm,
)  # Source model for creating evaluation forms


INTERVIEW_PENDING_THRESHOLD = timedelta(hours=1)


class Candidate(models.Model):
    """
    Model: information about the candidate being interviewed.
    """

    # Candidate's full name, e.g., "John Smith"
    full_name = models.CharField(max_length=255)

    # Candidate's email address, e.g., "john.smith@example.com"
    email = models.EmailField(unique=True)

    # URL to candidate's profile or CV, e.g., "https://linkedin.com/in/johnsmith"
    pf_link = models.URLField()

    def __str__(self):
        # Returns the candidate's full name as string representation, e.g., "John Smith"
        return self.full_name


class EvaluationForm(BaseForm):
    """
    A snapshot of an approved WorkingForm, used to conduct
    an interview for a specific candidate.
    Inherits 'name', 'slug', 'manager', 'tech_stack' from BaseForm.
    """

    # Inner class defining possible status values for the evaluation form
    class Status(models.TextChoices):
        PENDING = (
            "pending",
            "Pending",
        )  # Form is waiting for interview date, e.g., "pending"
        IN_PROGRESS = (
            "in_progress",
            "In Progress",
        )  # Interview is happening or imminent, e.g., "in_progress"
        COMPLETED = "completed", "Completed"  # Interview is finished, e.g., "completed"

    # Reference to the original working form this evaluation was created from, e.g., WorkingForm(id=5)
    working_form_origin = models.ForeignKey(
        WorkingForm,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluations",
        help_text="The WorkingForm this evaluation was cloned from.",
    )

    # Reference to the candidate being evaluated, e.g., Candidate(full_name="John Smith")
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.PROTECT,
        related_name="evaluations",
        help_text="The candidate being evaluated.",
    )

    # List of users who will conduct the interview, e.g., [User(username="interviewer1"), User(username="interviewer2")]
    interviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="interviewer_evaluations",
        help_text="Interviewers who will conduct the interview.",
    )

    # List of recruiters involved in the hiring process, e.g., [User(username="recruiter1")]
    recruiters = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="recruiter_evaluation_forms",
        blank=True,
        help_text="The recruiter(s) who is responding for hiring process.",
    )

    # The manager making the final hiring decision, e.g., User(username="manager1")
    hiring_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="hiring_manager_evaluation_forms",
        help_text="The hiring manager who is responding for make final decision about hiring.",
    )

    # Date and time when the interview is scheduled, e.g., datetime(2023, 5, 15, 14, 30, tzinfo=UTC)
    interview_datetime = models.DateTimeField(
        db_index=True, help_text="Date and time of the scheduled interview."
    )

    # Current status of the evaluation form, e.g., "pending", "in_progress", "completed"
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text="The status of the evaluation form",
    )

    # Name of the vacancy being filled, e.g., "Python Developer"
    vacancy_snapshot = models.CharField(max_length=255)

    # Level of the position, e.g., "Junior", "Middle", "Senior"
    level_snapshot = models.CharField(max_length=20)

    # Optional project name the candidate would work on, e.g., "Customer Portal"
    project_snapshot = models.CharField(max_length=255, blank=True)

    # Path to the generated report file, e.g., "reports/2023/05/evaluation_123.html"
    report_file = models.FileField(
        upload_to="reports/%Y/%m/",
        null=True,
        blank=True,
        help_text="Static HTML snapshot of the evaluation",
    )

    # Meta class for model configuration
    class Meta:
        # Orders evaluation forms by interview date (newest first), e.g., [EvaluationForm(interview_datetime="2023-05-20"), EvaluationForm(interview_datetime="2023-05-15")]
        ordering = ["-interview_datetime"]

    def save(self, *args, **kwargs) -> None:
        """
        - Auto-manage evaluation form status if interview_datetime was changed
        - Updates name and slug automatically if related fields change *on update*.
        - Creation logic (name/slug generation) is handled by the
        service layer that calls .create().

        Example:
        When saving an evaluation form with updated interview_datetime,
        it might change status from "pending" to "in_progress" and
        update the name to "Evaluation Senior Python Developer Customer Portal (John Smith) 42"
        """

        # update_fields означає, що викликач явно перелічив поля - регенерувати name/slug
        # у цій гілці не можна: super().save() їх не запише, і об'єкт у пам'яті розійдеться
        # з базою (саме так soft_delete() ламав slug). WorkingForm.save() робить так само.
        if self.pk and not kwargs.get("update_fields"):
            try:
                # Get the previous state of this object from database
                # all_objects: an admin may edit a soft-deleted row, which the
                # filtered default manager would not find
                old_instance = EvaluationForm.all_objects.get(pk=self.pk)
                # If interview time changed, update status accordingly
                if old_instance.interview_datetime != self.interview_datetime:
                    self._update_status_based_on_time()

            except EvaluationForm.DoesNotExist:
                pass

            # Generate a new name based on current field values, e.g., "Evaluation Senior Python Developer Customer Portal (John Smith) 42"
            new_name = f"Evaluation {self.level_snapshot} {self.vacancy_snapshot} {self.project_snapshot} ({self.candidate.full_name}) {self.pk}".strip()

            # If name hasn't changed, just save without further processing
            if self.name == new_name:
                super().save(*args, **kwargs)
                return

            # Update name and slug with new values
            self.name = new_name
            new_slug = slugify(
                self.name
            )  # e.g., "evaluation-senior-python-developer-customer-portal-john-smith-42"

            self.slug = new_slug

        # Call parent class save method
        super().save(*args, **kwargs)

    def _update_status_based_on_time(self):
        """
        Help Method:
        Set PENDING or IN_PROGRESS status, depend on new interview datetime.
        (Call from 'save()')

        Example:
        - If interview is more than 1 hour in future: status = "pending"
        - If interview is less than 1 hour away or in past: status = "in_progress"
        - If status is already "completed", it remains unchanged
        """

        # Don't change status if interview is already completed
        if self.status == EvaluationForm.Status.COMPLETED:
            return

        # Get current time and calculate threshold (1 hour from now)
        now = timezone.now()  # e.g., 2023-05-15 13:30:00+00:00
        one_hour_later = (
            now + INTERVIEW_PENDING_THRESHOLD
        )  # e.g., 2023-05-15 14:30:00+00:00

        # Set status based on interview time
        if self.interview_datetime > one_hour_later:
            self.status = EvaluationForm.Status.PENDING
        else:
            self.status = EvaluationForm.Status.IN_PROGRESS

    def __str__(self):
        # Returns the form name as string representation, e.g., "Evaluation Senior Python Developer (John Smith) 42"
        return self.name


class EvaluationFormTopic(models.Model):
    """
    Represents a topic within an evaluation form, organizing related questions.
    """

    # Reference to the parent evaluation form, e.g., EvaluationForm(id=42)
    evaluation_form = models.ForeignKey(
        EvaluationForm,
        on_delete=models.CASCADE,  # If evaluation form is deleted, delete this topic too
        related_name="form_topics",
    )

    # Reference to the original topic, e.g., Topic(name="Python Core")
    topic = models.ForeignKey(
        Topic,
        on_delete=models.PROTECT,  # Prevent deletion of topics that are used in evaluations
        related_name="evaluation_topics",
    )

    # Snapshot of the topic name at the time of evaluation creation, e.g., "Python Core"
    topic_name_snapshot = models.CharField(
        max_length=255, help_text="Snapshot of topic name"
    )

    def __str__(self):
        # Returns a string representation like "Python Core (Evaluation #42)"
        return f"{self.topic_name_snapshot} ({self.evaluation_form})"


class EvaluationFormItem(models.Model):
    """
    Snapshot of a Question. Does NOT inherit from BaseFormItems
    to avoid voting logic.
    """

    # Reference to the parent topic this question belongs to, e.g., EvaluationFormTopic(topic_name_snapshot="Python Core")
    form_topic = models.ForeignKey(
        EvaluationFormTopic,
        on_delete=models.CASCADE,  # If topic is deleted, delete all its questions
        related_name="items",
    )

    # The text of the question, e.g., "Explain the difference between list and tuple in Python"
    text_snapshot = models.TextField()

    # Difficulty level of the question (1-5), e.g., 3
    difficulty_snapshot = models.IntegerField()

    # Maximum possible score for this question, e.g., 3
    max_score_snapshot = models.IntegerField()

    # Source or category of the question, e.g., "technical", "behavioral"
    source_snapshot = models.CharField(max_length=50)

    # Reference to the original question this was copied from, e.g., Question(id=123)
    origin_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,  # If original question is deleted, keep this snapshot
        null=True,
        blank=True,
    )

    def __str__(self):
        # Returns a shortened version of the question text, e.g., "Explain the difference between list and..."
        return (
            f"{self.text_snapshot[:50]}..."
            if len(self.text_snapshot) > 50
            else self.text_snapshot
        )


class EvaluationScore(models.Model):
    """
    A single score given by a single interviewer to a single question.
    """

    # Inner class defining possible score values for evaluation questions
    class Score(models.IntegerChoices):
        NO_ANSWER = 0, "No Answer"  # Candidate couldn't answer the question, e.g., 0
        WEAK_ANSWER = 1, "Weak Answer"  # Candidate gave a poor answer, e.g., 1
        MEDIUM_ANSWER = (
            2,
            "Medium Answer",
        )  # Candidate gave an acceptable answer, e.g., 2
        STRONG_ANSWER = (
            3,
            "Strong Answer",
        )  # Candidate gave an excellent answer, e.g., 3

    # Reference to the question being scored, e.g., EvaluationFormItem(text_snapshot="Explain Python decorators")
    item = models.ForeignKey(
        EvaluationFormItem,
        on_delete=models.CASCADE,  # If question is deleted, delete all its scores
        related_name="scores",
    )

    # Reference to the interviewer giving the score, e.g., User(username="interviewer1")
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # Prevent deletion of users who have given scores
        related_name="scores_given",
    )

    # The numerical score given (0-3), e.g., 2
    score = models.IntegerField(
        choices=Score.choices,
        null=True,
        blank=True,
        help_text="Score given by interviewer (leave empty if not asked)",
    )

    # Optional comment about the candidate's answer, e.g., "Understood the concept but missed some edge cases"
    comment = models.TextField(blank=True, null=True)

    # Flag indicating if interviewer couldn't properly evaluate this question, e.g., True/False
    lacks_expertise = models.BooleanField(
        default=False,
        help_text="The interviewer noted that he did not have sufficient "
        "expertise in this matter to assess the candidate's answer.",
    )

    class Meta:
        # Ensures each interviewer can only score each question once
        unique_together = ("item", "interviewer")

    def __str__(self):
        # Returns a string like "Score 2 (Medium Answer) for 'Explain Python decorators...' by interviewer1"
        score_text = (
            f"{self.get_score_display()}" if self.score is not None else "Not scored"
        )
        return f"Score {self.score} ({score_text}) for '{str(self.item)[:30]}...' by {self.interviewer.username}"


class EvaluationFeedback(models.Model):
    """
    The final Pros/Cons/Decision feedback from a single interviewer.
    """

    # Inner class defining possible hiring decision values
    class Decision(models.TextChoices):
        NEXT_STEP = (
            "next_step",
            "Move to next step",
        )  # Candidate should proceed in the hiring process, e.g., "next_step"
        REFUSE = "refuse", "Refuse"  # Candidate should not proceed, e.g., "refuse"

    # Inner class defining possible candidate level assessments
    class CandidatesLevel(models.TextChoices):
        JUNIOR = "junior", "Junior"  # Junior level, e.g., "junior"
        MIDDLE = "middle", "Middle"  # Middle level, e.g., "middle"
        SENIOR = "senior", "Senior"  # Senior level, e.g., "senior"
        LEAD = "lead", "Lead"  # Lead level, e.g., "lead"
        MANAGER = "manager", "Manager"  # Manager level, e.g., "manager"

    # Reference to the evaluation form this feedback belongs to, e.g., EvaluationForm(id=42)
    evaluation_form = models.ForeignKey(
        EvaluationForm,
        on_delete=models.CASCADE,  # If evaluation form is deleted, delete all its feedback
        related_name="feedbacks",
    )

    # Reference to the interviewer giving the feedback, e.g., User(username="interviewer1")
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # Prevent deletion of users who have given feedback
        related_name="feedbacks_given",
    )

    # Positive aspects of the candidate, e.g., "Strong problem-solving skills, good communication"
    pros = models.TextField(blank=True)

    # Negative aspects of the candidate, e.g., "Limited experience with databases, needs improvement in system design"
    cons = models.TextField(blank=True)

    # Hiring recommendation, e.g., "next_step" or "refuse"
    decision = models.CharField(choices=Decision.choices, max_length=30, blank=True)

    # Assessment of candidate's skill level, e.g., "middle" or "senior"
    candidates_level = models.CharField(
        choices=CandidatesLevel.choices, max_length=20, blank=True
    )

    # Flag indicating if feedback is finalized and can no longer be edited, e.g., True/False
    is_submitted = models.BooleanField(
        db_index=True,
        default=False,
        help_text="Locks this feedback from further edits.",
    )

    class Meta:
        # Ensures each interviewer can only give one feedback per evaluation form
        unique_together = ("evaluation_form", "interviewer")

    def __str__(self):
        # Returns a string like "Feedback by interviewer1 for Evaluation #42 (John Smith)"
        return f"Feedback by {self.interviewer.username} for {self.evaluation_form}"
