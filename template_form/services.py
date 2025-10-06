from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from question.models import Question
from rest_framework import serializers
from techstack.models import TechStack
from django.contrib.auth.models import User
from template_form.models import TemplateForm, TemplateFormItems, FormTopic
from topic.models import Topic


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
    form_topic: FormTopic, user: User, all_questions_map: dict[int, Question]
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
        form_topic, created = FormTopic.objects.get_or_create(
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


@transaction.atomic
def update_template_form(
    instance: TemplateForm,
    manager: User,
    validated_data: dict,
) -> TemplateForm:
    """Update TemplateForm with all nested objects using 'soft replace' logic."""

    topics_data = validated_data.pop("topics_with_questions", None)
    instance.name = validated_data.get("name", instance.name)
    if "tech_stack" in validated_data:
        instance.tech_stack = _ensure_tech_stacks(validated_data["tech_stack"])
    instance.save()

    if topics_data is None:
        return instance

    incoming_question_ids = set()
    for topic_group in topics_data:
        for question_data in topic_group["questions"]:
            if "origin_question" in question_data:
                incoming_question_ids.add(question_data["origin_question"])

    existing_items = TemplateFormItems.objects.filter(
        form_topic__form=instance
    ).select_related("origin_question")
    existing_items_map = {
        item.origin_question.id: item for item in existing_items if item.origin_question
    }

    ids_to_deactivate = set(existing_items_map.keys()) - incoming_question_ids
    if ids_to_deactivate:
        instance.items.filter(origin_question_id__in=ids_to_deactivate).update(
            is_removed=True
        )

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

    if items_to_reactivate_ids:
        instance.form_topics.items.filter(id__in=items_to_reactivate_ids).update(
            is_removed=False
        )

    if new_topic_groups_to_process:
        process_topics_and_questions(instance, manager, new_topic_groups_to_process)

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
