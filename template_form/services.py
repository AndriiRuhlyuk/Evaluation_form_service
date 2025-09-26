from django.db import transaction

from question.models import Question
from rest_framework import serializers
from techstack.models import TechStack
from django.contrib.auth.models import User
from template_form.models import TemplateForm, TemplateFormItems
from topic.models import Topic


def _ensure_tech_stacks(tech_stack_data):
    """
    Take or create TechStack
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


def _ensure_topics(items_data: list[dict]) -> dict[str, Topic]:
    """
    Take all topic names and create Topic instances.
    :return: dict {name: TopicObject}
    """
    topic_names = set()
    for item in items_data:
        topic_info = item.get("topic")
        if topic_info and topic_info.get("name"):
            topic_names.add(topic_info["name"])

    if not topic_names:
        return {}

    Topic.objects.bulk_create(
        [Topic(name=name) for name in topic_names], ignore_conflicts=True
    )
    topics_in_db = Topic.objects.filter(name__in=topic_names)
    return {topic.name: topic for topic in topics_in_db}


def _get_or_create_questions(
    items_data: list, user: User, topics_map: dict
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
            topic_name = item["topic"]["name"]
            topic_obj = topics_map.get(topic_name)
            if not topic_obj:
                raise serializers.ValidationError(
                    f"Could not find or create topic: {topic_name}"
                )

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
    form: TemplateForm, user: User, all_questions_map: dict[int, Question]
):
    """
    Create instances TemplateFormItems (snapshots)
    """
    snapshots_to_create = []
    for item_index, origin_question in all_questions_map.items():
        snapshots_to_create.append(
            TemplateFormItems(
                form=form,
                added_by=user,
                origin_question=origin_question,
                text_snapshot=origin_question.question_text,
                difficulty_snapshot=origin_question.difficulty,
                source_snapshot=origin_question.source,
                topic_snapshot=origin_question.topic.name,
                max_score_snapshot=origin_question.max_score,
            )
        )
    if snapshots_to_create:
        TemplateFormItems.objects.bulk_create(snapshots_to_create)


def _process_and_create_items(form: TemplateForm, user: User, items_data: list):
    """An orchestrator that calls all the helper functions to create nested objects."""
    if not items_data:
        return

    topics_map = _ensure_topics(items_data)
    all_questions_map = _get_or_create_questions(items_data, user, topics_map)
    _create_snapshots(form, user, all_questions_map)


def _synchronize_form_topics(form: TemplateForm):
    """
    Synchronizes the ManyToMany relationship between the form and the topics
    based on the active questions currently in the form.
    """

    active_topic_ids = set(
        TemplateFormItems.objects.filter(form=form, is_removed=False)
        .values_list("origin_question__topic_id", flat=True)
        .distinct()
    )

    active_topic_ids.discard(None)

    form.topics.set(active_topic_ids)


@transaction.atomic
def create_template_form(manager: User, validated_data: dict) -> TemplateForm:
    """Create TemplateForm with all nested objects"""

    items_data = validated_data.pop("items", [])

    tech_stack = _ensure_tech_stacks(validated_data.pop("tech_stack"))

    template_form = TemplateForm.objects.create(
        manager=manager, tech_stack=tech_stack, **validated_data
    )

    _process_and_create_items(template_form, manager, items_data)
    _synchronize_form_topics(template_form)

    return template_form


@transaction.atomic
def update_template_form(
    instance: TemplateForm,
    manager: User,
    validated_data: dict,
) -> TemplateForm:
    """Update TemplateForm with all nested objects using 'soft replace' logic."""

    items_data = validated_data.pop("items", None)
    instance.name = validated_data.get("name", instance.name)
    if "tech_stack" in validated_data:
        instance.tech_stack = _ensure_tech_stacks(validated_data["tech_stack"])
    instance.save()

    if items_data is None:
        return instance

    incoming_question_ids = {
        item["origin_question"] for item in items_data if "origin_question" in item
    }

    existing_items = instance.items.all().select_related("origin_question")
    # ВИПРАВЛЕНО: створюємо словник {question_id: item_object}
    existing_items_map = {
        item.origin_question.id: item for item in existing_items if item.origin_question
    }

    ids_to_deactivate = set(existing_items_map.keys()) - incoming_question_ids
    if ids_to_deactivate:
        instance.items.filter(origin_question_id__in=ids_to_deactivate).update(
            is_removed=True
        )

    new_items_to_process = []
    items_to_reactivate_ids = []

    for item_data in items_data:
        question_id = item_data.get("origin_question")

        if question_id in existing_items_map:
            existing_item = existing_items_map[question_id]
            if existing_item.is_removed:
                items_to_reactivate_ids.append(existing_item.id)
        else:
            new_items_to_process.append(item_data)

    if items_to_reactivate_ids:
        instance.items.filter(id__in=items_to_reactivate_ids).update(is_removed=False)

    if new_items_to_process:
        _process_and_create_items(instance, manager, new_items_to_process)

    _synchronize_form_topics(instance)

    return instance
