from django.contrib.auth.models import User
from django.db import transaction

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
        item = WorkingFormItem.objects.get(pk=item_id)
    except WorkingFormItem.DoesNotExist:
        raise ValidationError("Item not found.")

    if item.deleted_by.filter(pk=user_id).exists():
        item.deleted_by.remove(user_id)
    else:
        item.deleted_by.add(user_id)

    should_be_removed = item.is_effectively_deleted
    if item.is_removed != should_be_removed:
        item.is_removed = should_be_removed
        item.save(update_fields=["is_removed"])

    return {
        "item": item,
        "data_for_client": {
            "event": "item_state_updated",
            "item_id": item.id,
            "delete_votes": item.deleted_by.count(),
            "total_approvers": item.form_topic.working_form.approvers.count(),
            "is_removed": item.is_removed,
        },
    }


@transaction.atomic
def toggle_topic_vote(form_id: int, topic_id: int, user_id: int) -> dict:
    """Toggles a user's delete vote for a specific topic and updates its is_removed status."""

    try:
        form_topic = WorkingFormTopic.objects.get(
            working_form_id=form_id, topic_id=topic_id
        )
    except WorkingFormTopic.DoesNotExist:
        raise ValidationError("Topic not found in this form.")

    if form_topic.deleted_by.filter(pk=user_id).exists():
        form_topic.deleted_by.remove(user_id)
    else:
        form_topic.deleted_by.add(user_id)

    should_be_removed = form_topic.is_effectively_deleted
    if form_topic.is_removed != should_be_removed:
        form_topic.is_removed = should_be_removed
        form_topic.save(update_fields=["is_removed"])
        form_topic.items.update(is_removed=should_be_removed)

    return {
        "topic": form_topic,
        "data_for_client": {
            "event": "topic_state_updated",
            "topic_id": form_topic.id,
            "delete_votes": form_topic.deleted_by.count(),
            "total_approvers": form_topic.working_form.approvers.count(),
            "is_removed": form_topic.is_removed,
            "affected_item_ids": [item.id for item in form_topic.items.all()],
        },
    }
