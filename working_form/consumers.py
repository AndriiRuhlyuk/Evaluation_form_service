import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import WorkingForm
from .services import toggle_topic_vote, toggle_item_vote


@database_sync_to_async
def get_status(form_id: int):
    """
    Async take form status
    """
    try:
        return WorkingForm.objects.get(pk=form_id).status
    except WorkingForm.DoesNotExist:
        return None


@database_sync_to_async
def is_user_staff(user) -> bool:
    """
    Async check if user is staff
    """

    return user.is_staff


@database_sync_to_async
def check_user_approval(form_id: int, user_pk: int) -> bool:
    """
    Chek that user approved working form.
    """
    return WorkingForm.objects.filter(pk=form_id, approved_by=user_pk).exists()


class WorkingFormConsumer(AsyncWebsocketConsumer):
    async def connect(self) -> None:
        """
        Take working form ID, add user to group chat.
        """

        self.form_id = self.scope["url_route"]["kwargs"]["form_id"]
        self.form_group_name = f"form_{self.form_id}"

        await self.channel_layer.group_add(self.form_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code) -> None:
        """
        Disconnect user with channel group
        """

        await self.channel_layer.group_discard(self.form_group_name, self.channel_name)

    async def receive(self, text_data) -> None:
        """
        Take message from user (frontend)
        Call async toggle_delete_vote function and
        send updated state all participants of chat.
        - param text_data: JSON data received from the websocket
        """

        data = json.loads(text_data)
        action = data.get("action")
        user = self.scope["user"]

        if action in ["toggle_delete_vote", "toggle_item_vote"]:
            is_staff = is_user_staff(user)

            if not is_staff:
                status = await get_status(form_id=self.form_id)
                if status == WorkingForm.Status.APPROVED:
                    await self.send_error(
                        "Changes are not allowed for an approved form."
                    )
                    return

                is_personally_approved = await check_user_approval(
                    self.form_id, user.pk
                )
                if is_personally_approved:
                    await self.send_error(
                        "You cannot vote on items/topics after you have approved the form."
                    )
                    return

        if action == "toggle_item_delete_vote":
            item_id = data.get("item_id")
            updated_item = await self._call_toggle_item_vote(item_id, user.pk)

            await self.channel_layer.group_send(
                self.form_group_name,
                {
                    "type": "handle.item.state.update",
                    "data": updated_item["data_for_client"],
                },
            )
        elif action == "toggle_topic_delete_vote":
            topic_id = data.get("topic_id")
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

    async def send_error(self, message: str):
        """Send standard error to client."""
        await self.send(text_data=json.dumps({"event": "error", "message": message}))

    async def form_metadata_updated(self, event) -> None:
        """
        Handle updated forms metadata and send it to client.
        """

        await self.send(
            text_data=json.dumps(
                {"event": "form_metadata_has_been_updated", "data": event["data"]}
            )
        )

    async def handle_item_state_update(self, event) -> None:
        """
        Final message for all browsers connected to channel group
        - param event: dict with type and state
        """

        await self.send(text_data=json.dumps(event["data"]))

    async def handle_topic_state_update(self, event) -> None:
        """
        Final message for all browsers connected to channel group
        - param event: dict with type and state
        """

        await self.send(text_data=json.dumps(event["data"]))

    async def topic_added(self, event):
        """
        Handles the 'topic_added' event from the channel layer and sends
        it to the client.
        """
        topic_data = event["topic"]

        await self.send(
            text_data=json.dumps({"event": "new_topic_added", "topic": topic_data})
        )

    async def question_added(self, event):
        """
        Handles the 'question_added' event from the channel layer and sends
        it to the client.
        """
        item_data = event["question"]

        await self.send(
            text_data=json.dumps({"event": "new_item_added", "item": item_data})
        )

    async def approval_update(self, event):
        """
        Handles update status approve and sends it to client.
        """
        await self.send(
            text_data=json.dumps(
                {"event": "approval_status_updated", "data": event["data"]}
            )
        )

    @database_sync_to_async
    def _call_toggle_topic_vote(
        self, form_id: int, topic_id: int, user_id: int
    ) -> dict:
        return toggle_topic_vote(form_id, topic_id, user_id)

    @database_sync_to_async
    def _call_toggle_item_vote(self, item_id: int, user_id: int) -> dict:
        return toggle_item_vote(item_id, user_id)
