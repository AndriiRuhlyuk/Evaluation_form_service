from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.urls import reverse

from project.models import Project
from question.models import Question
from working_form.custom_fields import M2MListField
from working_form.models import WorkingForm, WorkingFormItem, WorkingFormTopic


Employee = get_user_model()


class SimpleEmployeeSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for the Employee model.

    Used for nested representations within other serializers to avoid
    exposing sensitive user data. Only includes basic identification
    information about an employee.
    """

    class Meta:
        model = Employee  # The model being serialized
        fields = (
            "email",  # Employee's email address
            "fullname",  # Employee's full name
        )


class WorkingFormCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new WorkingForm instance.

    Handles the validation and creation of a working form, including its
    associated topics and questions, which are cloned from a template.
    It also validates the roles of the assigned users, ensuring that:
    - Approvers are a subset of interviewers
    - Recruiters have the RECRUITER role
    - Hiring manager has the HIRING_MANAGER role
    - The creator is automatically added as a recruiter
    """

    vacancy = serializers.CharField(
        max_length=500
    )  # The name of the vacancy (e.g., "Python Developer")
    level = serializers.ChoiceField(
        choices=WorkingForm.Level.choices
    )  # Seniority level of the vacancy
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(), required=True, allow_null=False
    )  # The project this vacancy is for

    # The 'interviewers', 'approvers', and 'recruiters' fields are lists of user IDs.
    interviewers = serializers.ListField(
        child=serializers.IntegerField(
            min_value=1
        ),  # User IDs must be positive integers
        allow_empty=False,
        min_length=1,
        error_messages={
            "min_length": "At least one interviewer is required.",
            "empty": "At least one interviewer is required.",
        },
    )  # List of employees who will conduct the interview

    approvers = serializers.ListField(
        child=serializers.IntegerField(
            min_value=1
        ),  # User IDs must be positive integers
        allow_empty=False,
        min_length=1,
        error_messages={
            "min_length": "At least one approver is required.",
            "empty": "At least one approver is required.",
        },
    )  # List of employees who must approve the form before it can be used

    recruiters = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=True
    )  # Optional list of recruiters responsible for the hiring process

    hiring_manager_id = serializers.IntegerField(
        required=True,
        allow_null=False,
        error_messages={"required": "Hiring Manager is required."},
    )  # The hiring manager who makes the final hiring decision

    def validate(self, data):
        """
        Comprehensive validation of the form creation data.

        This method performs several important validation and transformation steps:
        1. Validates user roles (Recruiter, Hiring Manager).
        2. Validates that approvers are a subset of interviewers.
        3. Fetches all users in a single query for efficiency.
        4. Replaces user IDs with user objects in validated_data.
        5. Automatically adds the creator (request.user) to the recruiters list.

        Args:
            data (dict): The initial data dictionary containing user IDs

        Returns:
            dict: The validated data with user IDs replaced by user objects

        Raises:
            ValidationError: If any validation checks fail
        """

        # Extract user IDs from the data
        interviewer_ids = data.get("interviewers", [])  # List of interviewer user IDs
        approver_ids = data.get("approvers", [])  # List of approver user IDs
        recruiter_ids = data.get("recruiters", [])  # List of recruiter user IDs
        hiring_manager_id = data.get("hiring_manager_id")  # Hiring manager user ID

        # Get the user who is creating this form
        creator = self.context.get("request").user

        # Check for duplicate IDs in each list
        if len(interviewer_ids) != len(set(interviewer_ids)):
            raise serializers.ValidationError(
                {
                    "interviewers": "Interviewers must be unique. Please remove any duplicates."
                }
            )
        if len(approver_ids) != len(set(approver_ids)):
            raise serializers.ValidationError(
                {"approvers": "Approvers must be unique. Please remove any duplicates."}
            )
        if len(recruiter_ids) != len(set(recruiter_ids)):
            raise serializers.ValidationError(
                {
                    "recruiters": "Recruiters list must be unique. Please remove any duplicates."
                }
            )

        # Convert lists to sets for efficient operations
        interviewer_id_set = set(interviewer_ids)
        approver_id_set = set(approver_ids)

        # Validate that all approvers are also interviewers
        if not approver_id_set.issubset(interviewer_id_set):
            raise serializers.ValidationError(
                "All approvers must also be listed as interviewers."
            )

        # Combine all IDs to fetch in a single query for efficiency
        all_ids_to_fetch = interviewer_id_set | set(recruiter_ids)

        if hiring_manager_id is not None:
            all_ids_to_fetch.add(hiring_manager_id)

        # Fetch all users in a single query
        users = Employee.objects.filter(pk__in=all_ids_to_fetch)
        user_map = {user.id: user for user in users}  # Map of user ID to user object

        # Check if all IDs were found
        if len(users) != len(all_ids_to_fetch):
            found_ids = set(user_map.keys())
            missing_ids = all_ids_to_fetch - found_ids
            raise serializers.ValidationError(
                f"The following user IDs were not found: {missing_ids}"
            )

        # Validate that all recruiters have the RECRUITER role
        recruiter_objects = []
        for r_id in recruiter_ids:
            user = user_map[r_id]
            if user.role != "RECRUITER":
                raise serializers.ValidationError(
                    {"recruiters": f"User {user.fullname} is not a Recruiter."}
                )
            recruiter_objects.append(user)

        # Validate that the hiring manager has the HIRING_MANAGER role
        manager_object = user_map.get(hiring_manager_id)
        if not manager_object or manager_object.role != "HIRING_MANAGER":
            raise serializers.ValidationError(
                {"hiring_manager_id": "The selected user is not a Hiring Manager."}
            )

        # Replace IDs with actual user objects in the data
        data["interviewers"] = [user_map[id] for id in interviewer_ids]
        data["approvers"] = [user_map[id] for id in approver_ids]
        data["hiring_manager"] = manager_object

        # Add the creator to the recruiters list
        data["recruiters"] = list(set(recruiter_objects + [creator]))

        # Remove the hiring_manager_id as it's replaced by the hiring_manager object
        data.pop("hiring_manager_id")

        return data


class WorkingFormUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an existing WorkingForm instance.

    Handles validation for fields that can be modified after creation.
    If key fields like 'interviewers' or 'approvers' are changed, it resets
    the approval status of the form by removing approvals from users who
    are no longer in the approvers list.

    This serializer uses a custom M2MListField for handling many-to-many
    relationships, which allows for partial updates of these fields.
    """

    vacancy = serializers.CharField(max_length=500)  # The name of the vacancy
    level = serializers.ChoiceField(
        choices=WorkingForm.Level.choices
    )  # Seniority level
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(), required=True, allow_null=False
    )  # The project this vacancy is for
    interviewers = M2MListField(
        required=False
    )  # List of interviewer IDs, optional for partial updates
    approvers = M2MListField(
        required=False
    )  # List of approver IDs, optional for partial updates
    recruiters = M2MListField(
        required=False
    )  # List of recruiter IDs, optional for partial updates
    hiring_manager_id = serializers.IntegerField(
        required=False, allow_null=True
    )  # Hiring manager ID, optional

    class Meta:
        model = WorkingForm  # The model being serialized
        fields = (
            "vacancy",  # Vacancy name field
            "level",  # Seniority level field
            "project",  # Project field
            "interviewers",  # Interviewers M2M field
            "approvers",  # Approvers M2M field
            "recruiters",  # Recruiters M2M field
            "hiring_manager_id",  # Hiring manager FK field
        )

    def validate(self, data):
        """
        Comprehensive validation of the form update data.

        This method performs several important validation and transformation steps:
        1. Validates that all user lists contain unique IDs
        2. Validates user roles (Recruiter, Hiring Manager)
        3. Validates that approvers are a subset of interviewers
        4. Fetches all users in a single query for efficiency
        5. Replaces user IDs with user objects in validated_data

        The method handles partial updates, only processing fields that are
        included in the update request.

        Args:
            data (dict): The initial data dictionary containing user IDs

        Returns:
            dict: The validated data with user IDs replaced by user objects

        Raises:
            ValidationError: If any validation checks fail
        """
        # Extract user IDs from the data (if provided in the update)
        interviewer_ids = data.get("interviewers", [])  # List of interviewer user IDs
        approver_ids = data.get("approvers", [])  # List of approver user IDs
        recruiter_ids = data.get(
            "recruiters"
        )  # List of recruiter user IDs (can be None)
        hiring_manager_id = data.get(
            "hiring_manager_id"
        )  # Hiring manager user ID (can be None)

        # Check for duplicate IDs in each list
        for field_name in ("interviewers", "approvers", "recruiters"):
            ids = data.get(field_name)
            if ids is not None and len(ids) != len(set(ids)):
                raise serializers.ValidationError(
                    {field_name: f"{field_name.capitalize()} must be unique."}
                )

        # Collect all user IDs that need to be fetched
        all_ids_to_fetch = set()
        if interviewer_ids is not None:
            all_ids_to_fetch.update(interviewer_ids)  # Add interviewer IDs
        if approver_ids is not None:
            all_ids_to_fetch.update(approver_ids)  # Add approver IDs
        if recruiter_ids is not None:
            all_ids_to_fetch.update(recruiter_ids)  # Add recruiter IDs
        if hiring_manager_id is not None:
            all_ids_to_fetch.add(hiring_manager_id)  # Add hiring manager ID

        # Fetch all users in a single query if there are any IDs to fetch
        if all_ids_to_fetch:
            users = Employee.objects.filter(pk__in=all_ids_to_fetch)
            user_map = {
                user.id: user for user in users
            }  # Map of user ID to user object

            # Check if all IDs were found
            if len(users) != len(all_ids_to_fetch):
                missing_ids = all_ids_to_fetch - set(user_map.keys())
                raise serializers.ValidationError(f"Users not found: {missing_ids}")
        else:
            user_map = {}  # Empty map if no users to fetch

        # Validate recruiters if provided in the update
        if recruiter_ids is not None:
            recruiter_objects = []
            for rid in recruiter_ids:
                user = user_map[rid]
                if user.role != "RECRUITER":
                    raise serializers.ValidationError(
                        {"recruiters": f"User {user.fullname} is not a Recruiter."}
                    )
                recruiter_objects.append(user)
            data["recruiters"] = recruiter_objects  # Replace IDs with user objects

        # Validate hiring manager if provided in the update
        if hiring_manager_id is not None:
            manager_object = user_map.get(hiring_manager_id)
            if not manager_object or manager_object.role != "HIRING_MANAGER":
                raise serializers.ValidationError(
                    {"hiring_manager_id": "The selected user is not a Hiring Manager."}
                )
            data["hiring_manager"] = manager_object  # Replace ID with user object
            data.pop("hiring_manager_id")  # Remove ID field as it's replaced by object

        # Replace interviewer and approver IDs with user objects if provided
        if interviewer_ids is not None:
            data["interviewers"] = [user_map[id] for id in interviewer_ids]
        if approver_ids is not None:
            data["approvers"] = [user_map[id] for id in approver_ids]

        # Validate that all approvers are also interviewers
        # This needs to consider both updated fields and existing values
        if "approvers" in data or "interviewers" in data:
            # Get final lists of interviewers and approvers after update
            final_interviewers = data.get(
                "interviewers", list(self.instance.interviewers.all())
            )  # Use provided interviewers or existing ones
            final_approvers = data.get(
                "approvers", list(self.instance.approvers.all())
            )  # Use provided approvers or existing ones
            final_interviewer_ids = {
                user.id for user in final_interviewers
            }  # Set of interviewer IDs
            final_approver_ids = {
                user.id for user in final_approvers
            }  # Set of approver IDs

            # Check that all approvers are also interviewers
            if not final_approver_ids.issubset(final_interviewer_ids):
                raise serializers.ValidationError(
                    "All approvers must also be listed as interviewers."
                )

        return data

    def _sync_m2m(self, m2m_manager, old_objects, new_objects):
        """
        Efficiently synchronizes a many-to-many relationship.

        This helper method compares the old and new sets of related objects,
        and performs only the necessary add/remove operations to update the
        relationship, minimizing database operations.

        Args:
            m2m_manager: The many-to-many manager to update
            old_objects (list): The current list of related objects
            new_objects (list): The new list of related objects to set

        Returns:
            None
        """
        if new_objects is None:
            return  # No update needed if new_objects is None (field not in update data)

        old_ids = {user.id for user in old_objects}  # Set of current user IDs
        new_ids = {user.id for user in new_objects}  # Set of new user IDs

        if to_add := new_ids - old_ids:  # Users to add (in new set but not in old set)
            m2m_manager.add(*to_add)  # Add the new users

        if (
            to_remove := old_ids - new_ids
        ):  # Users to remove (in old set but not in new set)
            m2m_manager.remove(*to_remove)  # Remove the old users

    def update(self, instance, validated_data):
        """
        Updates a WorkingForm instance with validated data.

        This method handles the complex update process for a WorkingForm:
        - Manages many-to-many relationship updates (interviewers, approvers, recruiters)
        - Handles foreign key update (hiring_manager)
        - Maintains approval state consistency by removing stale approvals
        - Saves the final state for potential WebSocket notifications

        Args:
            instance (WorkingForm): The existing WorkingForm instance to update
            validated_data (dict): The validated data containing the updates

        Returns:
            WorkingForm: The updated WorkingForm instance
        """
        # Extract M2M fields from validated data to handle separately
        new_interviewers = validated_data.pop(
            "interviewers", None
        )  # New interviewers list or None
        new_approvers = validated_data.pop(
            "approvers", None
        )  # New approvers list or None
        new_recruiters = validated_data.pop(
            "recruiters", None
        )  # New recruiters list or None

        # Get current values for comparison and fallback
        old_interviewers = list(instance.interviewers.all())  # Current interviewers
        old_approvers = list(instance.approvers.all())  # Current approvers
        old_recruiters = list(instance.recruiters.all())  # Current recruiters
        old_hiring_manager = instance.hiring_manager  # Current hiring manager

        # Store final lists for potential WebSocket notifications
        self._interviewers_list = (
            new_interviewers if new_interviewers is not None else old_interviewers
        )  # Use new list if provided, otherwise keep old list
        self._approvers_list = (
            new_approvers if new_approvers is not None else old_approvers
        )  # Use new list if provided, otherwise keep old list
        self._recruiters_list = (
            new_recruiters if new_recruiters is not None else old_recruiters
        )  # Use new list if provided, otherwise keep old list

        # Get the new hiring manager or keep the old one
        new_hiring_manager = validated_data.get("hiring_manager", old_hiring_manager)
        self._hiring_manager_obj = (
            new_hiring_manager  # Store for potential WebSocket notifications
        )

        # Update the instance with the remaining validated data
        instance = super().update(instance, validated_data)

        # Synchronize M2M relationships
        self._sync_m2m(instance.interviewers, old_interviewers, new_interviewers)
        self._sync_m2m(instance.approvers, old_approvers, new_approvers)

        # If approvers changed, remove approvals from users who are no longer approvers
        if new_approvers is not None:
            new_approver_ids = {
                user.id for user in new_approvers
            }  # Set of new approver IDs
            stale_approvals = instance.approved_by.exclude(
                pk__in=new_approver_ids
            )  # Users who approved but are no longer approvers
            if stale_approvals.exists():
                instance.approved_by.remove(*stale_approvals)  # Remove their approvals

        # Synchronize recruiters
        self._sync_m2m(instance.recruiters, old_recruiters, new_recruiters)

        return instance


class WorkingFormListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing WorkingForm instances.

    This serializer provides a lightweight representation of WorkingForm objects
    for use in list views. It includes only the essential fields needed for
    displaying forms in a list, along with a URL to access the detailed view.
    """

    tech_stack = (
        serializers.StringRelatedField()
    )  # String representation of the tech stack
    working_form_detail_url = (
        serializers.SerializerMethodField()
    )  # URL to the detail view

    class Meta:
        model = WorkingForm  # The model being serialized
        fields = (
            "id",  # Primary key
            "name",  # Form name
            "tech_stack",  # Technology stack
            "status",  # Form status (IN_PROGRESS/APPROVED)
            "working_form_detail_url",  # URL to the detail view
        )

    def get_working_form_detail_url(self, instance):
        """
        Generate URL for the form's detail view.

        Constructs an absolute URL to the detail view of this working form,
        using the form's slug for the URL pattern.

        Args:
            instance (WorkingForm): The WorkingForm instance being serialized

        Returns:
            str or None: The absolute URL to the detail view, or None if request context is missing
        """

        request = self.context.get("request")  # Get the request from context
        if not request:
            return None  # Can't build URL without request

        kwargs = {"slug": instance.slug}  # URL parameters
        view_name = "working_form:working-form-detail"  # Name of the detail view

        return request.build_absolute_uri(
            reverse(view_name, kwargs=kwargs)
        )  # Build absolute URL


class WorkingFormTopicListSerializer(serializers.ModelSerializer):
    """
    Serializer for a topic list within the main WorkingForm detail view.

    This serializer is used to represent topics in the context of a working form.
    It includes information about the topic itself, its deletion status, and
    statistics about the questions it contains. It's used as a nested serializer
    within the WorkingFormDetailSerializer for the topics field.
    """

    id = serializers.IntegerField(
        source="topic.id", read_only=True
    )  # Topic ID from the related Topic model
    name = serializers.CharField(
        source="topic.name", read_only=True
    )  # Topic name from the related Topic model

    delete_votes = serializers.IntegerField(
        source="topic_delete_votes", read_only=True
    )  # Number of votes to delete this topic
    is_effectively_deleted = (
        serializers.SerializerMethodField()
    )  # Calculated field for deletion status

    question_count = serializers.IntegerField(
        source="questions_count", read_only=True
    )  # Number of active questions in this topic
    detail_url = serializers.SerializerMethodField()  # URL to the topic detail view
    candidates_for_deletion_count = serializers.IntegerField(
        source="candidate_for_deletion_count", read_only=True
    )  # Number of questions with deletion votes but not yet removed

    class Meta:
        model = WorkingFormTopic  # The model being serialized
        fields = (
            "id",  # Topic ID
            "name",  # Topic name
            "delete_votes",  # Number of deletion votes
            "is_effectively_deleted",  # Whether the topic is effectively deleted
            "question_count",  # Number of questions
            "detail_url",  # URL to detail view
            "candidates_for_deletion_count",  # Questions with deletion votes
        )

    def get_is_effectively_deleted(self, instance: WorkingFormTopic) -> bool:
        """
        Calculates deletion status for the topic.

        Determines whether a topic should be considered effectively deleted
        based on the number of deletion votes compared to the total number
        of approvers. Uses prefetched data when available for efficiency.

        Args:
            instance (WorkingFormTopic): The topic instance being serialized

        Returns:
            bool: True if the topic is effectively deleted, False otherwise
        """

        if not hasattr(instance, "total_approvers_annotated"):
            # If the annotated data isn't available, use the instance property
            return instance.is_effectively_deleted

        # Calculate effective deletion based on annotated data
        return instance.calculate_effective_deletion(
            total_approvers=instance.total_approvers_annotated,  # Total number of approvers
            delete_votes=instance.topic_delete_votes,  # Number of deletion votes
        )

    def get_detail_url(self, instance):
        """
        Generate URL for the topic's detail view.

        Constructs an absolute URL to the detail view of this topic within
        its working form, using the working form's slug and the topic's ID.

        Args:
            instance (WorkingFormTopic): The topic instance being serialized

        Returns:
            str or None: The absolute URL to the detail view, or None if request context is missing
        """
        request = self.context.get("request")  # Get the request from context
        if not request:
            return None  # Can't build URL without request

        return request.build_absolute_uri(
            reverse(
                "working_form:working-form-topics-detail",  # Name of the detail view
                kwargs={
                    "working_form_slug": instance.working_form.slug,  # Working form slug for URL
                    "pk": instance.pk,  # Topic ID for URL
                },
            )
        )


class WorkingFormDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single WorkingForm instance.

    This serializer provides a comprehensive representation of a WorkingForm,
    including all its topics, associated users (interviewers, approvers, recruiters),
    approval status, and other metadata. It's used for the detail view of a
    working form.
    """

    tech_stack = serializers.StringRelatedField(
        read_only=True
    )  # String representation of the tech stack
    interviewers = SimpleEmployeeSerializer(
        many=True, read_only=True
    )  # List of interviewers with basic info
    approvers = SimpleEmployeeSerializer(
        many=True, read_only=True
    )  # List of approvers with basic info
    topics = WorkingFormTopicListSerializer(
        source="form_topics", many=True, read_only=True
    )  # List of topics with their details
    is_fully_approved = serializers.BooleanField(
        read_only=True
    )  # Whether all approvers have approved
    hiring_manager = SimpleEmployeeSerializer(
        read_only=True
    )  # Hiring manager with basic info
    recruiters = SimpleEmployeeSerializer(
        many=True, read_only=True
    )  # List of recruiters with basic info
    approved_by_me = (
        serializers.SerializerMethodField()
    )  # Whether the current user has approved

    class Meta:
        model = WorkingForm  # The model being serialized
        fields = (
            "id",  # Primary key
            "name",  # Form name
            "status",  # Form status (IN_PROGRESS/APPROVED)
            "tech_stack",  # Technology stack
            "topics",  # List of topics
            "created_at",  # Creation timestamp
            "interviewers",  # List of interviewers
            "approvers",  # List of approvers
            "hiring_manager",  # Hiring manager
            "recruiters",  # List of recruiters
            "is_fully_approved",  # Full approval status
            "approved_by_me",  # Current user's approval status
        )

    def get_approved_by_me(self, instance: WorkingForm) -> bool:
        """
        Check if the current user has approved this form.

        Determines whether the authenticated user making the request
        is in the 'approved_by' list of the form, indicating they have
        already approved it.

        Args:
            instance (WorkingForm): The form instance being serialized

        Returns:
            bool: True if the current user has approved the form, False otherwise
        """

        request = self.context.get("request")  # Get the request from context
        if not request or not request.user.is_authenticated:
            return False  # Not approved if no request or user is not authenticated

        user = request.user  # The current user
        approved_by_ids = {
            us.pk for us in instance.approved_by.all()
        }  # Set of user IDs who approved

        return (
            user.pk in approved_by_ids
        )  # Check if current user's ID is in the approved_by set


class WorkingFormItemSerializer(serializers.ModelSerializer):
    """
    Serializer for a single item (question) within a WorkingForm.

    This serializer provides a detailed representation of a question item
    within a working form topic. It includes information about the question text,
    difficulty, deletion status, and voting information. It supports both
    read operations (for displaying items) and write operations (for updating items).
    """

    detail_url = serializers.SerializerMethodField()  # URL to the item detail view
    delete_votes = serializers.IntegerField(
        read_only=True
    )  # Number of votes to delete this item
    is_effectively_deleted = (
        serializers.SerializerMethodField()
    )  # Calculated field for deletion status
    voted_by_current_user = (
        serializers.SerializerMethodField()
    )  # Whether current user voted to delete
    difficulty = serializers.CharField(
        source="get_difficulty_snapshot_display", read_only=True
    )  # Human-readable difficulty level
    difficulty_snapshot = serializers.ChoiceField(
        choices=WorkingFormItem.Difficulty.choices, write_only=True, required=False
    )  # Difficulty level for updates

    class Meta:
        model = WorkingFormItem  # The model being serialized
        fields = (
            "id",  # Primary key
            "text_snapshot",  # Question text
            "difficulty",  # Human-readable difficulty (read-only)
            "difficulty_snapshot",  # Difficulty level (write-only)
            "delete_votes",  # Number of deletion votes
            "is_effectively_deleted",  # Whether effectively deleted
            "voted_by_current_user",  # Current user's vote status
            "source_snapshot",  # Source of the question
            "detail_url",  # URL to detail view
        )

    def update(self, instance, validated_data):
        """
        Updates a WorkingFormItem instance with validated data.

        If the question text is modified, automatically updates the source
        to indicate it was changed by an interviewer.

        Args:
            instance (WorkingFormItem): The item instance to update
            validated_data (dict): The validated data for the update

        Returns:
            WorkingFormItem: The updated item instance
        """

        if "text_snapshot" in validated_data:
            # If text is changed, mark the source as changed by interviewer
            validated_data["source_snapshot"] = Question.QuestionSource.CHANGED

        return super().update(instance, validated_data)

    def get_is_effectively_deleted(self, instance: WorkingFormItem) -> bool:
        """
        Calculates deletion status for the item.

        Determines whether an item should be considered effectively deleted
        based on the number of deletion votes compared to the total number
        of approvers. Uses prefetched data when available for efficiency.

        Args:
            instance (WorkingFormItem): The item instance being serialized

        Returns:
            bool: True if the item is effectively deleted, False otherwise
        """

        if not hasattr(instance, "total_approvers"):
            # If the annotated data isn't available, use the instance property
            return instance.is_effectively_deleted

        # Calculate effective deletion based on annotated data
        return instance.calculate_effective_deletion(
            total_approvers=instance.total_approvers,  # Total number of approvers
            delete_votes=instance.delete_votes,  # Number of deletion votes
        )

    def get_voted_by_current_user(self, instance) -> bool:
        """
        Checks if the current user has voted to delete this item.

        Determines whether the authenticated user making the request
        has voted for the deletion of this item.

        Args:
            instance (WorkingFormItem): The item instance being serialized

        Returns:
            bool: True if the current user has voted to delete, False otherwise
        """

        user = self.context.get("request").user  # The current user
        if not user or user.is_anonymous:
            return False  # Not voted if no user or user is anonymous

        prefetched_users = instance.deleted_by.all()  # Users who voted to delete
        user_ids_who_voted = {
            u.id for u in prefetched_users
        }  # Set of user IDs who voted

        return (
            user.id in user_ids_who_voted
        )  # Check if current user's ID is in the voted set

    def get_detail_url(self, instance: WorkingFormItem):
        """
        Generate URL for the item's detail view.

        Constructs an absolute URL to the detail view of this item within
        its working form, using the working form's slug and the item's ID.

        Args:
            instance (WorkingFormItem): The item instance being serialized

        Returns:
            str or None: The absolute URL to the detail view, or None if request context is missing
        """
        request = self.context.get("request")  # Get the request from context
        if not request:
            return None  # Can't build URL without request

        kwargs = {
            "working_form_slug": instance.form_topic.working_form.slug,  # Working form slug for URL
            "pk": instance.pk,  # Item ID for URL
        }

        view_name = "working_form:working-form-items-detail"  # Name of the detail view

        return request.build_absolute_uri(
            reverse(view_name, kwargs=kwargs)
        )  # Build absolute URL


class WorkingFormTopicDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single topic, including all its questions.

    This serializer provides a comprehensive view of a topic within a working form,
    including all the questions (items) associated with it. It's used for the
    detail view of a topic.
    """

    questions = serializers.SerializerMethodField()  # List of questions in this topic

    class Meta:
        model = WorkingFormTopic  # The model being serialized
        fields = ("questions",)  # Only include the questions field

    def get_questions(self, instance: WorkingFormTopic):
        """
        Retrieves all active items (questions) for this topic.

        Takes a WorkingForm Topic instance and serializes its items using
        the WorkingFormItemSerializer, passing along the request context.

        Args:
            instance (WorkingFormTopic): The topic instance being serialized

        Returns:
            list: Serialized representation of all active items in this topic
        """

        active_items = instance.items.all()  # Get all active items for this topic

        return WorkingFormItemSerializer(
            active_items, many=True, context=self.context
        ).data  # Serialize the items


class AddQuestionToTopicSerializer(serializers.Serializer):
    """
    Serializer for adding a question to a topic.

    This serializer handles two scenarios:
    1. Adding an existing question by providing its ID
    2. Creating a new question by providing text and difficulty

    It's used in the add_question action of the WorkingFormTopicViewSet.
    """

    origin_question = serializers.IntegerField(
        required=False
    )  # ID of an existing question to add
    question_text = serializers.CharField(required=False)  # Text for a new question
    difficulty_snapshot = serializers.ChoiceField(
        choices=WorkingFormItem.Difficulty.choices, required=False
    )  # Difficulty level for a new question

    def validate(self, data):
        """
        Validates that the data contains either an existing question ID
        or both text and difficulty for a new question.

        Args:
            data (dict): The data to validate

        Returns:
            dict: The validated data

        Raises:
            ValidationError: If neither scenario's requirements are met
        """
        is_existing = "origin_question" in data  # Adding an existing question
        is_new = (
            "question_text" in data and "difficulty_snapshot" in data
        )  # Creating a new question

        if not is_existing and not is_new:
            raise serializers.ValidationError(
                "Provide either 'origin_question' or both 'question_text' and 'difficulty'."
            )
        return data


class AddTopicSerializer(serializers.Serializer):
    """
    Serializer for adding a topic to a working form.

    This serializer handles two scenarios:
    1. Adding an existing topic by providing its ID
    2. Creating a new topic by providing a name

    It's used in the add_topic action of the WorkingFormViewSet.
    """

    id = serializers.IntegerField(required=False)  # ID of an existing topic to add
    name = serializers.CharField(required=False)  # Name for a new topic

    def validate(self, data):
        """
        Validates that the data contains either an existing topic ID
        or a name for a new topic.

        Args:
            data (dict): The data to validate

        Returns:
            dict: The validated data

        Raises:
            ValidationError: If neither scenario's requirements are met
        """
        if not data.get("id") and not data.get("name"):
            raise serializers.ValidationError(
                "Either 'id' or 'name' must be provided for a topic."
            )
        return data
