from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db.models import Prefetch, Count, prefetch_related_objects
from rest_framework import viewsets, status, mixins, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.response import Response

from evaluation_form.serializers import (
    CreateEvaluationFormSerializer,
    RecruiterEvaluationSerializer,
)
from topic.serializers import TopicSerializer
from working_form.models import WorkingForm, WorkingFormTopic, WorkingFormItem
from working_form.permissions import (
    CanInteractWithWorkingForm,
    CanEditWorkingForm,
    CanCreateEvaluationForm,
    IsRecruiter,
)
from working_form.serializers import (
    WorkingFormDetailSerializer,
    WorkingFormListSerializer,
    WorkingFormItemSerializer,
    AddQuestionToTopicSerializer,
    WorkingFormTopicDetailSerializer,
    WorkingFormTopicListSerializer,
    WorkingFormUpdateSerializer,
    AddTopicSerializer,
    SimpleEmployeeSerializer,
    WorkingFormCreateSerializer,
)
from working_form.services import (
    add_question_to_topic,
    add_topic_to_working_form,
    clone_working_to_evaluation,
    clone_working_from_working,
)


class WorkingFormViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    A ViewSet for managing working forms (`WorkingForm`).

    Provides operations for viewing, updating, deleting, and approving
    working forms, as well as additional actions for topic management,
    cloning, and creating evaluation forms.

    **Key features:**
    - List and detail views with optimized prefetching per action.
    - Approval workflow (approve / unapprove) with WebSocket notifications.
    - Adding topics to a working form.
    - Restoring soft-deleted topics.
    - Cloning a working form into the new one.
    - Creating an evaluation form from an approved working form.

    **Endpoints:**
    - `GET /api/working-form/` — List of working forms.
    - `GET /api/working-form/{slug}/` — Working form details.
    - `PUT/PATCH /api/working-form/{slug}/` — Update a working form.
    - `DELETE /api/working-form/{slug}/` — Soft-delete a working form.
    - `POST /api/working-form/{slug}/approve/` — Approve the form.
    - `POST /api/working-form/{slug}/unapprove/` — Revoke approval.
    - `POST /api/working-form/{slug}/add-topic/` — Add a topic.
    - `GET /api/working-form/{slug}/restore-topic/` — List soft-deleted topics.
    - `POST /api/working-form/{slug}/create-evaluation/` — Create the evaluation form.
    - `GET/POST /api/working-form/{slug}/clone/` — Clone the working form.
    """

    lookup_field = "slug"

    queryset = WorkingForm.objects.select_related("tech_stack", "hiring_manager")

    def get_serializer_class(self):
        """
        Selects the serializer class based on the current action.

        - `add_topic`: `AddTopicSerializer` for topic input validation.
        - `retrieve`: `WorkingFormDetailSerializer` for full representation.
        - `update`, `partial_update`: `WorkingFormUpdateSerializer` for editing.
        - `create_evaluation_form`: `CreateEvaluationFormSerializer`.
        - `clone`: `WorkingFormCreateSerializer` for cloning input.
        - Default (`list`): `WorkingFormListSerializer` for a concise list view.
        """
        if self.action == "add_topic":
            return AddTopicSerializer
        if self.action == "retrieve":
            return WorkingFormDetailSerializer
        if self.action in ["update", "partial_update"]:
            return WorkingFormUpdateSerializer
        if self.action == "create_evaluation_form":
            return CreateEvaluationFormSerializer
        if self.action == "clone":
            return WorkingFormCreateSerializer
        return WorkingFormListSerializer

    def get_permissions(self):
        """
        Determines access permissions based on the action.

        - `update`, `partial_update`: `IsAuthenticated` + `CanEditWorkingForm`.
        - `create_evaluation_form`: `IsAuthenticated` + `CanCreateEvaluationForm`.
        - `approve`, `unapprove`, `add_topic`, `restore_topic`: `IsAuthenticated` + `CanInteractWithWorkingForm`.
        - `destroy`: `IsAuthenticated` + `IsAdminUser`.
        - `clone`: `IsAdminUser` + `IsRecruiter`.
        - Default: `IsAuthenticated`.
        """
        if self.action in [
            "update",
            "partial_update",
        ]:
            return [permissions.IsAuthenticated(), CanEditWorkingForm()]
        if self.action == "create_evaluation_form":
            return [permissions.IsAuthenticated(), CanCreateEvaluationForm()]
        if self.action in ["approve", "unapprove", "add_topic", "restore_topic"]:
            return [permissions.IsAuthenticated(), CanInteractWithWorkingForm()]
        if self.action == "destroy":
            return [permissions.IsAuthenticated(), permissions.IsAdminUser()]
        if self.action == "clone":
            return [permissions.IsAdminUser(), IsRecruiter()]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        """
        Soft-deletes the working form instead of removing the database row.

        Without this override DRF's DestroyModelMixin would call
        `instance.delete()` - a hard delete, contradicting the `is_deleted`
        flag this model carries. Restoring is admin-only (django admin).
        """
        instance.soft_delete(self.request.user)

    def _get_form_topics_prefetch(self):
        """
        Returns a Prefetch object for form topics with annotations.

        This helper method creates a consistent prefetch specification for form topics
        that includes annotations for vote counts and question counts, as well as
        prefetching the nested item deletion votes.

        The method uses `WorkingFormTopicManager.get_annotated_list()` to add computed
        fields and ensures consistent ordering by topic name. This prefetch object
        is used in both `retrieve` and `update` flows to optimize database queries.

        Returns:
            Prefetch: A configured Prefetch object for form_topics with annotations
                      and nested prefetches
        """
        return Prefetch(
            # The relation name to prefetch
            "form_topics",
            # The queryset to use for prefetching, with annotations and ordering
            queryset=WorkingFormTopic.objects.get_annotated_list()
            .order_by("topic__name")  # Sort topics alphabetically by name
            .prefetch_related(
                "items__deleted_by"
            ),  # Also prefetch deletion votes for items
        )

    def get_queryset(self):
        """
        Returns an optimized queryset based on the current action.

        Each action gets only the prefetches/annotations it needs to avoid
        conflicts between `prefetch_related` and `annotate`:

        - `list`: annotates approver/interviewer counts, prefetches topics.
        - `retrieve`: prefetches all M2M relations for full detail view.
        - `update`, `partial_update`: prefetches recruiters and approved_by.
        - `approve`, `unapprove`, `add_topic`, `restore_topic`: prefetches approvers.
        - `create_evaluation_form`: prefetches recruiters.
        """

        queryset = super().get_queryset()

        if self.action == "list":

            return queryset.prefetch_related(self._get_form_topics_prefetch()).annotate(
                approvers_count=Count("approvers", distinct=True),
                approved_by_count=Count("approved_by", distinct=True),
                interviewer_count=Count("interviewers", distinct=True),
            )

        if self.action in ["approve", "unapprove", "add_topic", "restore_topic"]:
            return queryset.prefetch_related("approvers", "approved_by")

        if self.action in ["update", "partial_update"]:
            return queryset.prefetch_related("recruiters", "approved_by")

        if self.action == "create_evaluation_form":
            return queryset.prefetch_related("recruiters")

        if self.action == "retrieve":
            return queryset.prefetch_related(
                "interviewers", "approvers", "approved_by", "recruiters"
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieves a single working form with full detail data.

        Loads the instance with prefetched M2M relations from `get_queryset`,
        then additionally prefetches annotated topics via `_get_form_topics_prefetch`.
        """

        instance = self.get_object()

        prefetch_related_objects([instance], self._get_form_topics_prefetch())

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_update(self, serializer):
        """
        Saves the working form and sends a WebSocket notification.

        This method extends the standard perform_update behavior to include
        real-time collaboration features. After saving the form, it:

        1. Reloads M2M relationship caches to ensure fresh data
        2. Prepares a data payload with the updated form metadata
        3. Broadcasts the update to all connected clients via WebSockets

        This ensures that all users viewing the form see updates in real-time
        without needing to refresh their browser.

        Args:
            serializer: The validated serializer instance with form data

        Returns:
            WorkingForm: The saved form instance
        """
        # Save the form instance with the validated data
        form_instance = serializer.save()

        # Reload M2M caches to ensure we have fresh data after saving
        prefetch_related_objects(
            [form_instance], "interviewers", "approvers", "recruiters"
        )

        # Get the cached lists of related objects from the serializer
        interviewers_list = (
            serializer._interviewers_list
        )  # List of interviewer employees
        approvers_list = serializer._approvers_list  # List of approver employees
        recruiters_list = serializer._recruiters_list  # List of recruiter employees
        hiring_manager_obj = serializer._hiring_manager_obj  # Hiring manager employee

        # Prepare WebSocket notification
        channel_layer = get_channel_layer()  # Get the ASGI channel layer
        form_group_name = f"form_{form_instance.id}"  # Channel group name for this form

        # Prepare the data payload with updated form metadata
        updated_data = {
            "vacancy": form_instance.vacancy,  # Job vacancy title
            "level": form_instance.get_level_display(),  # Human-readable experience level
            "project": (
                form_instance.project.name if form_instance.project else ""
            ),  # Project name
            # Serialize the related employees for the frontend
            "interviewers": SimpleEmployeeSerializer(interviewers_list, many=True).data,
            "approvers": SimpleEmployeeSerializer(approvers_list, many=True).data,
            "recruiters": SimpleEmployeeSerializer(recruiters_list, many=True).data,
            "hiring_manager": SimpleEmployeeSerializer(hiring_manager_obj).data,
        }

        # Send the update to all clients connected to this form's WebSocket group
        async_to_sync(channel_layer.group_send)(
            form_group_name, {"type": "form_metadata_updated", "data": updated_data}
        )

        return form_instance

    def update(self, request, *args, **kwargs):
        """
        Updates the working form and returns the full detail representation.

        Delegates saving and WebSocket notification to `perform_update`, then
        reloads annotated topics for the response via `_get_form_topics_prefetch`.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        updated_instance = self.perform_update(serializer)

        prefetch_related_objects([updated_instance], self._get_form_topics_prefetch())

        detail_serializer = WorkingFormDetailSerializer(
            updated_instance, context=self.get_serializer_context()
        )

        return Response(detail_serializer.data)

    @action(detail=True, methods=["post"], url_path="add-topic")
    def add_topic(self, request, slug=None):
        """
        Add a new or existing topic to the working form.

        This action endpoint allows users to add topics to a working form in two ways:
        1. By referencing an existing topic via its ID: `{"id": <topic_pk>}`
        2. By creating a new topic with a name: `{"name": "Topic Name"}`

        After successfully adding the topic, a WebSocket notification is sent to
        all connected clients so they can update their UI in real-time.

        URL: POST /api/working-form/{slug}/add-topic/

        Args:
            request: The HTTP request
            slug: The slug of the working form

        Returns:
            Response: The serialized topic data with 201 Created status on success,
                     or 400 Bad Request with error details on failure
        """
        # Get the working form instance
        form = self.get_object()

        # Validate the input data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Call the service function to add the topic to the form
            new_form_topic = add_topic_to_working_form(form, serializer.validated_data)
        except ValidationError as e:
            # Return validation errors if any
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        # Prepare WebSocket notification
        channel_layer = get_channel_layer()  # Get the ASGI channel layer
        form_group_name = f"form_{form.id}"  # Channel group name for this form
        # Serialize the topic for the frontend
        topic_data = TopicSerializer(new_form_topic.topic).data

        # Send the notification to all connected clients
        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "topic_added",  # Event type that will be handled by the consumer
                "topic": topic_data,  # Topic data to be sent to clients
            },
        )

        # Return the created topic data with 201 Created status
        return Response(topic_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="restore-topic")
    def restore_topic(self, request, slug=None):
        """
        Retrieve a list of soft-deleted topics that can be restored.

        This endpoint returns all topics that have been soft-deleted from the
        working form. These topics can be restored through the WebSocket
        `toggle_topic_vote` action, which allows users to vote on restoring
        a topic.

        The endpoint uses the special `all_objects` manager which includes
        soft-deleted records, and adds annotations for vote counts and other
        metadata needed for the restoration UI.

        URL: GET /api/working-form/{slug}/restore-topic/

        Args:
            request: The HTTP request
            slug: The slug of the working form

        Returns:
            Response: A list of serialized soft-deleted topics with their metadata
        """
        # Get the working form instance
        form = self.get_object()

        # Query for soft-deleted topics using the all_objects manager
        # This manager includes records with is_removed=True
        deleted_topics = WorkingFormTopic.all_objects.get_annotated_list().filter(
            working_form=form,  # Filter to this form only
            is_removed=True,  # Only include removed topics
        )

        # Serialize the deleted topics for the response
        serializer = WorkingFormTopicListSerializer(
            deleted_topics, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, slug=None):
        """
        Add the current user's approval to the working form.

        This action allows a user to approve a working form, which is part of the
        form's approval workflow. When all approvers have approved the form, its
        status changes to APPROVED, making it available for creating evaluation forms.

        The endpoint handles these cases:
        - If the user has already approved the form, returns 'already_approved'
        - If this is a new approval, adds the user to approved_by and returns 'approval_added'
        - If all approvers have now approved, updates the form status to APPROVED

        After processing, a WebSocket notification is sent to all connected clients
        so they can update their UI in real-time.

        URL: POST /api/working-form/{slug}/approve/

        Args:
            request: The HTTP request
            slug: The slug of the working form

        Returns:
            Response: JSON with approval status, form status, and list of approvers
        """
        # Get the working form instance
        form = self.get_object()
        user = request.user

        # Check if the user has already approved this form
        approved_by_ids = {
            u.pk for u in form.approved_by.all()
        }  # Set of user IDs who approved
        user_has_approved = (
            user.pk in approved_by_ids
        )  # Whether this user already approved

        # Handle the approval action
        if user_has_approved:
            # User already approved - no changes needed
            action_result = "already_approved"
        else:
            # Add the user's approval
            form.approved_by.add(user)
            action_result = "approval_added"

        # Refresh related objects to ensure we have current data
        prefetch_related_objects([form], "approved_by", "approvers")

        # Check if the form is now fully approved (all approvers have approved)
        is_approved = form.is_fully_approved

        # Update the form status based on approval state
        if is_approved:
            form.status = WorkingForm.Status.APPROVED  # All approvers have approved
        else:
            form.status = (
                WorkingForm.Status.IN_PROGRESS
            )  # Still waiting for some approvals

        # Save the updated status
        form.save(update_fields=["status"])

        # Prepare response data
        response_data = {
            "action_result": action_result,  # What happened with this request
            "is_fully_approved": is_approved,  # Whether all approvers have approved
            "form_status": form.status,  # Current form status
            "approved_by": SimpleEmployeeSerializer(
                form.approved_by.all(), many=True
            ).data,  # List of users who approved
        }

        # Prepare WebSocket notification
        channel_layer = get_channel_layer()  # Get the ASGI channel layer
        form_group_name = f"form_{form.id}"  # Channel group name for this form

        # Send the notification to all connected clients
        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "approval_update",  # Event type that will be handled by the consumer
                "data": response_data,  # Approval data to be sent to clients
            },
        )

        # Return the approval data
        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unapprove")
    def unapprove(self, request, slug=None):
        """
        Revoke the current user's approval to allow further editing of the form.

        This action allows a user to withdraw their approval from a working form,
        which is necessary to make changes after approving. When any approval is
        withdrawn, the form's status is reset to IN_PROGRESS, allowing edits.

        The endpoint handles these cases:
        - If the form is already in progress and the user hasn't approved, returns early
        - If the user has approved, removes their approval
        - Always sets the form status to IN_PROGRESS

        After processing, a WebSocket notification is sent to all connected clients
        so they can update their UI in real-time.

        URL: POST /api/working-form/{slug}/unapprove/

        Args:
            request: The HTTP request
            slug: The slug of the working form

        Returns:
            Response: JSON with approval status, form status, and list of approvers
        """
        # Get the working form instance
        form = self.get_object()
        user = request.user

        # Check if the user has already approved this form
        approved_by_ids = {
            u.pk for u in form.approved_by.all()
        }  # Set of user IDs who approved
        user_has_approved = (
            user.pk in approved_by_ids
        )  # Whether this user already approved

        # If form is already in progress and user hasn't approved, nothing to do
        if form.status == WorkingForm.Status.IN_PROGRESS and not user_has_approved:
            return Response(
                {
                    "message": "Form is already in progress and you have not approved it."
                },
                status=status.HTTP_200_OK,
            )

        # Remove user's approval if they had approved
        if user_has_approved:
            form.approved_by.remove(user)

        # Always set form status to IN_PROGRESS when unapproving
        form.status = WorkingForm.Status.IN_PROGRESS  # Allow edits to the form
        form.save(update_fields=["status"])

        # Refresh related objects to ensure we have current data
        prefetch_related_objects([form], "approved_by")

        # Prepare response data
        response_data = {
            "action_result": "unapproved_for_edit",  # What happened with this request
            "is_fully_approved": False,  # Form is no longer fully approved
            "form_status": form.status,  # Current form status (IN_PROGRESS)
            "approved_by": SimpleEmployeeSerializer(
                form.approved_by.all(), many=True
            ).data,  # Updated list of users who approved
        }

        # Prepare WebSocket notification
        channel_layer = get_channel_layer()  # Get the ASGI channel layer
        form_group_name = f"form_{form.id}"  # Channel group name for this form

        # Send the notification to all connected clients
        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "approval_update",
                "data": response_data,
            },  # Same event type as approve
        )

        # Return the updated approval data
        return Response(response_data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="create-evaluation",
    )
    def create_evaluation_form(self, request, slug=None):
        """
        Create a new evaluation form from an approved working form.

        This action creates a concrete evaluation form that can be used in an
        actual interview. It takes an approved working form template and creates
        a new evaluation form instance with all the topics and questions from
        the working form, along with candidate and interview details.

        The endpoint requires:
        - The working form must be in APPROVED status
        - The user must have permission to create evaluations (recruiter or superuser)
        - Candidate and interview datetime must be provided

        URL: POST /api/working-form/{slug}/create-evaluation/

        Args:
            request: The HTTP request with candidate and interview details
            slug: The slug of the working form to create an evaluation from

        Returns:
            Response: The serialized evaluation form data with 201 Created status on success,
                     or 400 Bad Request with error details on failure
        """
        # Get the working form instance
        working_form = self.get_object()

        # Validate the input data (candidate, interview datetime)
        input_serializer = CreateEvaluationFormSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        # Process the validated data
        prepared_data = (
            input_serializer.save()
        )  # This doesn't save to DB, just prepares data

        try:
            # Call the service function to create the evaluation form
            # This deep-copies the form structure (topics, items, interviewers)
            evaluation_form = clone_working_to_evaluation(
                working_form=working_form, **prepared_data
            )
        except ValidationError as e:
            # Return validation errors if any
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        # Serialize the created evaluation form for the response
        output_serializer = RecruiterEvaluationSerializer(
            evaluation_form, context={"request": request}
        )

        # Return the created evaluation form data with 201 Created status
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="clone",
    )
    def clone(self, request, slug=None):
        """
        GET/POST /api/working-form/{slug}/clone/
        Clones the working form into a new instance.

        - **GET**: Returns pre-filled initial data (vacancy, level, project,
          interviewers, approvers, recruiters) from the original form.
        - **POST**: Validates input via `WorkingFormCreateSerializer` and
          creates a deep copy (topics, items) with the new metadata via
          the `clone_working_from_working` service.
        """
        original_form = self.get_object()

        if request.method == "GET":
            initial_data = {
                "vacancy": f"{original_form.vacancy} (Copy)",
                "level": original_form.level,
                "project": original_form.project_id,
                "interviewers": list(
                    original_form.interviewers.values_list("pk", flat=True)
                ),
                "approvers": list(original_form.approvers.values_list("pk", flat=True)),
                "recruiters": list(
                    original_form.recruiters.values_list("pk", flat=True)
                ),
                "hiring_manager_id": original_form.hiring_manager_id,
            }

            return Response(initial_data)

        # POST method
        context = self.get_serializer_context()

        serializer = self.get_serializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)

        try:
            new_form = clone_working_from_working(
                original_form=original_form,
                validated_data=serializer.validated_data,
            )
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = WorkingFormDetailSerializer(new_form, context=context)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class WorkingFormItemViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    A ViewSet for managing items (questions) within a working form.

    Provides list, detail, and update operations for `WorkingFormItem`
    instances that belong to a specific working form (resolved via the
    `working_form_slug` URL parameter).

    **Key features:**
    - Annotated queryset with delete vote counts and total approvers.
    - WebSocket notification on item updates.

    **Endpoints:**
    - `GET /api/working-form/{slug}/items/` — List items for the form.
    - `GET /api/working-form/{slug}/items/{pk}/` — Item details.
    - `PUT/PATCH /api/working-form/{slug}/items/{pk}/` — Update an item.
    """

    queryset = WorkingFormItem.objects.all()

    def get_permissions(self):
        """
        Determines access permissions based on the action.

        - `update`, `partial_update`: `IsAuthenticated` + `CanInteractWithWorkingForm`.
        - Default: `IsAuthenticated`.
        """
        if self.action in ["update", "partial_update"]:
            return [permissions.IsAuthenticated(), CanInteractWithWorkingForm()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Returns items belonging to the working form identified by `working_form_slug`.

        Uses the manager's `get_annotated_list()` to add `delete_votes` and
        `total_approvers` annotations.
        """
        return WorkingFormItem.objects.get_annotated_list().filter(
            form_topic__working_form__slug=self.kwargs["working_form_slug"],
        )

    def get_serializer_class(self):
        """Returns `WorkingFormItemSerializer` for all actions."""
        return WorkingFormItemSerializer

    def perform_update(self, serializer) -> dict:
        """
        Saves the item and broadcasts the update via WebSocket.

        After saving, reloads `deleted_by` for the response serializer and
        sends the serialized item data to the form's WebSocket group.
        Returns the serialized data dict for use by `update()`.
        """
        item = serializer.save()

        prefetch_related_objects([item], "deleted_by")

        item_data = WorkingFormItemSerializer(
            item, context={"request": self.request}
        ).data

        channel_layer = get_channel_layer()
        form_group_name = f"form_{item.form_topic.working_form.id}"

        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {"type": "handle_item_state_update", "data": item_data},
        )

        return item_data

    def update(self, request, *args, **kwargs):
        """
        Updates the item and returns already-serialized data from `perform_update`.

        Avoids double serialization by using the dict returned by `perform_update`
        directly in the response.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        serialized_data = self.perform_update(serializer)

        return Response(serialized_data)


class WorkingFormTopicViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A ViewSet for managing topics within a specific working form.

    Provides read-only access (list, detail) plus custom actions for adding
    questions and viewing soft-deleted items for restoration.

    **Key features:**
    - Annotated list with vote counts, question counts, and deletion candidates.
    - Detail view with prefetched items and their delete-vote annotations.
    - Adding questions to a topic with WebSocket notification.
    - Viewing soft-deleted items for restoration.

    **Endpoints:**
    - `GET /api/working-form/{slug}/topics/` — List topics for the form.
    - `GET /api/working-form/{slug}/topics/{pk}/` — Topic details with items.
    - `POST /api/working-form/{slug}/topics/{pk}/add-question/` — Add a question.
    - `GET /api/working-form/{slug}/topics/{pk}/restore-item/` — List soft-deleted items.
    """

    queryset = WorkingFormTopic.objects.all()

    @property
    def renderer_classes(self):
        """
        Show JSON and BrowsableAPIRenderer in DEBUG mode.
        Show only JSON in Production mode.
        """
        if settings.DEBUG:
            return [JSONRenderer, BrowsableAPIRenderer]
        return [JSONRenderer]

    def get_permissions(self):
        """
        Determines access permissions based on the action.

        - `add_question`, `restore_item`: `IsAuthenticated` + `CanInteractWithWorkingForm`.
        - Default: `IsAuthenticated`.
        """
        if self.action in ["add_question", "restore_item"]:
            return [permissions.IsAuthenticated(), CanInteractWithWorkingForm()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        """
        Selects the serializer class based on the current action.

        - `add_question`: `AddQuestionToTopicSerializer` for question input validation.
        - `retrieve`: `WorkingFormTopicDetailSerializer` for a full topic with items.
        - Default (`list`): `WorkingFormTopicListSerializer` for a concise list view.
        """
        if self.action == "add_question":
            return AddQuestionToTopicSerializer
        if self.action == "retrieve":
            return WorkingFormTopicDetailSerializer
        return WorkingFormTopicListSerializer

    def get_queryset(self):
        """
        Returns topics belonging to the working form identified by `working_form_slug`.

        Each action gets tailored prefetching:
        - `list`: annotated with vote counts, question counts, and deletion candidates.
        - `retrieve`: prefetches items with delete-vote annotations.
        - `add_question`: prefetches `working_form.approvers` and `approved_by`.
        - Default: selects related `working_form` and `topic`.
        """
        queryset = (
            super()
            .get_queryset()
            .filter(working_form__slug=self.kwargs["working_form_slug"])
            .select_related("topic")
        )

        if self.action == "list":

            return queryset.get_annotated_list()

        if self.action == "retrieve":

            return queryset.prefetch_related(
                Prefetch(
                    "items",
                    queryset=WorkingFormItem.objects.annotate(
                        delete_votes=Count("deleted_by", distinct=True),
                        total_approvers=Count(
                            "form_topic__working_form__approvers", distinct=True
                        ),
                    )
                    .prefetch_related("deleted_by")
                    .select_related("form_topic__working_form"),
                )
            )

        if self.action == "add_question":
            return queryset.select_related("working_form", "topic").prefetch_related(
                "working_form__approvers", "working_form__approved_by"
            )

        return queryset.select_related("working_form", "topic")

    @action(detail=True, methods=["post"], url_path="add-question")
    def add_question(self, request, working_form_slug=None, pk=None):
        """
        POST /api/working-form/{slug}/topics/{pk}/add-question/
        Adds a question to the topic.

        Accepts either `{"origin_question": <pk>}` to link an existing question,
        or `{"question_text": "...", "difficulty_snapshot": ...}` to create a new
        one. Reloads the item with annotations and broadcasts it via WebSocket.
        """
        form_topic = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            new_item = add_question_to_topic(
                form_topic, request.user, serializer.validated_data
            )
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            item_for_response = WorkingFormItem.objects.get_annotated_list().get(
                pk=new_item.pk
            )
        except WorkingFormItem.DoesNotExist:
            return Response(
                {"error": "Failed to reload created item."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        channel_layer = get_channel_layer()
        form_group_name = f"form_{form_topic.working_form.id}"

        item_data = WorkingFormItemSerializer(
            item_for_response, context={"request": request}
        ).data

        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "question_added",
                "question": item_data,
            },
        )

        return Response(item_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="restore-item")
    def restore_item(self, request, working_form_slug=None, pk=None):
        """
        GET /api/working-form/{slug}/topics/{pk}/restore-item/
        Returns a list of soft-deleted items for this topic.

        Uses `all_objects` manager to include removed items with annotations.
        Actual restoration is handled via the WebSocket `toggle_delete_vote` action.
        """
        form_topic = self.get_object()

        deleted_items = WorkingFormItem.all_objects.get_annotated_list().filter(
            form_topic=form_topic, is_removed=True
        )

        serializer = WorkingFormItemSerializer(
            deleted_items, many=True, context={"request": request}
        )
        return Response(serializer.data)
