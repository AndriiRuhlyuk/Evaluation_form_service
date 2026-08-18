from types import SimpleNamespace
from typing import Any

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from question.models import Question
from rest_framework import serializers
from techstack.models import TechStack
from django.contrib.auth.models import User
from template_form.models import TemplateForm, TemplateFormItems, TemplateFormTopic
from topic.models import Topic
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem

# List of fields that store snapshot data from the original question
# These fields are used for bulk updates and to track what fields should be copied
# from the original question to maintain historical accuracy
SNAPSHOT_FIELDS = [
    "text_snapshot",  # Stores the text of the question
    "difficulty_snapshot",  # Stores the difficulty level of the question
    "max_score_snapshot",  # Stores the maximum score possible for the question
    "topic_snapshot",  # Stores the name of the topic the question belongs to
    "source_snapshot",  # Stores the source of the question (e.g., TEMPLATE)
]


def _ensure_tech_stacks(tech_stack_data):
    """
    Finds an existing `TechStack` instance or creates a new one.

    This utility function provides flexibility in how technology stacks can be
    referenced in the API. It handles multiple input formats and ensures that a
    valid TechStack instance is always returned, creating one if necessary.

    The function is flexible and accepts technology stack data in multiple formats:
    - A `TechStack` model instance: returned as-is
    - A dictionary with a `name` key: finds or creates a TechStack with that name
    - A string (the stack name): finds or creates a TechStack with that name
    - A numeric ID: looks up the TechStack by primary key

    Args:
        tech_stack_data (Any): Data used to identify the technology stack.
            Can be a TechStack instance, dict, string, or numeric ID.

    Returns:
        TechStack: A valid `TechStack` model instance that can be used in relationships.

    Raises:
        serializers.ValidationError: If an invalid identifier is provided or if
            the TechStack with the given ID doesn't exist.
    """
    # Case 1: Already a TechStack instance - return it directly
    if isinstance(tech_stack_data, TechStack):
        return tech_stack_data

    # Case 2: Dictionary with name (and optional description)
    if isinstance(tech_stack_data, dict):
        # Get or create the tech stack with the given name
        tech_stack, created = TechStack.objects.get_or_create(
            name=tech_stack_data.get("name"),
            defaults={"description": tech_stack_data.get("description", "")},
        )
        return tech_stack

    # Case 3: String (tech stack name)
    if isinstance(tech_stack_data, str):
        # Get or create the tech stack with the given name
        tech_stack, created = TechStack.objects.get_or_create(
            name=tech_stack_data,
        )
        return tech_stack

    # Case 4: Numeric ID - try to find the tech stack by primary key
    try:
        return TechStack.objects.get(pk=tech_stack_data)
    except (TechStack.DoesNotExist, TypeError, ValueError):
        # Raise validation error if the ID is invalid or the tech stack doesn't exist
        raise serializers.ValidationError(
            f"Invalid identifier for TechStack: {tech_stack_data}"
        )


def _ensure_single_topic(topic_data: dict) -> Topic:
    """
    Finds a `Topic` by ID or name, or creates a new one if it does not exist.

    This helper function resolves a topic reference from input data, supporting
    two ways to identify a topic:
    1. By ID: Looks up an existing topic with the given ID
    2. By name: Finds or creates a topic with the given name

    The function is used during form creation and updates to ensure that all
    topic references are resolved to valid Topic instances.

    Args:
        topic_data (dict): A dictionary containing either:
            - 'id': The primary key of an existing topic
            - 'name': The name of a topic (will be created if it doesn't exist)

    Returns:
        Topic: A valid `Topic` model instance that can be used in relationships.

    Raises:
        serializers.ValidationError: If:
            - A topic with the specified ID is not found
            - The dictionary contains neither 'id' nor 'name'
            - The input data is invalid
    """
    # Extract topic identifier from the input data
    topic_id = topic_data.get("id")  # ID of an existing topic
    topic_name = topic_data.get("name")  # Name to find or create a topic

    # Case 1: Topic identified by ID
    if topic_id:
        try:
            # Try to find the topic with the given ID
            return Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            # Topic with the given ID doesn't exist
            raise serializers.ValidationError(f"Topic with id={topic_id} not found.")

    # Case 2: Topic identified by name
    if topic_name:
        # Find or create a topic with the given name
        topic, _ = Topic.objects.get_or_create(name=topic_name)
        return topic

    # Case 3: No valid identifier provided
    raise serializers.ValidationError("Topic data must contain 'id' or 'name'.")


def _get_or_create_questions(
    items_data: list, user: User, topic_obj: Topic
) -> dict[int, Question]:
    """
    Processes a list of questions: retrieves existing ones and prepares new ones for creation.

    This function handles two scenarios for each question in the input data:
    1. Existing questions: Identified by 'origin_question' ID, retrieved from the database
    2. New questions: Created on-the-fly based on provided text and difficulty

    The function uses bulk operations for efficiency when creating new questions.
    It maintains the original ordering of questions by mapping each question to its
    original index in the input list.

    Args:
        - items_data (list): A list of dictionaries describing the questions. Each dictionary
                           can contain either:
                           - 'origin_question': ID of an existing question
                           - 'question_text' and 'difficulty': Data for creating a new question
        - user (User): The user who will be set as the author of new questions.
        - topic_obj (Topic): The topic with which new questions will be associated.

    Returns:
        - dict[int, Question]: A dictionary where:
                             - key: The index of the question in the input list
                             - value: The corresponding Question model instance
                             This preserves the original ordering from the input data.
    """
    # Lists to track new questions to be created
    new_questions_to_create = []  # Holds Question objects to be bulk created
    item_indices_for_new_questions = []  # Tracks original indices for new questions

    # Lists to track existing questions to be retrieved
    existing_question_ids = []  # IDs of existing questions to fetch
    item_indices_for_existing_questions = {}  # Maps question IDs to original indices

    # Process each item in the input data
    for index, item in enumerate(items_data):
        # Case 1: Existing question identified by ID
        if "origin_question" in item:
            q_id = item["origin_question"]
            existing_question_ids.append(q_id)
            item_indices_for_existing_questions[q_id] = index
        # Case 2: New question to be created
        else:
            # Create a new Question instance (not yet saved to database)
            new_questions_to_create.append(
                Question(
                    question_text=item["question_text"],  # Text of the question
                    difficulty=item["difficulty"],  # Difficulty level
                    topic=topic_obj,  # Associated topic
                    question_author=user,  # User who created it
                    source=Question.QuestionSource.TEMPLATE,  # Source type
                )
            )
            item_indices_for_new_questions.append(index)

    # Final mapping of original indices to Question objects
    final_questions_map = {}

    # Bulk create new questions if any exist
    if new_questions_to_create:
        created_questions = Question.objects.bulk_create(new_questions_to_create)
        # Map each created question back to its original index
        for index, question in enumerate(created_questions):
            original_item_index = item_indices_for_new_questions[index]
            final_questions_map[original_item_index] = question

    # Retrieve existing questions if any were referenced
    if existing_question_ids:
        existing_questions = Question.objects.filter(id__in=existing_question_ids)
        # Map each existing question back to its original index
        for question in existing_questions:
            original_item_index = item_indices_for_existing_questions[question.id]
            final_questions_map[original_item_index] = question

    return final_questions_map


def populate_snapshot_from_question(snapshot: TemplateFormItems, user=None) -> None:
    """
    Populates snapshot fields with data from the original question.

    This function implements the "snapshot" concept, which is a key feature of the
    form system. It copies data from the original question to create a point-in-time
    record that won't change even if the original question is later modified.

    The function copies the following data:
    - Text of the question
    - Difficulty level
    - Source information
    - Maximum score (calculated from difficulty)
    - Topic name
    - User who added the question to the form

    This denormalization ensures that forms maintain historical accuracy and
    consistency over time, regardless of changes to the original questions.

    Args:
        - snapshot (TemplateFormItems): The snapshot instance to be populated with data.
        - user (User, optional): The user who added the item to the form. Defaults to None.
    """
    # Copy data from the original question if it exists
    if snapshot.origin_question:
        # Copy the question text
        snapshot.text_snapshot = snapshot.origin_question.question_text

        # Copy the difficulty level
        snapshot.difficulty_snapshot = snapshot.origin_question.difficulty

        # Copy the source information (e.g., TEMPLATE, CUSTOM)
        snapshot.source_snapshot = snapshot.origin_question.source

        # Calculate and copy the maximum score based on difficulty
        snapshot.max_score_snapshot = (
            snapshot.origin_question.max_score
            if snapshot.origin_question.difficulty
            else None
        )

    # Copy the topic name from the form topic
    if snapshot.form_topic and snapshot.form_topic.topic:
        snapshot.topic_snapshot = snapshot.form_topic.topic.name

    # Set the user who added this question to the form
    if user:
        snapshot.added_by = user


def _create_snapshots(
    form_topic: TemplateFormTopic, user: User, all_questions_map: dict[int, Question]
):
    """
    Creates snapshot instances (`TemplateFormItems`) for a set of questions.

    This function is responsible for creating the actual snapshot records in the database.
    It takes a mapping of questions (from _get_or_create_questions) and creates a
    TemplateFormItems instance for each one, linking it to the specified form topic.

    The function uses bulk creation for efficiency when creating multiple snapshots.
    Each snapshot is populated with data from its original question using the
    populate_snapshot_from_question helper function.

    Args:
        - form_topic (TemplateFormTopic): The object linking the form and the topic.
            This establishes where in the form structure these questions belong.
        - user (User): The user adding the questions, who will be recorded as the
            creator of these snapshots.
        - all_questions_map (dict[int, Question]): A dictionary mapping original indices
            to Question objects that should be added to the form.
    """
    # List to collect all snapshots before bulk creation
    snapshots_to_create = []

    # Create a snapshot for each question in the map
    for item_index, origin_question in all_questions_map.items():
        # Create a new TemplateFormItems instance (snapshot)
        snapshot = TemplateFormItems(
            form_topic=form_topic,  # Link to the form topic
            origin_question=origin_question,  # Link to the original question
        )

        # Populate the snapshot with data from the original question
        populate_snapshot_from_question(snapshot, user)

        # Add to the list for bulk creation
        snapshots_to_create.append(snapshot)

    # Bulk create all snapshots if any exist
    if snapshots_to_create:
        TemplateFormItems.objects.bulk_create(snapshots_to_create)


def process_topics_and_questions(form: TemplateForm, user: User, topic_data: list):
    """
    Orchestrates the process of creating topics and questions for a form.

    This is a high-level coordinator function that manages the entire workflow of
    adding topics and questions to a form template. It handles the complex process of:
    1. Resolving or creating topics
    2. Establishing form-topic relationships
    3. Processing question data (both existing and new questions)
    4. Creating snapshots of questions within the form

    The function expects a nested data structure where each topic has an associated
    list of questions, and processes each topic-questions group independently.

    Args:
        - form (TemplateForm): The form template instance to which topics and questions
                             will be added.
        - user (User): The user performing the operation, who will be recorded as the
                     creator of new questions and snapshots.
        - topic_data (list): A list of dictionaries, each describing a topic-questions group
                           in the format:
                           ```
                           {
                               'topic': {'id': 123} or {'name': 'Topic Name'},
                               'questions': [
                                   {'origin_question': 456} or
                                   {'question_text': 'Question?', 'difficulty': 2}
                               ]
                           }
                           ```
    """
    # If no topic data provided, nothing to process
    if not topic_data:
        return

    # Process each topic-questions group
    for topic_group in topic_data:
        # Step 1: Resolve or create the topic
        topic_obj = _ensure_single_topic(topic_group["topic"])

        # Step 2: Create or get the form-topic relationship
        form_topic, created = TemplateFormTopic.objects.get_or_create(
            form=form, topic=topic_obj
        )

        # Get the list of questions for this topic
        questions_data = topic_group["questions"]

        # Step 3: Process the questions (get existing ones or create new ones)
        all_questions_map = _get_or_create_questions(questions_data, user, topic_obj)

        # Step 4: Create snapshots for all questions in this topic
        _create_snapshots(form_topic, user, all_questions_map)


def _synchronize_form_topics(form: TemplateForm):
    """
    Synchronizes the `form.topics` many-to-many relationship with topics
    that have active questions.

    This maintenance function ensures that the form's topics list accurately
    reflects the topics that actually have active questions in the form. It's
    called after operations that might change the set of active questions
    (like adding, removing, or updating questions).

    The synchronization process:
    1. Finds all active items (not soft-deleted) in the form
    2. Extracts the unique set of topic IDs these items belong to
    3. Updates the form's topics many-to-many relationship to match this set

    This keeps the form.topics field in sync with reality, which is important
    for proper filtering and querying of forms by topic.

    Args:
        form (TemplateForm): The form instance whose topics need to be synchronized
    """
    # Get all topic IDs that have active questions in this form
    # An active question is one where is_removed=False
    active_topic_ids = set(
        TemplateFormItems.objects.filter(form_topic__form=form, is_removed=False)
        .values_list("origin_question__topic_id", flat=True)
        .distinct()
    )

    # Remove None values (questions without a topic)
    active_topic_ids.discard(None)

    # Update the form's topics to match the active topics
    # This replaces the existing set of topics with the new set
    form.topics.set(active_topic_ids)


@transaction.atomic
def create_template_form(manager: User, validated_data: dict) -> TemplateForm:
    """
    Creates a `TemplateForm` instance along with all nested objects.

    This is the main entry point for creating a new form template through the API.
    It handles the entire creation process in a single database transaction to
    ensure data consistency. If any part of the process fails, all changes are
    rolled back.

    The function performs these steps:
    1. Extracts nested data (topics and questions) from the input
    2. Resolves or creates the technology stack
    3. Creates the main TemplateForm instance
    4. Processes all topics and questions, creating necessary relationships
    5. Synchronizes the form's topics list to match active questions

    This function is typically called from the TemplateFormSerializer's create method.

    Args:
        - manager (User): The user who creates the form and becomes its manager.
            This user will be recorded as the owner of the form.
        - validated_data (dict): Validated data from the serializer, containing:
            - name: The name of the form
            - tech_stack: Technology stack data (can be ID, name, or dict)
            - topics_with_questions: Nested data structure with topics and questions

    Returns:
        TemplateForm: The newly created form template instance with all relationships
                    established.
    """
    # Extract nested data for topics and questions
    topics_data = validated_data.pop("topics_with_questions", [])

    # Resolve or create the technology stack
    tech_stack = _ensure_tech_stacks(validated_data.pop("tech_stack"))

    # Create the main form template instance
    template_form = TemplateForm.objects.create(
        manager=manager,  # Set the current user as the manager
        tech_stack=tech_stack,  # Link to the technology stack
        **validated_data,  # Include other fields like name
    )

    # Process all topics and questions
    process_topics_and_questions(template_form, manager, topics_data)

    # Synchronize the form's topics list to match active questions
    _synchronize_form_topics(template_form)

    return template_form


def _deactivate_removed_items(
    instance: TemplateForm, incoming_question_ids: set[int]
) -> None:
    """
    Finds items that are missing from the input data and marks them as removed.

    This function implements the "soft deletion" mechanism for questions in a form.
    Rather than permanently deleting questions that are no longer included in an
    update, it marks them as removed (is_removed=True) to preserve the history.

    The function works by:
    1. Finding all currently active questions in the form
    2. Comparing them with the list of questions in the update request
    3. Identifying questions that were previously active but are now missing
    4. Marking those questions as removed (soft deletion)

    This approach ensures that form history is preserved while still allowing
    questions to be effectively removed from the active view of the form.

    Args:
        - instance (TemplateForm): The form instance being updated.
        - incoming_question_ids (set[int]): The set of question IDs included in the
            update request. Questions not in this set will be marked as removed.
    """
    # Get all currently active question IDs in the form
    existing_active_ids = set(
        TemplateFormItems.objects.filter(
            form_topic__form=instance, is_removed=False
        ).values_list("origin_question_id", flat=True)
    )

    # Find questions that exist in the form but are not in the incoming data
    # These are the questions that need to be marked as removed
    ids_to_deactivate = existing_active_ids - incoming_question_ids

    # Perform a bulk update to mark these questions as removed
    # This is more efficient than updating each question individually
    TemplateFormItems.objects.filter(
        form_topic__form=instance, origin_question_id__in=ids_to_deactivate
    ).update(is_removed=True)


def _reactivate_or_identify_new_items(
    topics_data: list[dict[str, Any]],
    existing_items_map: dict[int, TemplateFormItems],
) -> tuple[list[int], list[dict[str, Any]]]:
    """
    Analyzes the input data to split questions into two groups: reactivation and new.

    Iterates over the input data and evaluates each question:
    1. If an item with the same question already exists in the form and is marked
       as removed (`is_removed=True`), its ID is added to the reactivation list.
    2. If no item with the given question exists in the form, its data is added
       to the list of new items for further processing.

    Args:
        - topics_data (list): A list of "topic–questions" groups from the input request.
        - existing_items_map (dict): A mapping of question IDs to existing
                                   `TemplateFormItems` instances.

    Returns:
        tuple[list[int], list[dict[str, Any]]]: A tuple containing:
            - A list of item IDs to be reactivated.
            - A list of data for entirely new questions, grouped by topics.
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
    Processes a list of new questions to be added to the form.

    If the `new_topic_groups` list is not empty, delegates their creation
    to the main `process_topics_and_questions` function.

    Args:
        - instance (TemplateForm): The form instance being updated.
        - manager (User): The user performing the operation.
        - new_topic_groups (list): A list of new questions grouped by topics.
    """
    if new_topic_groups:
        process_topics_and_questions(instance, manager, new_topic_groups)


@transaction.atomic
def update_template_form(
    instance: TemplateForm,
    manager: User,
    validated_data: dict,
) -> TemplateForm:
    """
    Updates a `TemplateForm` and its nested objects using a "soft replacement" strategy.

    This orchestrator performs the following steps within a single transaction:
    1. Updates the form’s simple fields (`name`, `tech_stack`).
    2. Deactivates items that were removed from the form (`_deactivate_removed_items`).
    3. Determines which items should be reactivated and which are new
       (`_reactivate_or_identify_new_items`).
    4. Reactivates previously removed items (sets `is_removed=False`).
    5. Creates entirely new items (`_process_newly_added_items`).
    6. Synchronizes the `topics` many-to-many relationship with the current set of topics.

    Args:
        - instance (TemplateForm): The form instance to be updated.
        - manager (User): The user performing the update.
        - validated_data (dict): Validated data from the serializer.

    Returns:
        TemplateForm: The updated form template instance.
    """

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


def save_template_draft(instance: TemplateForm, draft_data: dict) -> TemplateForm:
    """
    Saves form JSON data as a draft without validation.

    This function writes the provided `draft_data` dictionary to the `draft_data`
    field, sets the `has_unpublished_changes` flag to `True`, and updates the
    last-modified timestamp draft.

    Args:
        - instance (TemplateForm): The form instance for which the draft is saved.
        - draft_data (dict): A JSON-compatible dictionary containing form data
                           from the frontend.

    Returns:
        TemplateForm: The updated form instance with the saved draft.
    """
    instance.draft_data = draft_data
    instance.has_unpublished_changes = True
    instance.draft_updated_at = timezone.now()
    instance.save(
        update_fields=["draft_data", "has_unpublished_changes", "draft_updated_at"]
    )
    return instance


@transaction.atomic
def publish_template_form(instance: TemplateForm, manager: User) -> TemplateForm:
    """
    Publishes draft changes by applying them to the main form.

    The function validates the data from the `draft_data` field using the
    `TemplateFormSerializer`. If validation succeeds, it calls
    `update_template_form` to apply the changes. After successful publishing,
    the draft fields are cleared.

    Args:
        instance (TemplateForm): The form instance with unpublished changes.
        manager (User): The user performing the publish operation.

    Returns:
        TemplateForm: The updated form instance.

    Raises:
        serializers.ValidationError: If the draft data is not valid.
    """
    if not instance.draft_data:
        return instance

    # Validate draft_data through serializer
    from template_form.serializers import TemplateFormSerializer

    serializer = TemplateFormSerializer(
        instance=instance,
        data=instance.draft_data,
        partial=True,
        context={"request": SimpleNamespace(user=manager)},
    )
    serializer.is_valid(raise_exception=True)

    # Apply validated data
    update_template_form(instance, manager, serializer.validated_data)

    # Clear draft after successful publishing
    instance.draft_data = None
    instance.has_unpublished_changes = False
    instance.draft_updated_at = None
    instance.save(
        update_fields=["draft_data", "has_unpublished_changes", "draft_updated_at"]
    )
    return instance


def get_question_details(request, pk):
    """
    Retrieves question data in JSON format for autofilling in the admin panel.

    Used for an AJAX request from the admin interface to automatically populate
    `_snapshot` fields in the form when an `origin_question` is selected.

    Args:
        - request: The HTTP request object.
        - pk (int): The ID of the `Question` instance.

    Returns:
        JsonResponse: A JSON response containing data for populating the fields.
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
    Creates a deep copy of a `TemplateForm` as a new `WorkingForm` instance.

    The process includes:
    1. Creating a new working form (`WorkingForm`) with attributes from `validated_data`.
    2. Copying base attributes (manager, tech stack) from the template.
    3. Generating a unique name and `slug`.
    4. Assigning interviewers, recruiters, and other participants.
    5. Creating copies of `TemplateFormTopic` as `WorkingFormTopic`.
    6. Creating copies of active `TemplateFormItems` as `WorkingFormItem`,
       preserving all `_snapshot` fields.

    Args:
        - template_form (TemplateForm): The template form instance to be cloned.
        - validated_data: A dictionary with validated data for the new WorkingForm
                   (e.g., {'vacancy': '...', 'level': '...', 'project': '...', 'interviewers': [...]}).
    Returns:
        WorkingForm: The newly created WorkingForm instance.
    """

    interviewers = validated_data.pop("interviewers", [])
    approvers = validated_data.pop("approvers", [])
    recruiters = validated_data.pop("recruiters")
    hiring_manager = validated_data.pop("hiring_manager")

    vacancy = validated_data.get("vacancy")
    project = validated_data.get("project")
    level = validated_data.get("level")

    name, slug = WorkingForm.generate_name_and_slug(
        level, vacancy, project, timezone.now()
    )

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
