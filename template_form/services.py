import uuid
from typing import Any

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify

from question.models import Question
from rest_framework import serializers
from techstack.models import TechStack
from django.contrib.auth.models import User
from template_form.models import TemplateForm, TemplateFormItems, TemplateFormTopic
from topic.models import Topic
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem


def _ensure_tech_stacks(tech_stack_data):
    """
    Take or create TechStack and return instance.
    """
    if isinstance(tech_stack_data, TechStack):

        return tech_stack_data

    if isinstance(tech_stack_data, dict):
        tech_stack, created = TechStack.objects.get_or_create(
            name=tech_stack_data.get("name"),
            defaults={"description": tech_stack_data.get("description", "")},
        )

        return tech_stack

    if isinstance(tech_stack_data, str):
        tech_stack, created = TechStack.objects.get_or_create(
            name=tech_stack_data,
        )

        return tech_stack

    try:
        return TechStack.objects.get(pk=tech_stack_data)
    except (TechStack.DoesNotExist, TypeError, ValueError):
        raise serializers.ValidationError(
            f"Invalid identifier for TechStack: {tech_stack_data}"
        )


def _ensure_single_topic(topic_data: dict) -> Topic:
    """
    Find or create single topic
    """

    topic_id = topic_data.get("id")
    topic_name = topic_data.get("name")

    if topic_id:
        try:
            return Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            raise serializers.ValidationError(f"Topic with id={topic_id} not found.")

    if topic_name:
        topic, _ = Topic.objects.get_or_create(name=topic_name)
        return topic
    raise serializers.ValidationError("Topic data must contain 'id' or 'name'.")


def _get_or_create_questions(
    items_data: list, user: User, topic_obj: Topic
) -> dict[int, Question]:
    """
    Gets existing and creates new questions from `items_data`.
    :return: dict {index_in_items_data: QuestionObject} for ALL questions
    """
    new_questions_to_create = []
    item_indices_for_new_questions = []

    existing_question_ids = []
    item_indices_for_existing_questions = {}

    for index, item in enumerate(items_data):
        if "origin_question" in item:
            q_id = item["origin_question"]
            existing_question_ids.append(q_id)
            item_indices_for_existing_questions[q_id] = index

        else:
            new_questions_to_create.append(
                Question(
                    question_text=item["question_text"],
                    difficulty=item["difficulty"],
                    topic=topic_obj,
                    question_author=user,
                    source=Question.QuestionSource.TEMPLATE,
                )
            )
            item_indices_for_new_questions.append(index)

    final_questions_map = {}
    if new_questions_to_create:
        created_questions = Question.objects.bulk_create(new_questions_to_create)
        for index, question in enumerate(created_questions):
            original_item_index = item_indices_for_new_questions[index]
            final_questions_map[original_item_index] = question

    if existing_question_ids:
        existing_questions = Question.objects.filter(id__in=existing_question_ids)
        for question in existing_questions:
            original_item_index = item_indices_for_existing_questions[question.id]
            final_questions_map[original_item_index] = question

    return final_questions_map


def _create_snapshots(
    form_topic: TemplateFormTopic, user: User, all_questions_map: dict[int, Question]
):
    """
    Create instances TemplateFormItems (snapshots)
    """
    snapshots_to_create = []
    for item_index, origin_question in all_questions_map.items():
        max_score = (
            origin_question.difficulty * 3 if origin_question.difficulty else None
        )
        snapshots_to_create.append(
            TemplateFormItems(
                form_topic=form_topic,
                added_by=user,
                origin_question=origin_question,
                text_snapshot=origin_question.question_text,
                difficulty_snapshot=origin_question.difficulty,
                source_snapshot=origin_question.source,
                topic_snapshot=origin_question.topic.name,
                max_score_snapshot=max_score,
            )
        )
    if snapshots_to_create:
        TemplateFormItems.objects.bulk_create(snapshots_to_create)


def process_topics_and_questions(form: TemplateForm, user: User, topic_data: list):
    """
    An orchestrator that iterate by topics, and
    for every topic take question
    """
    if not topic_data:
        return

    for topic_group in topic_data:
        topic_obj = _ensure_single_topic(topic_group["topic"])
        form_topic, created = TemplateFormTopic.objects.get_or_create(
            form=form, topic=topic_obj
        )
        questions_data = topic_group["questions"]

        all_questions_map = _get_or_create_questions(questions_data, user, topic_obj)
        _create_snapshots(form_topic, user, all_questions_map)


def _synchronize_form_topics(form: TemplateForm):
    """
    Synchronizes the ManyToMany relationship between the form and the topics
    based on the active questions currently in the form.
    """

    active_topic_ids = set(
        TemplateFormItems.objects.filter(form_topic__form=form, is_removed=False)
        .values_list("origin_question__topic_id", flat=True)
        .distinct()
    )

    active_topic_ids.discard(None)

    form.topics.set(active_topic_ids)


@transaction.atomic
def create_template_form(manager: User, validated_data: dict) -> TemplateForm:
    """Create TemplateForm with all nested objects"""

    topics_data = validated_data.pop("topics_with_questions", [])
    tech_stack = _ensure_tech_stacks(validated_data.pop("tech_stack"))

    template_form = TemplateForm.objects.create(
        manager=manager, tech_stack=tech_stack, **validated_data
    )

    process_topics_and_questions(template_form, manager, topics_data)
    _synchronize_form_topics(template_form)

    return template_form


def _deactivate_removed_items(
    instance: TemplateForm, incoming_question_ids: set[int]
) -> None:
    """
    Finds questions that are no longer in the form data and marks them as removed.
    """
    existing_active_ids = set(
        instance.form_topics.items.filter(is_removed=False).values_list(
            "origin_question_id", flat=True
        )
    )
    ids_to_deactivate = existing_active_ids - incoming_question_ids

    if ids_to_deactivate:
        instance.form_topics.items.filter(
            origin_question_id__in=ids_to_deactivate
        ).update(is_removed=True)


def _reactivate_or_identify_new_items(
    topics_data: list[dict[str, Any]],
    existing_items_map: dict[int, TemplateFormItems],
) -> tuple[list[int], list[dict[str, Any]]]:
    """
    Analyzes incoming data to sort questions into two groups:
    1. Items to be reactivated.
    2. Completely new items to be processed.
    """

    items_to_reactivate_ids = []
    new_topic_groups_to_process = []

    for topic_group in topics_data:
        new_questions_for_this_topic = []
        for question_data in topic_group["questions"]:
            question_id = question_data.get("origin_question")

            if question_id and question_id in existing_items_map:
                existing_item = existing_items_map[question_id]
                if existing_item.is_removed:
                    items_to_reactivate_ids.append(existing_item.id)
            else:
                new_questions_for_this_topic.append(question_data)

        if new_questions_for_this_topic:
            new_topic_groups_to_process.append(
                {
                    "topic": topic_group["topic"],
                    "questions": new_questions_for_this_topic,
                }
            )
    return (items_to_reactivate_ids, new_topic_groups_to_process)


def _process_newly_added_items(
    instance: TemplateForm, manager: User, new_topic_groups: list[dict[str, Any]]
) -> None:
    """
    Takes the list of new questions grouped by topic and creates them in the database
    by delegating to the main processing function.
    """
    if new_topic_groups:
        process_topics_and_questions(instance, manager, new_topic_groups)


@transaction.atomic
def update_template_form(
    instance: TemplateForm,
    manager: User,
    validated_data: dict,
) -> TemplateForm:
    """Update TemplateForm with all nested objects using 'soft replace' logic."""

    instance.name = validated_data.get("name", instance.name)
    if "tech_stack" in validated_data:
        instance.tech_stack = _ensure_tech_stacks(validated_data["tech_stack"])
    instance.save()

    topics_data = validated_data.pop("topics_with_questions", None)

    if topics_data is None:
        return instance

    incoming_question_ids = {
        question_data["origin_question"]
        for topic_group in topics_data
        for question_data in topic_group["questions"]
        if "origin_question" in question_data
    }
    existing_items_map = {
        item.origin_question_id: item for item in instance.form_topics.items.all()
    }

    _deactivate_removed_items(instance, incoming_question_ids)

    items_to_reactivate_ids, new_topic_groups = _reactivate_or_identify_new_items(
        topics_data, existing_items_map
    )

    if items_to_reactivate_ids:
        instance.form_topics.items.filter(id__in=items_to_reactivate_ids).update(
            is_removed=False
        )

    _process_newly_added_items(instance, manager, new_topic_groups)

    _synchronize_form_topics(instance)

    return instance


def get_question_details(request, pk):
    """
    :return question data in JSON format for autofill in Admin Panel.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "Permission denied"}, status=403)

    question = get_object_or_404(Question, pk=pk)

    data = {
        "text_snapshot": question.question_text,
        "difficulty_snapshot": question.difficulty,
        "source_snapshot": question.source,
        "topic_snapshot": question.topic.name if question.topic else "",
        "max_score_snapshot": question.max_score,
    }
    return JsonResponse(data)


@transaction.atomic
def clone_template_to_working(
    template_form: TemplateForm, validated_data: dict
) -> WorkingForm:
    """
    Creates a deep copy of a TemplateForm into a new WorkingForm instance.

    Args:
        template_form: The source TemplateForm instance.
        validated_data: A dictionary with validated data for the new WorkingForm
                   (e.g., {'vacancy': '...', 'level': '...', 'project': '...', 'interviewers': [...]}).
    Returns:
        The newly created WorkingForm instance.
    """

    interviewers = validated_data.pop("interviewers", [])
    approvers = validated_data.pop("approvers", [])
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

    working_form = WorkingForm.objects.create(
        template_origin=template_form,
        manager=template_form.manager,
        tech_stack=template_form.tech_stack,
        hiring_manager=hiring_manager,
        name=name,
        slug=slug,
        **validated_data,
    )

    working_form.interviewers.add(*interviewers)
    working_form.approvers.add(*approvers)
    working_form.recruiters.add(*recruiters)

    template_form_topics = template_form.form_topics.all()
    if not template_form_topics:
        return working_form

    topic_map = {
        tpc_frm.topic_id: WorkingFormTopic(
            working_form=working_form, topic=tpc_frm.topic
        )
        for tpc_frm in template_form_topics
    }

    WorkingFormTopic.objects.bulk_create(topic_map.values())

    newly_created_topics = WorkingFormTopic.objects.filter(working_form=working_form)
    topics_map_with_new_pks = {tpc.topic_id: tpc for tpc in newly_created_topics}

    items_to_create = []

    template_items = TemplateFormItems.objects.select_related(
        "added_by", "origin_question", "form_topic"
    ).filter(form_topic__form=template_form, is_removed=False)

    for item in template_items:
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

    return working_form
