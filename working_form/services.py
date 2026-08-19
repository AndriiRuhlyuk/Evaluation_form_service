import uuid

from django.utils import timezone
from django.db import transaction
from django.db.models import Count
from django.utils.text import slugify

from evaluation_form.models import (
    Candidate,
    EvaluationForm,
    EvaluationFeedback,
    EvaluationFormTopic,
    EvaluationFormItem,
)
from employee.models import Employee
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

    This function either adds an existing topic or creates a new one based on
    the provided topic_data, then associates it with the working form. It ensures
    that the same topic isn't added twice to the same form.

    Args:
        working_form (WorkingForm): The working form to add the topic to
        topic_data (dict): Data containing either 'id' of an existing topic or 'name' for a new one

    Returns:
        WorkingFormTopic: The newly created WorkingFormTopic instance

    Raises:
        ValidationError: If the topic already exists in the working form
    """

    # Get or create the topic based on the provided data
    topic = _ensure_single_topic(
        topic_data
    )  # Helper function from template_form.services

    # Check if the topic is already in this working form
    if working_form.topics.filter(pk=topic.pk).exists():
        raise ValidationError(f"Topic '{topic.name}' is already in this working form.")

    # Create the association between the working form and the topic
    working_form_topic = WorkingFormTopic.objects.create(
        working_form=working_form,  # The working form to add the topic to
        topic=topic,  # The topic to add
    )

    return working_form_topic


def _get_existing_question(question_id: int) -> Question:
    """
    Fetches an existing question by ID.

    Helper function to retrieve a question by its ID, with appropriate error
    handling if the question doesn't exist.

    Args:
        question_id (int): The ID of the question to fetch

    Returns:
        Question: The question instance

    Raises:
        ValidationError: If no question with the given ID exists
    """

    try:
        return Question.objects.get(pk=question_id)  # Try to get the question
    except Question.DoesNotExist:
        # Raise a user-friendly validation error if the question doesn't exist
        raise ValidationError(f"Question with id={question_id} not found.")


def _create_new_question(
    question_data: dict, author: Employee, topic: Topic
) -> Question:
    """
    Creates a new Question instance for manual addition.

    Helper function to create a new question based on the provided data,
    setting the source to MANUAL to indicate it was manually added by an interviewer.

    Args:
        question_data (dict): Data containing 'question_text' and 'difficulty_snapshot'
        author (Employee): The employee who is creating the question
        topic (Topic): The topic the question belongs to

    Returns:
        Question: The newly created Question instance
    """

    return Question.objects.create(
        question_text=question_data.get("question_text"),  # The text of the question
        difficulty=question_data.get("difficulty_snapshot"),  # The difficulty level
        topic=topic,  # The topic the question belongs to
        question_author=author,  # The employee who created the question
        source=Question.QuestionSource.MANUAL,  # Source is MANUAL for interviewer-added questions
    )


@transaction.atomic
def add_question_to_topic(
    form_topic: WorkingFormTopic, user: Employee, question_data: dict
) -> WorkingFormItem:
    """
    Adds a question to a specific topic within a working form.

    This function handles two scenarios:
    1. Adding an existing question by its ID
    2. Creating a new question with provided text and difficulty

    In both cases, it creates a WorkingFormItem that contains a snapshot of
    the question's data at the time it was added to the form.

    Args:
        form_topic (WorkingFormTopic): The topic to add the question to
        user (Employee): The employee who is adding the question
        question_data (dict): Data containing either 'origin_question' ID or
                             'question_text' and 'difficulty_snapshot'

    Returns:
        WorkingFormItem: The newly created item

    Raises:
        ValidationError: If the question is already in this topic
    """

    origin_question_id = question_data.get(
        "origin_question"
    )  # ID of existing question, if any

    # Check if the question is already in this topic
    if (
        origin_question_id
        and form_topic.items.filter(origin_question_id=origin_question_id).exists()
    ):
        raise ValidationError(
            f"Question with origin_id '{origin_question_id}' is already in this topic."
        )

    # Get or create the question
    if origin_question_id:
        # Use existing question
        origin_question = _get_existing_question(origin_question_id)
    else:
        # Create new question
        origin_question = _create_new_question(question_data, user, form_topic.topic)

    # Create a new item with a snapshot of the question's current state
    new_item = WorkingFormItem.objects.create(
        form_topic=form_topic,  # The topic this item belongs to
        added_by=user,  # The user who added this item
        origin_question=origin_question,  # Reference to the original question
        text_snapshot=origin_question.question_text,  # Snapshot of question text
        difficulty_snapshot=origin_question.difficulty,  # Snapshot of difficulty
        topic_snapshot=origin_question.topic.name,  # Snapshot of topic name
        source_snapshot=origin_question.source,  # Snapshot of source
        max_score_snapshot=origin_question.max_score,  # Snapshot of max score
    )
    return new_item


@transaction.atomic
def toggle_item_vote(item_id: int, user_id: int) -> dict:
    """
    Toggles a user's delete vote for a specific item and updates its is_removed status.

    This function handles the voting process for deleting an item (question) from a
    working form. If the user has already voted, their vote is removed; otherwise,
    a new vote is added. The item's deletion status is then recalculated based on
    the updated vote count.

    Args:
        item_id (int): The ID of the item to toggle the vote for
        user_id (int): The ID of the user who is voting

    Returns:
        dict: A dictionary containing the updated item and data for client notification

    Raises:
        ValidationError: If the item with the given ID doesn't exist
    """

    try:
        # Get the item with annotations for vote counts and approver counts
        item = (
            WorkingFormItem.objects.select_related("form_topic__working_form")
            .annotate(
                annotated_delete_votes=Count(
                    "deleted_by", distinct=True
                ),  # Count of current deletion votes
                annotated_total_approvers=Count(
                    "form_topic__working_form__approvers", distinct=True
                ),  # Count of total approvers
            )
            .get(pk=item_id)
        )
    except WorkingFormItem.DoesNotExist:
        raise ValidationError("Item not found.")

    # Check if the user has already voted
    user_already_voted = item.deleted_by.filter(pk=user_id).exists()

    # Toggle the vote
    if user_already_voted:
        # Remove the vote if the user already voted
        item.deleted_by.remove(user_id)
        current_delete_votes = item.annotated_delete_votes - 1  # Decrement vote count
    else:
        # Add the vote if the user hasn't voted yet
        item.deleted_by.add(user_id)
        current_delete_votes = item.annotated_delete_votes + 1  # Increment vote count

    total_approvers = item.annotated_total_approvers  # Total number of approvers

    # Calculate if the item should be considered deleted based on vote threshold
    should_be_removed = item.calculate_effective_deletion(
        total_approvers=total_approvers,
        delete_votes=current_delete_votes,
    )

    # Update the item's removal status if it has changed
    if item.is_removed != should_be_removed:
        item.is_removed = should_be_removed
        item.save(update_fields=["is_removed"])  # Only update the is_removed field

    # Return the updated item and data for client notification
    return {
        "item": item,  # The updated item object
        "data_for_client": {
            "event": "item_state_updated",  # Event type for WebSocket
            "item_id": item.id,  # ID of the updated item
            "delete_votes": current_delete_votes,  # Current number of deletion votes
            "total_approvers": total_approvers,  # Total number of approvers
            "is_removed": item.is_removed,  # Whether the item is now removed
        },
    }


@transaction.atomic
def toggle_topic_vote(form_id: int, topic_id: int, user_id: int) -> dict:
    """
    Toggles a user's delete vote for a specific topic and updates its is_removed status.

    This function handles the voting process for deleting a topic from a working form.
    If the user has already voted, their vote is removed; otherwise, a new vote is added.
    The topic's deletion status is then recalculated based on the updated vote count.
    If the topic's removal status changes, all items within the topic are also updated.

    Args:
        form_id (int): The ID of the working form
        topic_id (int): The ID of the topic within the form
        user_id (int): The ID of the user who is voting

    Returns:
        dict: A dictionary containing the updated topic and data for client notification

    Raises:
        ValidationError: If the topic is not found in the specified form
    """

    try:
        # Get the topic with annotations for vote counts and approver counts
        form_topic = WorkingFormTopic.objects.annotate(
            annotated_delete_votes=Count(
                "deleted_by", distinct=True
            ),  # Count of current deletion votes
            annotated_total_approvers=Count(
                "working_form__approvers", distinct=True
            ),  # Count of total approvers
        ).get(working_form_id=form_id, topic_id=topic_id)

    except WorkingFormTopic.DoesNotExist:
        raise ValidationError("Topic not found in this form.")

    # Check if the user has already voted and toggle the vote
    if form_topic.deleted_by.filter(pk=user_id).exists():
        # Remove the vote if the user already voted
        form_topic.deleted_by.remove(user_id)
        current_delete_votes = (
            form_topic.annotated_delete_votes - 1
        )  # Decrement vote count
    else:
        # Add the vote if the user hasn't voted yet
        form_topic.deleted_by.add(user_id)
        current_delete_votes = (
            form_topic.annotated_delete_votes + 1
        )  # Increment vote count

    total_approvers = form_topic.annotated_total_approvers  # Total number of approvers

    # Calculate if the topic should be considered deleted based on vote threshold
    should_be_removed = form_topic.calculate_effective_deletion(
        total_approvers=total_approvers,
        delete_votes=current_delete_votes,
    )

    # Update the topic's removal status if it has changed
    if form_topic.is_removed != should_be_removed:
        form_topic.is_removed = should_be_removed
        form_topic.save(
            update_fields=["is_removed"]
        )  # Only update the is_removed field

        # Also update all items within this topic to match the topic's removal status
        WorkingFormItem.all_objects.filter(form_topic=form_topic).update(
            is_removed=should_be_removed
        )

    # Return the updated topic and data for client notification
    return {
        "topic": form_topic,  # The updated topic object
        "data_for_client": {
            "event": "topic_state_updated",  # Event type for WebSocket
            "topic_id": form_topic.id,  # ID of the updated topic
            "delete_votes": current_delete_votes,  # Current number of deletion votes
            "total_approvers": total_approvers,  # Total number of approvers
            "is_removed": form_topic.is_removed,  # Whether the topic is now removed
            "affected_item_ids": list(
                WorkingFormItem.all_objects.filter(form_topic=form_topic).values_list(
                    "id", flat=True
                )
            ),  # IDs of all items affected by this topic's status change
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

    This function converts a working form template into an actual evaluation form
    for a specific candidate. It copies all the form's structure (topics and questions)
    and creates feedback entries for each interviewer. The working form must be in
    APPROVED status to be used for evaluations.

    Args:
        working_form (WorkingForm): The source WorkingForm instance to clone
        candidate (Candidate): The candidate being evaluated
        interview_datetime (timezone.datetime): The scheduled time and date of the interview

    Returns:
        EvaluationForm: The newly created EvaluationForm instance

    Raises:
        ValidationError: If the working form is not in APPROVED status
    """

    # Verify the working form is approved
    if working_form.status != WorkingForm.Status.APPROVED:
        raise ValidationError(
            "Only APPROVED Working Forms can be used for evaluations."
        )

    # Format the datetime for display in the form name
    formatted_datetime = interview_datetime.strftime(
        "%d %b %Y, %H:%M"
    )  # Format: DD Mon YYYY, HH:MM
    short_id = str(uuid.uuid4())[:8]  # Generate a short unique ID

    # Create a name for the evaluation form
    name = f"Evaluation {working_form.level} {working_form.vacancy} - {candidate.full_name} ({formatted_datetime}) #{short_id}"

    # Create a slug for the URL, ensuring it's unique
    base_slug = slugify(name)  # Convert name to URL-friendly format
    slug = base_slug
    counter = 1
    # all_objects: a soft-deleted evaluation still reserves its slug
    while EvaluationForm.all_objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"  # Add counter to ensure uniqueness
        counter += 1

    # Create the evaluation form with metadata from the working form
    evaluation_form = EvaluationForm.objects.create(
        working_form_origin=working_form,  # Reference to the source working form
        candidate=candidate,  # The candidate being evaluated
        manager=working_form.manager,  # Copy the manager
        hiring_manager=working_form.hiring_manager,  # Copy the hiring manager
        tech_stack=working_form.tech_stack,  # Copy the tech stack
        status=EvaluationForm.Status.PENDING,  # Initial status is PENDING
        interview_datetime=interview_datetime,  # Scheduled interview time
        name=name,  # Form name
        slug=slug,  # URL slug
        vacancy_snapshot=working_form.vacancy,  # Snapshot of vacancy name
        level_snapshot=working_form.level,  # Snapshot of level
        project_snapshot=(
            working_form.project.name if working_form.project else ""
        ),  # Snapshot of project name
    )

    # Copy interviewers from the working form
    interviewers = working_form.interviewers.all()
    evaluation_form.interviewers.add(*interviewers)

    # Copy recruiters from the working form
    recruiters = working_form.recruiters.all()
    evaluation_form.recruiters.add(*recruiters)

    # Create feedback entries for each interviewer
    feedbacks_to_create = [
        EvaluationFeedback(evaluation_form=evaluation_form, interviewer=interviewer)
        for interviewer in interviewers
    ]
    EvaluationFeedback.objects.bulk_create(feedbacks_to_create)

    # Get all topics from the working form
    working_form_topics = working_form.form_topics.all()

    # If there are no topics, return the form as is
    if not working_form_topics:
        return evaluation_form

    # Create a mapping of topic IDs to new EvaluationFormTopic instances
    topic_map = {
        tcp_frm.topic_id: EvaluationFormTopic(
            evaluation_form=evaluation_form,  # The new evaluation form
            topic=tcp_frm.topic,  # Reference to the original topic
            topic_name_snapshot=tcp_frm.topic.name,  # Snapshot of topic name
        )
        for tcp_frm in working_form_topics
    }

    # Bulk create all the topic instances
    EvaluationFormTopic.objects.bulk_create(topic_map.values())

    # Get the newly created topics with their primary keys
    newly_created_topics = EvaluationFormTopic.objects.filter(
        evaluation_form=evaluation_form
    )
    topics_map_with_new_pks = {tpc.topic_id: tpc for tpc in newly_created_topics}

    # Prepare to create items (questions) for each topic
    items_to_create = []

    # Get all items from the working form
    working_items = WorkingFormItem.objects.select_related(
        "added_by", "origin_question", "form_topic"
    ).filter(form_topic__working_form=working_form)

    # For each item in the working form, create a corresponding item in the evaluation form
    for item in working_items:
        new_form_topic = topics_map_with_new_pks.get(item.form_topic.topic_id)
        if not new_form_topic:
            continue  # Skip if the topic wasn't created

        # Create a new evaluation form item with snapshots of the original item's data
        items_to_create.append(
            EvaluationFormItem(
                form_topic=new_form_topic,  # The new topic this item belongs to
                origin_question=item.origin_question,  # Reference to the original question
                text_snapshot=item.text_snapshot,  # Snapshot of question text
                difficulty_snapshot=item.difficulty_snapshot,  # Snapshot of difficulty
                topic_snapshot=item.topic_snapshot,  # Snapshot of topic name
                source_snapshot=item.source_snapshot,  # Snapshot of source
                max_score_snapshot=item.max_score_snapshot,  # Snapshot of max score
            )
        )

    # Bulk create all the item instances
    if items_to_create:
        EvaluationFormItem.objects.bulk_create(items_to_create)

    return evaluation_form


@transaction.atomic
def clone_working_from_working(
    original_form: WorkingForm, validated_data: dict
) -> WorkingForm:
    """
    Creates a deep copy of an existing WorkingForm with new metadata.

    This function clones an existing working form but updates its metadata
    (vacancy, level, project, etc.) with new values from validated_data.
    It copies the structure (topics and questions) from the original form
    but assigns new users (interviewers, approvers, recruiters) and sets
    the status to IN_PROGRESS.

    Args:
        original_form (WorkingForm): The source WorkingForm to clone
        validated_data (dict): New metadata for the cloned form, including
                              'interviewers', 'approvers', 'recruiters',
                              'hiring_manager', 'vacancy', 'level', 'project'

    Returns:
        WorkingForm: The newly created WorkingForm instance
    """

    # Extract user lists from validated data
    interviewers = validated_data.pop("interviewers")  # List of interviewer objects
    approvers = validated_data.pop("approvers")  # List of approver objects
    recruiters = validated_data.pop("recruiters")  # List of recruiter objects
    hiring_manager = validated_data.pop("hiring_manager")  # Hiring manager object

    # Extract key metadata for generating name and slug
    vacancy = validated_data.get("vacancy")  # Vacancy name
    project = validated_data.get("project")  # Project object
    level = validated_data.get("level")  # Seniority level

    # Generate a unique name and slug for the new form
    name, slug = WorkingForm.generate_name_and_slug(
        level, vacancy, project, timezone.now()
    )

    # Create the new form with metadata from original form and validated_data
    new_form = WorkingForm.objects.create(
        template_origin=original_form.template_origin,  # Keep the same template origin
        manager=original_form.manager,  # Keep the same manager
        tech_stack=original_form.tech_stack,  # Keep the same tech stack
        hiring_manager=hiring_manager,  # Use new hiring manager
        name=name,  # Use generated name
        slug=slug,  # Use generated slug
        status=WorkingForm.Status.IN_PROGRESS,  # Always start as IN_PROGRESS
        **validated_data,  # Include remaining validated data
    )

    # Add the new users to the form
    new_form.interviewers.add(*interviewers)  # Add interviewers
    new_form.approvers.add(*approvers)  # Add approvers
    new_form.recruiters.add(*recruiters)  # Add recruiters

    # Get all non-removed topics from the original form
    original_topics = original_form.form_topics.filter(is_removed=False)
    if not original_topics:
        return new_form  # Return early if there are no topics to copy

    # Create a mapping of topic IDs to new WorkingFormTopic instances
    topic_map = {
        tcp_frm.topic_id: WorkingFormTopic(working_form=new_form, topic=tcp_frm.topic)
        for tcp_frm in original_topics
    }

    # Bulk create all the topic instances
    WorkingFormTopic.objects.bulk_create(topic_map.values())

    # Get the newly created topics with their primary keys
    newly_created_topics = WorkingFormTopic.objects.filter(working_form=new_form)
    topics_map_with_new_pks = {tpc.topic_id: tpc for tpc in newly_created_topics}

    # Prepare to create items (questions) for each topic
    items_to_create = []

    # Get all items from the original form
    original_items = WorkingFormItem.objects.filter(
        form_topic__working_form=original_form
    )

    # For each item in the original form, create a corresponding item in the new form
    for item in original_items:
        new_form_topic = topics_map_with_new_pks.get(item.form_topic.topic_id)
        if not new_form_topic:
            continue  # Skip if the topic wasn't created

        # Create a new working form item with the same data as the original
        items_to_create.append(
            WorkingFormItem(
                form_topic=new_form_topic,  # The new topic this item belongs to
                added_by=item.added_by,  # Keep the same added_by user
                origin_question=item.origin_question,  # Keep the same origin question
                text_snapshot=item.text_snapshot,  # Keep the same text
                difficulty_snapshot=item.difficulty_snapshot,  # Keep the same difficulty
                source_snapshot=item.source_snapshot,  # Keep the same source
                topic_snapshot=item.topic_snapshot,  # Keep the same topic snapshot
                max_score_snapshot=item.max_score_snapshot,  # Keep the same max score
            )
        )

    # Bulk create all the item instances
    if items_to_create:
        WorkingFormItem.objects.bulk_create(items_to_create)

    return new_form
