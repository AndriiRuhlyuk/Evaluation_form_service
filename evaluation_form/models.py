from datetime import timedelta

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from question.models import Question
from template_form.models import BaseForm
from topic.models import Topic
from working_form.models import WorkingForm


class Candidate(models.Model):
    """
    Model: information about the candidate being interviewed.
    """

    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    pf_link = models.URLField()

    def __str__(self):
        return self.full_name


class EvaluationForm(BaseForm):
    """
    A snapshot of an approved WorkingForm, used to conduct
    an interview for a specific candidate.
    Inherits 'name', 'slug', 'manager', 'tech_stack' from BaseForm.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"

    working_form_origin = models.ForeignKey(
        WorkingForm,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluations",
        help_text="The WorkingForm this evaluation was cloned from.",
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.PROTECT,
        related_name="evaluations",
        help_text="The candidate being evaluated.",
    )
    interviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="interviewer_evaluations",
        help_text="Interviewers who will conduct the interview.",
    )
    recruiters = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="recruiter_evaluation_forms",
        blank=True,
        help_text="The recruiter(s) who is responding for hiring process.",
    )
    hiring_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="hiring_manager_evaluation_forms",
        help_text="The hiring manager who is responding for make final decision about hiring.",
    )
    interview_datetime = models.DateTimeField(
        help_text="Date and time of the scheduled interview."
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="The status of the evaluation form",
    )
    vacancy_snapshot = models.CharField(max_length=255)
    level_snapshot = models.CharField(max_length=20)
    project_snapshot = models.CharField(max_length=255, blank=True)

    report_file = models.FileField(
        upload_to="reports/%Y/%m/",
        null=True,
        blank=True,
        help_text="Static HTML snapshot of the evaluation",
    )

    class Meta:
        ordering = ["-interview_datetime"]

    def save(self, *args, **kwargs) -> None:
        """
        - Auto-manage evaluation form status if interview_datetime was changed
        - Updates name and slug automatically if related fields change *on update*.
        - Creation logic (name/slug generation) is handled by the
        service layer that calls .create().
        """

        if self.pk:
            try:
                old_instance = EvaluationForm.objects.get(pk=self.pk)
                if old_instance.interview_datetime != self.interview_datetime:
                    self._update_status_based_on_time()

            except EvaluationForm.DoesNotExist:
                pass

            new_name = f"Evaluation {self.level_snapshot} {self.vacancy_snapshot} {self.project_snapshot} ({self.candidate.full_name}) {self.pk}".strip()

            if self.name == new_name:

                super().save(*args, **kwargs)
                return

            self.name = new_name
            new_slug = slugify(self.name)

            self.slug = new_slug

        super().save(*args, **kwargs)

    def _update_status_based_on_time(self):
        """
        Help Method:
        Set PENDING or IN_PROGRESS status, depend on new interview datetime.
        (Call from 'save()')
        """

        if self.status == EvaluationForm.Status.COMPLETED:
            return

        now = timezone.now()
        one_hour_later = now + timedelta(hours=1)

        if self.interview_datetime > one_hour_later:
            self.status = EvaluationForm.Status.PENDING
        else:
            self.status = EvaluationForm.Status.IN_PROGRESS

    def __str__(self):
        return self.name


class EvaluationFormTopic(models.Model):
    evaluation_form = models.ForeignKey(
        EvaluationForm,
        on_delete=models.CASCADE,
        related_name="form_topics",
    )
    topic = models.ForeignKey(
        Topic, on_delete=models.PROTECT, related_name="evaluation_topics"
    )
    topic_name_snapshot = models.CharField(
        max_length=255, help_text="Snapshot of topic name"
    )


class EvaluationFormItem(models.Model):
    """
    Snapshot of a Question. Does NOT inherit from BaseFormItems
    to avoid voting logic.
    """

    form_topic = models.ForeignKey(
        EvaluationFormTopic,
        on_delete=models.CASCADE,
        related_name="items",
    )
    text_snapshot = models.TextField()
    difficulty_snapshot = models.IntegerField()
    max_score_snapshot = models.IntegerField()
    source_snapshot = models.CharField(max_length=50)
    origin_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )


class EvaluationScore(models.Model):
    """
    A single score given by a single interviewer to a single question.
    """

    class Score(models.IntegerChoices):
        NO_ANSWER = 0, "No Answer"
        WEAK_ANSWER = 1, "Weak Answer"
        MEDIUM_ANSWER = 2, "Medium Answer"
        STRONG_ANSWER = 3, "Strong Answer"

    item = models.ForeignKey(
        EvaluationFormItem,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="scores_given"
    )
    score = models.IntegerField(
        choices=Score.choices,
        null=True,
        blank=True,
        help_text="Score given by interviewer (leave empty if not asked)",
    )
    comment = models.TextField(blank=True, null=True)
    lacks_expertise = models.BooleanField(
        default=False,
        help_text="The interviewer noted that he did not have sufficient "
        "expertise in this matter to assess the candidate's answer.",
    )

    class Meta:
        unique_together = ("item", "interviewer")


class EvaluationFeedback(models.Model):
    """
    The final Pros/Cons/Decision feedback from a single interviewer.
    """

    class Decision(models.TextChoices):
        NEXT_STEP = "next_step", "Move to next step"
        REFUSE = "refuse", "Refuse"

    class CandidatesLevel(models.TextChoices):
        JUNIOR = "junior", "Junior"
        MIDDLE = "middle", "Middle"
        SENIOR = "senior", "Senior"
        LEAD = "lead", "Lead"
        MANAGER = "manager", "Manager"

    evaluation_form = models.ForeignKey(
        EvaluationForm, on_delete=models.CASCADE, related_name="feedbacks"
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="feedbacks_given",
    )
    pros = models.TextField(blank=True)
    cons = models.TextField(blank=True)
    decision = models.CharField(choices=Decision.choices, max_length=30, blank=True)
    candidates_level = models.CharField(
        choices=CandidatesLevel.choices, max_length=20, blank=True
    )

    is_submitted = models.BooleanField(
        default=False, help_text="Locks this feedback from further edits."
    )

    class Meta:
        unique_together = ("evaluation_form", "interviewer")
