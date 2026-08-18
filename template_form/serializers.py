from django.urls import reverse
from rest_framework import serializers

from .models import TemplateForm, TemplateFormItems
from techstack.models import TechStack
from topic.models import Topic
from .services import (
    create_template_form,
    update_template_form,
    _ensure_tech_stacks,
)


class TopicSerializer(serializers.ModelSerializer):
    """
    A serializer for the `Topic` model.

    Intended for use as a nested serializer within `TemplateFormDetailSerializer`
    to represent basic topic information (ID and name) in the context of
    question grouping (get_topics_with_questions)
    """

    # id - Integer field representing the primary key of the Topic
    # Example: 1, 2, 3

    # name - String field representing the name of the Topic
    # Example: "ORM", "REST API", "Authentication"

    class Meta:
        model = Topic
        fields = ("id", "name")


class TechStackRelatedField(serializers.RelatedField):
    """
    A custom field for serializing the `TechStack` relationship.

    This field provides flexibility when working with a technology stack in the API,
    allowing the client to pass a `TechStack` in multiple formats:
    - As an ID (integer): "tech_stack": 1
    - As a string (name): "tech_stack": "Java"
    - As a dictionary with name: "tech_stack": {"name": "Java", "description": "..."}

    This flexibility makes the API more user-friendly by supporting different ways
    to reference technology stacks, and automatically creating new ones when needed.

    Methods:
        - to_internal_value: Converts input data to a TechStack instance by delegating
            to the `_ensure_tech_stacks` service function.
        - to_representation: Converts a TechStack instance to its string representation
            (the name) for API responses.
    """

    def to_internal_value(self, data):
        """
        Converts the provided data into a TechStack instance.

        This method handles the deserialization process, taking the raw input data
        from the API request and converting it to a valid TechStack instance that
        can be used in the model. It delegates the actual processing to the
        `_ensure_tech_stacks` service function, which handles all the logic for
        finding or creating TechStack instances.

        Args:
            data: The raw input data from the API request. Can be an ID, string, or dict.
                 Examples:
                 - Integer ID: 1
                 - String name: "Java"
                 - Dictionary: {"name": "Python", "description": "Python programming language"}

        Returns:
            TechStack: A valid TechStack model instance.
                      Example: TechStack(id=1, name="Java")

        Raises:
            ValidationError: If the data cannot be converted to a valid TechStack.
                            Example: ValidationError(["Tech stack not found and could not be created"])
        """
        # Delegate to the service function that handles all the logic
        # data - can be an ID (1), string ("Java"), or dict ({"name": "Python"})
        # Returns a TechStack instance like TechStack(id=1, name="Java")
        return _ensure_tech_stacks(data)

    def to_representation(self, value: TechStack):
        """
        Converts a TechStack instance to its string representation.

        This method handles the serialization process, taking a TechStack model
        instance and converting it to a simple string (the name) for the API response.
        This makes the API response cleaner and more readable.

        Args:
            value (TechStack): The TechStack model instance to be serialized.
                              Example: TechStack(id=1, name="Java")

        Returns:
            str: The name of the technology stack.
                Example: "Java"
        """
        # Return just the name of the tech stack for a clean API response
        # value - TechStack instance like TechStack(id=1, name="Java")
        # Returns a string like "Java"
        return value.name


class InputTopicSerializer(serializers.Serializer):
    """
    A serializer for validating input data of a topic.

    This serializer is used to validate the format of topic data in API requests.
    It ensures that a topic can be identified either by its ID (for existing topics)
    or by name (for new or existing topics). At least one of these fields must be
    provided.

    Used as a nested serializer within `TopicWithQuestionsInputSerializer`
    to validate the correctness of data identifying a topic.

    Fields:
        - id (IntegerField): Optional. The ID of an existing topic.
        - name (CharField): Optional. The name of a topic (will create if doesn't exist).
    """

    # ID of an existing topic (optional)
    # Example: 1, 2, 3
    id = serializers.IntegerField(required=False)

    # Name of a topic - can be used to find or create (optional)
    # Example: "ORM", "REST API", "Authentication"
    name = serializers.CharField(required=False)

    def validate(self, data):
        """
        Validates that either `id` or `name` is provided to identify the topic.

        This validation ensures that the API request contains enough information
        to identify a topic. At least one of the fields must be provided.

        Args:
            data (dict): The data to be validated
                        Example: {"id": 1} or {"name": "ORM"} or {"id": 1, "name": "ORM"}

        Returns:
            dict: The validated data
                 Example: {"id": 1} or {"name": "ORM"} or {"id": 1, "name": "ORM"}

        Raises:
            ValidationError: If neither 'id' nor 'name' is provided
                            Example: ValidationError(["Either 'id' or 'name' must be provided for a topic."])
        """
        # Check if at least one identifier is provided
        # data - Dictionary containing topic identification, like {"id": 1} or {"name": "ORM"}
        if not data.get("id") and not data.get("name"):
            raise serializers.ValidationError(
                "Either 'id' or 'name' must be provided for a topic."
            )
        return data


class InputTemplateFormItemSerializer(serializers.Serializer):
    """
    A serializer for validating input data of a form item (question).

    Used as a nested serializer within `TopicWithQuestionsInputSerializer`.
    It validates data for a single question, ensuring that either
    `origin_question` (the ID of an existing question) is provided,
    or a full set of data (`question_text`, `difficulty`) for creating
    a new question.
    """

    # ID of an existing question to reuse
    # Example: 42 (references TemplateFormItems with id=42)
    origin_question = serializers.IntegerField(required=False)

    # Text of the question if creating a new one
    # Example: "What is dependency injection?"
    question_text = serializers.CharField(required=False)

    # Difficulty level of the question (1=Easy, 2=Medium, 3=Hard)
    # Example: 2 (Medium difficulty)
    difficulty = serializers.IntegerField(required=False)

    def validate(self, data):
        """
        Validates the presence of data for either an existing or a new question.

        Args:
            data (dict): The data to be validated
                        Examples:
                        - Existing question: {"origin_question": 42}
                        - New question: {"question_text": "What is dependency injection?", "difficulty": 2}

        Returns:
            dict: The validated data
                 Examples: Same as input if valid

        Raises:
            ValidationError: If neither an existing question ID nor complete data for a new question is provided
                            Example: ValidationError(["Provide either 'origin_question' or full data for a new question."])
        """
        # Check if data contains reference to existing question
        # Example: data = {"origin_question": 42}
        is_existing = "origin_question" in data

        # Check if data contains all required fields for a new question
        # Example: data = {"question_text": "What is dependency injection?", "difficulty": 2}
        is_new = all(k in data for k in ["question_text", "difficulty"])

        if not is_existing and not is_new:
            raise serializers.ValidationError(
                "Provide either 'origin_question' or full data for a new question."
            )
        return data


class TopicWithQuestionsInputSerializer(serializers.Serializer):
    """
    A serializer for validating the nested "topic with questions" structure.

    This serializer defines the expected format for a single input data block
    that contains a topic object and a list of related questions.
    """

    # Topic object containing either id or name (or both)
    # Example: {"id": 1} or {"name": "ORM"}
    topic = InputTopicSerializer()

    # List of questions for this topic (at least one required)
    # Example: [
    #   {"origin_question": 42},
    #   {"question_text": "What is dependency injection?", "difficulty": 2}
    # ]
    questions = InputTemplateFormItemSerializer(many=True, min_length=1)


class TemplateFormSerializer(serializers.ModelSerializer):
    """
    Serializer for CREATE & UPDATE Template Form.

    This serializer serves as the primary entry point for manipulating form
    templates. It handles the complex nested `topics_with_questions` structure
    and delegates the business logic for creation and updates to the appropriate
    service functions (`create_template_form`, `update_template_form`)
    """

    # Nested structure of topics and their questions
    # Example: [
    #   {
    #     "topic": {"name": "ORM"},
    #     "questions": [
    #       {"origin_question": 42},
    #       {"question_text": "What is an ORM?", "difficulty": 1}
    #     ]
    #   }
    # ]
    topics_with_questions = TopicWithQuestionsInputSerializer(
        many=True, required=True, write_only=True
    )

    # Technology stack for this template form
    # Example: "Java" or 1 or {"name": "Python"}
    tech_stack = TechStackRelatedField(queryset=TechStack.objects.all())

    class Meta:
        model = TemplateForm
        # id - Integer primary key (Example: 1)
        # name - String name of the template (Example: "Java Developer Interview")
        # tech_stack - Technology stack (Example: "Java")
        # topics_with_questions - Nested structure of topics and questions
        fields = ("id", "name", "tech_stack", "topics_with_questions")

    def create(self, validated_data):
        """
        Handles the creation of a new `TemplateForm` instance.

        Delegates the creation process to the `create_template_form` service
        function, passing the validated data and the current user as the manager.

        Args:
            validated_data (dict): The validated data from the request
                                  Example: {
                                    "name": "Java Developer Interview",
                                    "tech_stack": <TechStack: Java>,
                                    "topics_with_questions": [...]
                                  }

        Returns:
            TemplateForm: The newly created template form instance
                         Example: TemplateForm(id=1, name="Java Developer Interview", ...)
        """
        # Get the current user from the request context to set as manager
        # Example: User(id=1, username="manager1")
        manager = self.context["request"].user

        # Call service function to handle the complex creation logic
        # Returns a new TemplateForm instance
        return create_template_form(manager=manager, validated_data=validated_data)

    def update(self, instance, validated_data):
        """
        Handles updating an existing `TemplateForm` instance.

        Delegates the update logic to the `update_template_form` service function.

        Args:
            instance (TemplateForm): The existing template form to update
                                    Example: TemplateForm(id=1, name="Java Developer Interview")
            validated_data (dict): The validated data from the request
                                  Example: {
                                    "name": "Updated Java Developer Interview",
                                    "tech_stack": <TechStack: Java>,
                                    "topics_with_questions": [...]
                                  }

        Returns:
            TemplateForm: The updated template form instance
                         Example: TemplateForm(id=1, name="Updated Java Developer Interview", ...)
        """
        # Get the current user from the request context
        # Example: User(id=1, username="manager1")
        manager = self.context["request"].user

        # Call service function to handle the complex update logic
        # Returns the updated TemplateForm instance
        return update_template_form(
            instance=instance, manager=manager, validated_data=validated_data
        )


class TemplateFormListSerializer(serializers.ModelSerializer):
    """
    A serializer for the list representation of `TemplateForm`.

    Provides a concise, read-optimized view of form templates. Includes
    aggregated fields such as `topics_count` and `items_count`, and also
    generates a URL for navigating to the detailed view.
    """

    # String representation of the technology stack
    # Example: "Java" or "Python"
    tech_stack = serializers.StringRelatedField()

    # Count of topics in this template form
    # Example: 5 (meaning the form has 5 topics)
    topics_count = serializers.IntegerField(read_only=True)

    # Count of active (non-removed) items/questions in this template form
    # Example: 25 (meaning the form has 25 active questions)
    items_count = serializers.IntegerField(source="active_items_count", read_only=True)

    # URL to access the detailed view of this template form
    # Example: "http://example.com/api/template-form/java-developer-interview/"
    form_detail_url = serializers.SerializerMethodField()

    class Meta:
        model = TemplateForm
        fields = (
            "id",  # Integer primary key (Example: 1)
            "name",  # String name of the template (Example: "Java Developer Interview")
            "tech_stack",  # String representation of tech stack (Example: "Java")
            "topics_count",  # Integer count of topics (Example: 5)
            "items_count",  # Integer count of active items (Example: 25)
            "form_detail_url",  # URL to detail view (Example: "http://example.com/api/template-form/java-developer-interview/")
        )

    def get_form_detail_url(self, instance):
        """
        Generate URL for item detail view.

        Args:
            instance (TemplateForm): The template form instance
                                    Example: TemplateForm(id=1, name="Java Developer Interview", slug="java-developer-interview")

        Returns:
            str: The absolute URL to the detail view
                Example: "http://example.com/api/template-form/java-developer-interview/"
            None: If request context is not available
        """
        # Get the request object from context
        # Example: <Request: GET '/api/template-form/'>
        request = self.context.get("request")
        if not request:
            return None

        # Prepare URL parameters using the form's slug
        # Example: {"slug": "java-developer-interview"}
        kwargs = {"slug": instance.slug}
        view_name = "template_form:template-form-detail"

        # Build and return the absolute URL
        # Example: "http://example.com/api/template-form/java-developer-interview/"
        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class TemplateFormItemsListSerializer(serializers.ModelSerializer):
    """
    A serializer for the list representation of form items (`TemplateFormItems`).

    Used as a nested serializer within `TemplateFormDetailSerializer` to
    display a list of active questions within each topic.
    """

    # URL to access the detailed view of this form item
    # Example: "http://example.com/api/template-form/java-developer-interview/items/42/"
    item_detail_url = serializers.SerializerMethodField()

    class Meta:
        model = TemplateFormItems
        fields = (
            "id",  # Integer primary key (Example: 42)
            "text_snapshot",  # String text of the question (Example: "What is dependency injection?")
            "difficulty_snapshot",  # Integer difficulty level (Example: 2 for Medium)
            "item_detail_url",  # URL to detail view (Example: "http://example.com/api/template-form/java-developer-interview/items/42/")
        )

    def get_item_detail_url(self, instance):
        """
        Generate URL for item detail view.

        Args:
            instance (TemplateFormItems): The form item instance
                                         Example: TemplateFormItems(id=42, text_snapshot="What is dependency injection?")

        Returns:
            str: The absolute URL to the detail view
                Example: "http://example.com/api/template-form/java-developer-interview/items/42/"
            None: If request context is not available
        """
        # Get the request object from context
        # Example: <Request: GET '/api/template-form/java-developer-interview/'>
        request = self.context.get("request")
        if not request:
            return None

        # Prepare URL parameters using the form's slug and item's primary key
        # Example: {"form_topic__form_slug": "java-developer-interview", "pk": 42}
        view_name = "template_form:form-items-detail"
        kwargs = {
            "form_topic__form_slug": instance.form_topic.form.slug,  # Example: "java-developer-interview"
            "pk": instance.pk,  # Example: 42
        }

        # Build and return the absolute URL
        # Example: "http://example.com/api/template-form/java-developer-interview/items/42/"
        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class TemplateFormItemsDetailSerializer(serializers.ModelSerializer):
    """
    A serializer for the detailed representation of a single form item.

    Provides full, read-only information about a specific snapshot item,
    including all `_snapshot` fields and a reference to the original question.
    """

    # String representation of the original question this item was based on
    # Example: "What is dependency injection?" or None if created directly
    origin_question = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TemplateFormItems
        fields = (
            "id",  # Integer primary key (Example: 42)
            "text_snapshot",  # String text of the question (Example: "What is dependency injection?")
            "difficulty_snapshot",  # Integer difficulty level (Example: 2 for Medium)
            "topic_snapshot",  # String name of the topic (Example: "ORM")
            "max_score_snapshot",  # Integer maximum score possible (Example: 5)
            "origin_question",  # String representation of original question (Example: "What is dependency injection?")
            "is_removed",  # Boolean indicating if item is removed (Example: False)
        )
        read_only_fields = fields


class TemplateFormItemUpdateSerializer(serializers.ModelSerializer):
    """
    A serializer for partially updating a form item.

    Allows modification of a limited set of snapshot fields, such as
    difficulty or the text of a question that was created on the fly.
    """

    class Meta:
        model = TemplateFormItems
        fields = (
            "text_snapshot",  # String text of the question (Example: "What is dependency injection?")
            "difficulty_snapshot",  # Integer difficulty level (Example: 2 for Medium)
            "topic_snapshot",  # String name of the topic (Example: "ORM")
        )

    def validate_difficulty_snapshot(self, value):
        """
        Validate `difficulty_snapshot` value (1, 2 or 3)

        Args:
            value (int): The difficulty level to validate
                        Example: 2

        Returns:
            int: The validated difficulty level
                Example: 2

        Raises:
            ValidationError: If value is not 1, 2, or 3
                            Example: ValidationError(["Difficulty snapshot must be 1 (Easy), 2(Medium), 3(Hard)."])
        """
        # Check if difficulty is one of the allowed values
        # value - Integer representing difficulty level (1=Easy, 2=Medium, 3=Hard)
        if value not in [1, 2, 3]:
            raise serializers.ValidationError(
                "Difficulty snapshot must be 1 (Easy),  2(Medium), 3(Hard)."
            )
        return value


class TemplateFormDetailSerializer(serializers.ModelSerializer):
    """
    A serializer for the detailed representation of `TemplateForm`.

    Provides complete information about a form template, including the list
    of topics and a nested list of active questions for each of them. It also
    exposes draft-related data if a draft exists.
    """

    # String representation of the technology stack
    # Example: "Java" or "Python"
    tech_stack = serializers.StringRelatedField(read_only=True)

    # Nested structure of topics and their active questions
    # Example: [
    #   {
    #     "topic": {"id": 1, "name": "ORM"},
    #     "questions": [
    #       {"id": 42, "text_snapshot": "What is an ORM?", "difficulty_snapshot": 1, "item_detail_url": "..."}
    #     ]
    #   }
    # ]
    topics_with_questions = serializers.SerializerMethodField()

    # String representation of the user who manages this template
    # Example: "john.doe@example.com"
    manager = serializers.StringRelatedField(read_only=True)

    # JSON data containing the draft state of the form
    # Example: {"name": "Updated Java Interview", "topics_with_questions": [...]}
    draft_data = serializers.JSONField(read_only=True)

    # Boolean indicating if there are unpublished changes
    # Example: True
    has_unpublished_changes = serializers.BooleanField(read_only=True)

    # Timestamp of when the draft was last updated
    # Example: "2023-05-15T14:30:45Z"
    draft_updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TemplateForm
        fields = (
            "id",  # Integer primary key (Example: 1)
            "name",  # String name of the template (Example: "Java Developer Interview")
            "manager",  # String representation of manager (Example: "john.doe@example.com")
            "tech_stack",  # String representation of tech stack (Example: "Java")
            "topics_with_questions",  # Nested structure of topics and questions
            "created_at",  # Timestamp of creation (Example: "2023-05-10T09:15:30Z")
            "draft_data",  # JSON data of draft (Example: {"name": "Updated Java Interview", ...})
            "has_unpublished_changes",  # Boolean flag (Example: True)
            "draft_updated_at",  # Timestamp of draft update (Example: "2023-05-15T14:30:45Z")
        )

    def get_topics_with_questions(self, instance):
        """
        Builds a nested structure of topics and active questions.

        This method retrieves all topics associated with the form, filters their
        questions to include only active ones (`is_removed=False`), and serializes
        them into the defined response structure.

        Args:
            instance (TemplateForm): The template form instance
                                    Example: TemplateForm(id=1, name="Java Developer Interview")

        Returns:
            list: A list of dictionaries, where each dictionary represents a topic
                  and its list of questions.
                  Example: [
                    {
                      "topic": {"id": 1, "name": "ORM"},
                      "questions": [
                        {"id": 42, "text_snapshot": "What is an ORM?", "difficulty_snapshot": 1, "item_detail_url": "..."}
                      ]
                    }
                  ]
        """
        # Initialize empty result list
        # Will contain dictionaries with topic and questions data
        result = []

        # Iterate through all topics associated with this form
        # form_topic - TemplateFormTopic instance linking a Topic to this TemplateForm
        for form_topic in instance.form_topics.all():
            # Try to get pre-filtered active items if available (from prefetch_related)
            # active_items - List of TemplateFormItems that are not removed
            active_items = getattr(form_topic, "active_items", None)
            if active_items is None:
                # If not prefetched, filter items manually
                active_items = [
                    item for item in form_topic.items.all() if not item.is_removed
                ]

            # Skip topics with no active items
            if not active_items:
                continue

            # Add topic with its questions to the result
            # Creates a dictionary with "topic" and "questions" keys
            result.append(
                {
                    "topic": TopicSerializer(
                        form_topic.topic, context=self.context
                    ).data,  # Example: {"id": 1, "name": "ORM"}
                    "questions": TemplateFormItemsListSerializer(
                        active_items, many=True, context=self.context
                    ).data,  # Example: [{"id": 42, "text_snapshot": "What is an ORM?", ...}]
                }
            )

        return result
