import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import models
from rest_framework.exceptions import ValidationError

from .models import WorkingForm
from .services import toggle_topic_vote, toggle_item_vote

logger = logging.getLogger(__name__)


class WorkingFormConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time collaboration on working forms.

    This consumer handles WebSocket connections for collaborative editing and
    voting on working forms. It manages user authentication, access control,
    and real-time updates between all connected clients.

    The consumer implements a pub/sub pattern where clients can send actions
    (like voting) and receive updates when any client makes changes to the form.
    """

    async def connect(self) -> None:
        """
        Handle WebSocket connection establishment.

        This method:
        1. Extracts the working form ID from the URL route
        2. Validates that the user is authenticated and has access to the form
        3. Adds the user to the form's channel group for real-time updates
        4. Accepts the connection if all checks pass

        If the user is anonymous or doesn't have access to the form, the
        connection is closed immediately.
        """
        # Extract form ID from URL parameters
        self.form_id = self.scope["url_route"]["kwargs"]["form_id"]
        # Create a unique channel group name for this form
        self.form_group_name = f"form_{self.form_id}"

        # Get the user from the connection scope
        user = self.scope.get("user")
        logger.debug("WebSocket CONNECT: user=%s, form_id=%s", user, self.form_id)

        # Reject connection if user is not authenticated
        if not user or user.is_anonymous:
            await self.close()
            return

        # Check if user has access to this form
        has_access = await self._check_user_access(self.form_id, user)
        if not has_access:
            await self.close()
            return

        # Add user to the form's channel group
        await self.channel_layer.group_add(self.form_group_name, self.channel_name)
        # Accept the WebSocket connection
        await self.accept()

    async def disconnect(self, close_code) -> None:
        """
        Handle WebSocket disconnection.

        This method removes the user from the form's channel group when
        they disconnect, ensuring they no longer receive updates for this form.

        Args:
            close_code: The WebSocket close code
        """
        # Get the form group name if it exists
        form_group_name = getattr(self, "form_group_name", None)
        # If we have a group name, remove this channel from it
        if form_group_name:
            await self.channel_layer.group_discard(form_group_name, self.channel_name)

    async def receive(self, text_data: str) -> None:
        """
        Process incoming WebSocket messages from clients.

        This method handles messages from the frontend, particularly for
        voting on items/topics deletion. It:
        1. Parses the JSON message
        2. Validates user permissions
        3. Processes the requested action
        4. Broadcasts updates to all connected clients

        Args:
            text_data: JSON string containing the client message
        """
        # Parse the JSON data from the client
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON.")
            return

        # Extract the requested action and user
        action = data.get(
            "action"
        )  # The action to perform (e.g., toggle_item_delete_vote)
        user = self.scope["user"]  # The authenticated user making the request

        # Log the received action and user
        logger.debug("WebSocket RECEIVE: action=%s, user=%s", action, user.pk)

        if action in ["toggle_item_delete_vote", "toggle_topic_delete_vote"]:
            if not user or user.is_anonymous:
                await self.send_error("Authentication required.")
                return

            ctx = await self._get_vote_context(self.form_id, user)
            if ctx is None:
                await self.send_error("Form does not exist.")
                return

            if not (ctx["is_approver"] or ctx["is_superuser"]):
                await self.send_error(
                    "You must be an Approver or Recruiter to make changes."
                )
                return

            if ctx["status"] == WorkingForm.Status.APPROVED:
                await self.send_error(
                    "Changes are not allowed for an approved form. Please un-approve it first."
                )
                return
            if ctx["is_personally_approved"]:
                await self.send_error(
                    "You cannot vote on items/topics after you have approved the form."
                )
                return

        try:
            if action == "toggle_item_delete_vote":
                item_id = data.get("item_id")
                if not item_id:
                    await self.send_error("Missing 'item_id'.")
                    return

                # ✅ ЛОГУВАННЯ перед викликом
                logger.debug(
                    "Calling toggle_item_vote: item_id=%s, user_pk=%s", item_id, user.pk
                )

                updated_item = await self._call_toggle_item_vote(item_id, user.pk)

                # ✅ ЛОГУВАННЯ результату
                logger.debug(
                    "toggle_item_vote result: %s", updated_item["data_for_client"]
                )

                await self.channel_layer.group_send(
                    self.form_group_name,
                    {
                        "type": "handle.item.state.update",
                        "data": updated_item["data_for_client"],
                    },
                )
            elif action == "toggle_topic_delete_vote":
                topic_id = data.get("topic_id")
                if not topic_id:
                    await self.send_error("Missing 'topic_id'.")
                    return

                form_id = self.form_id
                updated_topic = await self._call_toggle_topic_vote(
                    form_id, topic_id, user.pk
                )

                await self.channel_layer.group_send(
                    self.form_group_name,
                    {
                        "type": "handle.topic.state.update",
                        "data": updated_topic["data_for_client"],
                    },
                )
            else:
                await self.send_error(f"Unknown action: {action}")
        except ValidationError as e:
            await self.send_error(str(e.detail[0]) if hasattr(e, "detail") else str(e))
        except Exception:
            logger.exception("Unexpected error in WorkingFormConsumer.receive")
            await self.send_error("An internal error occurred.")

    async def send_error(self, message: str):
        """
        Send a standardized error message to the client.

        This utility method formats error messages in a consistent structure
        that the frontend can easily parse and display.

        Args:
            message: The error message to send to the client
        """
        await self.send(text_data=json.dumps({"event": "error", "message": message}))

    async def form_metadata_updated(self, event) -> None:
        """
        Handle form metadata update events and forward to the client.

        This method is called when form metadata (vacancy, level, project, etc.)
        has been updated by any user. It forwards the updated data to all
        connected clients for this form.

        Args:
            event: Dict containing the updated form metadata
        """
        await self.send(
            text_data=json.dumps(
                {"event": "form_metadata_has_been_updated", "data": event["data"]}
            )
        )

    async def handle_item_state_update(self, event) -> None:
        """
        Forward item state updates to connected clients.

        This method is called when an item's state (e.g., delete votes) has changed.
        It broadcasts the updated item data to all clients connected to this form.

        Args:
            event: Dict containing the updated item data
        """
        await self.send(text_data=json.dumps(event["data"]))

    async def handle_topic_state_update(self, event) -> None:
        """
        Forward topic state updates to connected clients.

        This method is called when a topic's state (e.g., delete votes) has changed.
        It broadcasts the updated topic data to all clients connected to this form.

        Args:
            event: Dict containing the updated topic data
        """
        await self.send(text_data=json.dumps(event["data"]))

    async def topic_added(self, event):
        """
        Handle topic addition events and forward to clients.

        This method is called when a new topic has been added to the form.
        It notifies all connected clients about the new topic so they can
        update their UI accordingly.

        Args:
            event: Dict containing the new topic data
        """
        # Extract the topic data from the event
        topic_data = event["topic"]

        # Send the new topic notification to the client
        await self.send(
            text_data=json.dumps({"event": "new_topic_added", "topic": topic_data})
        )

    async def question_added(self, event):
        """
        Handle question addition events and forward to clients.

        This method is called when a new question (item) has been added to a topic.
        It notifies all connected clients about the new question so they can
        update their UI accordingly.

        Args:
            event: Dict containing the new question data
        """
        # Extract the question (item) data from the event
        item_data = event["question"]

        # Send the new question notification to the client
        await self.send(
            text_data=json.dumps({"event": "new_item_added", "item": item_data})
        )

    async def approval_update(self, event):
        """
        Handle form approval status updates and forward to clients.

        This method is called when a form's approval status changes (e.g., a user
        approves or unapproves the form). It notifies all connected clients about
        the updated approval status.

        Args:
            event: Dict containing the updated approval status data
        """
        # Send the approval status update to the client
        await self.send(
            text_data=json.dumps(
                {"event": "approval_status_updated", "data": event["data"]}
            )
        )

    @database_sync_to_async
    def _call_toggle_topic_vote(
        self, form_id: int, topic_id: int, user_id: int
    ) -> dict:
        """
        Call the toggle_topic_vote service function asynchronously.

        This method bridges the async WebSocket world with the sync Django ORM
        by using database_sync_to_async to safely call the database operation.

        Args:
            form_id: ID of the working form
            topic_id: ID of the topic to toggle vote on
            user_id: ID of the user casting the vote

        Returns:
            dict: Result data including the updated topic state
        """
        return toggle_topic_vote(form_id, topic_id, user_id)

    @database_sync_to_async
    def _call_toggle_item_vote(self, item_id: int, user_id: int) -> dict:
        """
        Call the toggle_item_vote service function asynchronously.

        This method bridges the async WebSocket world with the sync Django ORM
        by using database_sync_to_async to safely call the database operation.

        Args:
            item_id: ID of the item to toggle vote on
            user_id: ID of the user casting the vote

        Returns:
            dict: Result data including the updated item state
        """
        return toggle_item_vote(item_id, user_id)

    @database_sync_to_async
    def _check_user_access(self, form_id: int, user) -> bool:
        """
        Check if a user has access to a specific working form.

        A user has access if they are:
        1. A superuser, or
        2. An approver, recruiter, interviewer, or hiring manager for the form

        Args:
            form_id: ID of the working form to check access for
            user: The user object to check permissions for

        Returns:
            bool: True if the user has access, False otherwise
        """
        # Superusers have access to all forms that exist
        if user.is_superuser:
            return WorkingForm.objects.filter(pk=form_id).exists()

        # Regular users need to be associated with the form in some role
        return (
            WorkingForm.objects.filter(pk=form_id)
            .filter(
                models.Q(approvers=user.pk)  # User is an approver
                | models.Q(recruiters=user.pk)  # User is a recruiter
                | models.Q(interviewers=user.pk)  # User is an interviewer
                | models.Q(hiring_manager=user.pk)  # User is the hiring manager
            )
            .exists()
        )

    @database_sync_to_async
    def _get_vote_context(self, form_id: int, user) -> dict:
        """
        Fetch all permission and status data needed for vote validation in a single call.

        This method efficiently gathers all the context needed to validate if a user
        can vote on items/topics in a form, avoiding multiple database queries.

        Args:
            form_id: ID of the working form
            user: The user object to check permissions for

        Returns:
            dict: Context data with status and permission flags, or None if form doesn't exist
        """
        try:
            # Get the form instance
            form = WorkingForm.objects.get(pk=form_id)
        except WorkingForm.DoesNotExist:
            return None

        # Return a dictionary with all relevant permission flags
        return {
            "status": form.status,  # Current form status (e.g., APPROVED, IN_PROGRESS)
            "is_superuser": user.is_superuser,  # Whether user is a superuser
            "is_approver": form.approvers.filter(
                pk=user.pk
            ).exists(),  # Whether user is an approver
            "is_personally_approved": form.approved_by.filter(
                pk=user.pk
            ).exists(),  # Whether user has approved the form
        }
