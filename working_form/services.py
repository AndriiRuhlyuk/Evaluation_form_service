import uuid

from django.utils import timezone
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.utils.text import slugify

from employee.models import Employee
from evaluation_form.models import (
    Candidate,
    EvaluationForm,
    EvaluationFeedback,
    EvaluationFormTopic,
    EvaluationFormItem,
)
from question.models import Question
from template_form.services import _ensure_single_topic
from topic.models import Topic
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem
from rest_framework.exceptions import ValidationError


@transaction.atomic
def add_topic_to_working_form(
    working_form: WorkingForm, topic_data: dict
) -> WorkingFormTopic:
    """
    Adds a topic to a WorkingForm using the _ensure_single_topic helper.
    """

    topic = _ensure_single_topic(topic_data)

    if working_form.topics.filter(pk=topic.pk).exists():
        raise ValidationError(f"Topic '{topic.name}' is already in this working form.")

    working_form_topic = WorkingFormTopic.objects.create(
        working_form=working_form,
        topic=topic,
    )

    return working_form_topic


def _get_existing_question(question_id: int) -> Question:
    """Fetches an existing question by ID, raising a validation error if not found."""

    try:
        return Question.objects.get(pk=question_id)
    except Question.DoesNotExist:
        raise ValidationError(f"Question with id={question_id} not found.")


def _create_new_question(question_data: dict, author: User, topic: Topic) -> Question:
    """Creates a new Question instance for manual addition."""

    return Question.objects.create(
        question_text=question_data.get("question_text"),
        difficulty=question_data.get("difficulty_snapshot"),
        topic=topic,
        question_author=author,
        source=Question.QuestionSource.MANUAL,
    )


@transaction.atomic
def add_question_to_topic(
    form_topic: WorkingFormTopic, user: User, question_data: dict
) -> WorkingFormItem:
    """
    Adds a question to a specific topic using helper functions.
    """

    origin_question_id = question_data.get("origin_question")

    if (
        origin_question_id
        and form_topic.items.filter(origin_question_id=origin_question_id).exists()
    ):
        raise ValidationError(
            f"Question with origin_id '{origin_question_id}' is already in this topic."
        )

    if origin_question_id:
        origin_question = _get_existing_question(origin_question_id)
    else:
        origin_question = _create_new_question(question_data, user, form_topic.topic)

    new_item = WorkingFormItem.objects.create(
        form_topic=form_topic,
        added_by=user,
        origin_question=origin_question,
        text_snapshot=origin_question.question_text,
        difficulty_snapshot=origin_question.difficulty,
        topic_snapshot=origin_question.topic.name,
        source_snapshot=origin_question.source,
        max_score_snapshot=origin_question.difficulty * 3,
    )
    return new_item


@transaction.atomic
def toggle_item_vote(item_id: int, user_id: int) -> dict:
    """Toggles a user's delete vote for a specific item and updates its is_removed status."""

    try:
        item = (
            WorkingFormItem.objects.select_related("form_topic__working_form")
            .annotate(
                annotated_delete_votes=Count("deleted_by", distinct=True),
                annotated_total_approvers=Count(
                    "form_topic__working_form__approvers", distinct=True
                ),
            )
            .get(pk=item_id)
        )
    except WorkingFormItem.DoesNotExist:
        raise ValidationError("Item not found.")

    # ✅ ЛОГУВАННЯ: Хто голосує
    print(f"toggle_item_vote called: item_id={item_id}, user_id={user_id}")

    # ✅ ЛОГУВАННЯ: Хто вже проголосував
    existing_voters = list(item.deleted_by.values_list("id", "email"))
    print(f"Current voters for item {item_id}: {existing_voters}")

    # Toggle vote
    user_already_voted = item.deleted_by.filter(pk=user_id).exists()
    print(f"User {user_id} already voted: {user_already_voted}")

    if user_already_voted:
        item.deleted_by.remove(user_id)
        print(f"REMOVED vote from user {user_id}")
        current_delete_votes = item.annotated_delete_votes - 1
    else:
        item.deleted_by.add(user_id)
        print(f"ADDED vote from user {user_id}")
        current_delete_votes = item.annotated_delete_votes + 1

    total_approvers = item.annotated_total_approvers
    print(f"After toggle: votes={current_delete_votes}, approvers={total_approvers}")

    should_be_removed = item._calculate_effective_deletion(
        total_approvers=total_approvers,
        delete_votes=current_delete_votes,
    )

    if item.is_removed != should_be_removed:
        item.is_removed = should_be_removed
        item.save(update_fields=["is_removed"])

    return {
        "item": item,
        "data_for_client": {
            "event": "item_state_updated",
            "item_id": item.id,
            "delete_votes": current_delete_votes,
            "total_approvers": total_approvers,
            "is_removed": item.is_removed,
        },
    }


@transaction.atomic
def toggle_topic_vote(form_id: int, topic_id: int, user_id: int) -> dict:
    """Toggles a user's delete vote for a specific topic and updates its is_removed status."""

    try:
        form_topic = WorkingFormTopic.objects.annotate(
            annotated_delete_votes=Count("deleted_by", distinct=True),
            annotated_total_approvers=Count("working_form__approvers", distinct=True),
        ).get(working_form_id=form_id, topic_id=topic_id)

    except WorkingFormTopic.DoesNotExist:
        raise ValidationError("Topic not found in this form.")

    if form_topic.deleted_by.filter(pk=user_id).exists():
        form_topic.deleted_by.remove(user_id)
        current_delete_votes = form_topic.annotated_delete_votes - 1
    else:
        form_topic.deleted_by.add(user_id)
        current_delete_votes = form_topic.annotated_delete_votes + 1

    total_approvers = form_topic.annotated_total_approvers

    should_be_removed = form_topic._calculate_effective_deletion(
        total_approvers=total_approvers,
        delete_votes=current_delete_votes,
    )

    if form_topic.is_removed != should_be_removed:
        form_topic.is_removed = should_be_removed
        form_topic.save(update_fields=["is_removed"])
        form_topic.items.update(is_removed=should_be_removed)

    return {
        "topic": form_topic,
        "data_for_client": {
            "event": "topic_state_updated",
            "topic_id": form_topic.id,
            "delete_votes": current_delete_votes,
            "total_approvers": total_approvers,
            "is_removed": form_topic.is_removed,
            "affected_item_ids": list(form_topic.items.values_list("id", flat=True)),
        },
    }


@transaction.atomic
def clone_working_to_evaluation(
    working_form: WorkingForm,
    candidate: Candidate,
    interview_datetime: timezone.datetime,
) -> EvaluationForm:
    """
    Creates a deep copy of an APPROVED WorkingForm into a new EvaluationForm instance.
    Args:
        working_form: The source WorkingForm instance.
        candidate: The Candidate instance.
        interview_datetime: The time and date of the interview.
    Returns:
        The newly created EvaluationForm instance.
    """

    if working_form.status != WorkingForm.Status.APPROVED:
        raise ValidationError(
            "Only APPROVED Working Forms can be used for evaluations."
        )

    formatted_datetime = interview_datetime.strftime("%d %b %Y, %H:%M")
    short_id = str(uuid.uuid4())[:8]

    name = f"Evaluation {working_form.level} {working_form.vacancy} - {candidate.full_name} ({formatted_datetime}) #{short_id}"
    base_slug = slugify(name)
    slug = base_slug
    counter = 1
    while EvaluationForm.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    evaluation_form = EvaluationForm.objects.create(
        working_form_origin=working_form,
        candidate=candidate,
        manager=working_form.manager,
        hiring_manager=working_form.hiring_manager,
        tech_stack=working_form.tech_stack,
        status=EvaluationForm.Status.PENDING,
        interview_datetime=interview_datetime,
        name=name,
        slug=slug,
        vacancy_snapshot=working_form.vacancy,
        level_snapshot=working_form.level,
        project_snapshot=working_form.project,
    )

    interviewers = working_form.interviewers.all()
    evaluation_form.interviewers.add(*interviewers)

    recruiters = working_form.recruiters.all()
    evaluation_form.recruiters.add(*recruiters)

    feedbacks_to_create = [
        EvaluationFeedback(evaluation_form=evaluation_form, interviewer=interviewer)
        for interviewer in interviewers
    ]

    EvaluationFeedback.objects.bulk_create(feedbacks_to_create)

    working_form_topics = working_form.form_topics.all()

    if not working_form_topics:
        evaluation_form.save()
        return evaluation_form

    topic_map = {
        tcp_frm.topic_id: EvaluationFormTopic(
            evaluation_form=evaluation_form,
            topic=tcp_frm.topic,
            topic_name_snapshot=tcp_frm.topic.name,
        )
        for tcp_frm in working_form_topics
    }

    EvaluationFormTopic.objects.bulk_create(topic_map.values())

    newly_created_topics = EvaluationFormTopic.objects.filter(
        evaluation_form=evaluation_form
    )
    topics_map_with_new_pks = {tpc.topic_id: tpc for tpc in newly_created_topics}

    items_to_create = []

    working_items = WorkingFormItem.objects.select_related(
        "added_by", "origin_question", "form_topic"
    ).filter(form_topic__working_form=working_form, is_removed=False)

    for item in working_items:
        new_form_topic = topics_map_with_new_pks.get(item.form_topic.topic_id)
        if not new_form_topic:
            continue

        items_to_create.append(
            EvaluationFormItem(
                form_topic=new_form_topic,
                origin_question=item.origin_question,
                text_snapshot=item.text_snapshot,
                difficulty_snapshot=item.difficulty_snapshot,
                source_snapshot=item.source_snapshot,
                max_score_snapshot=item.max_score_snapshot,
            )
        )

    if items_to_create:
        EvaluationFormItem.objects.bulk_create(items_to_create)

    return evaluation_form


@transaction.atomic
def clone_working_from_working(
    original_form: WorkingForm, validated_data: dict
) -> WorkingForm:
    """
    Create deep copy WorkingForm (from 'original_form')
    but use new metadata (from 'validated_data').
    """

    interviewers = validated_data.pop("interviewers")
    approvers = validated_data.pop("approvers")
    recruiters = validated_data.pop("recruiters")
    hiring_manager = validated_data.pop("hiring_manager")

    vacancy = validated_data.get("vacancy")
    project = validated_data.get("project")
    level = validated_data.get("level")

    level_display = dict(WorkingForm.Level.choices).get(level, level.capitalize())
    short_id = str(uuid.uuid4())[:8]

    if project:
        name = f"Working {level_display} {vacancy} ({project}) #{short_id}"
    else:
        name = f"Working {level_display} {vacancy} #{short_id}"

    base_slug = slugify(name)
    slug = base_slug
    counter = 1
    while WorkingForm.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    new_form = WorkingForm.objects.create(
        template_origin=original_form.template_origin,
        manager=original_form.manager,
        tech_stack=original_form.tech_stack,
        hiring_manager=hiring_manager,
        name=name,
        slug=slug,
        status=WorkingForm.Status.IN_PROGRESS**validated_data,
    )

    new_form.interviewers.add(*interviewers)
    new_form.approvers.add(*approvers)
    new_form.recruiters.add(*recruiters)

    original_topics = original_form.form_topics.filter(is_removed=False)
    if not original_topics:
        return new_form

    topic_map = {
        tcp_frm.topic_id: WorkingFormTopic(working_form=new_form, topic=tcp_frm.topic)
        for tcp_frm in original_topics
    }

    WorkingFormTopic.objects.bulk_create(topic_map.values())

    newly_created_topics = WorkingFormTopic.objects.filter(working_form=new_form)
    topics_map_with_new_pks = {tpc.topic_id: tpc for tpc in newly_created_topics}

    items_to_create = []

    original_items = WorkingFormItem.objects.filter(
        form_topic__working_form=new_form, is_removed=False
    )

    for item in original_items:
        new_form_topic = topics_map_with_new_pks.get(item.form_topic.topic_id)
        if not new_form_topic:
            continue

        items_to_create.append(
            WorkingFormItem(
                form_topic=new_form_topic,
                added_by=item.added_by,
                origin_question=item.origin_question,
                text_snapshot=item.text_snapshot,
                difficulty_snapshot=item.difficulty_snapshot,
                source_snapshot=item.source_snapshot,
                topic_snapshot=item.topic_snapshot,
                max_score_snapshot=item.max_score_snapshot,
            )
        )

    if items_to_create:
        WorkingFormItem.objects.bulk_create(items_to_create)

    return new_form
