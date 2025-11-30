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

    lookup_field = "slug"

    queryset = WorkingForm.objects.select_related("tech_stack", "hiring_manager")

    def get_serializer_class(self):
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

    def _get_form_topics_prefetch(self):
        """
        Return Prefetch-object for topics with annotations
        that counts in custom manager in nodel.
        """
        return Prefetch(
            "form_topics",
            queryset=WorkingFormTopic.objects.get_annotated_list()
            .filter(is_removed=False)
            .order_by("topic__name")
            .prefetch_related("items__deleted_by"),
        )

    def get_queryset(self):
        """
        Separate prefetch/annotate data for different actions:
        - list (annotate count approvers/interviewers)
        - retrieve (M2M relations)
        - update/partial_update/approve/add_topic (prefetch approvers/interviewers)
        to avoid conflicts (prefetch/annotate)
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
        Take instance with cashed data (interviewers/approvers),
        reloads prefetched topics and gives all data to serializer.
        """

        instance = self.get_object()

        prefetch_related_objects([instance], self._get_form_topics_prefetch())

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_update(self, serializer):
        """
        Take validated lists (from serializer) and use
        them in WebSocket message after saving (no cash)
        - Save instance,
        - RELOAD M2M-cash (for response in serializer in update)
        """

        form_instance = serializer.save()

        prefetch_related_objects(
            [form_instance], "interviewers", "approvers", "recruiters"
        )

        interviewers_list = serializer._interviewers_list
        approvers_list = serializer._approvers_list
        recruiters_list = serializer._recruiters_list
        hiring_manager_obj = serializer._hiring_manager_obj

        channel_layer = get_channel_layer()
        form_group_name = f"form_{form_instance.id}"
        updated_data = {
            "vacancy": form_instance.vacancy,
            "level": form_instance.get_level_display(),
            "project": form_instance.project,
            "interviewers": SimpleEmployeeSerializer(interviewers_list, many=True).data,
            "approvers": SimpleEmployeeSerializer(approvers_list, many=True).data,
            "recruiters": SimpleEmployeeSerializer(recruiters_list, many=True).data,
            "hiring_manager": SimpleEmployeeSerializer(hiring_manager_obj).data,
        }
        async_to_sync(channel_layer.group_send)(
            form_group_name, {"type": "form_metadata_updated", "data": updated_data}
        )

    def update(self, request, *args, **kwargs):
        """
        Update instance, with prefetched interviewers/approvers (from perform update)
        for response alive cashed topics (_get_form_topics_prefetch)
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
        POST: Adds a new or existing topic to the working form.
        Input: {"id": 1} OR {"name": "New Topic Name"}
        Send message to WebSocket about adding a new topic.
        """

        form = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            new_form_topic = add_topic_to_working_form(form, serializer.validated_data)
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        channel_layer = get_channel_layer()
        form_group_name = f"form_{form.id}"
        topic_data = TopicSerializer(new_form_topic.topic).data

        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "topic_added",
                "topic": topic_data,
            },
        )

        return Response(topic_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="restore-topic")
    def restore_topic(self, request, slug=None):
        """
        GET: Returns a list of soft-deleted topics for this form.
        Restoration is handled via WebSocket 'toggle_topic_vote' action.
        """
        form = self.get_object()

        deleted_topics = WorkingFormTopic.objects.get_annotated_list().filter(
            working_form=form, is_removed=True
        )

        serializer = WorkingFormTopicListSerializer(
            deleted_topics, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, slug=None):
        """
        POST: Approves WorkingForm instance by approvers.
        Check user in approvers list.
        Add the current user to the approved_by list and sets
        the form status to APPROVED.
        Send message to WebSocket about approve instance.
        """
        form = self.get_object()
        user = request.user

        approved_by_ids = {u.pk for u in form.approved_by.all()}
        user_has_approved = user.pk in approved_by_ids

        if user_has_approved:
            action_result = "already_approved"
        else:
            form.approved_by.add(user)
            action_result = "approval_added"

        prefetch_related_objects([form], "approved_by", "approvers")

        is_approved = form.is_fully_approved

        if is_approved:
            form.status = WorkingForm.Status.APPROVED
        else:
            form.status = WorkingForm.Status.IN_PROGRESS

        form.save(update_fields=["status"])

        response_data = {
            "action_result": action_result,
            "is_fully_approved": is_approved,
            "form_status": form.status,
            "approved_by": SimpleEmployeeSerializer(
                form.approved_by.all(), many=True
            ).data,
        }

        channel_layer = get_channel_layer()
        form_group_name = f"form_{form.id}"

        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {
                "type": "approval_update",
                "data": response_data,
            },
        )

        return Response(
            {"action_result": action_result, **response_data}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], url_path="unapprove")
    def unapprove(self, request, slug=None):
        """
        POST: Un-approves the Working Form instance to allow editing.
        Check user in approvers list.
        Removes the current user from the approved_by list and sets
        the form status back to IN_PROGRESS.
        Send message to WebSocket about approve instance.
        """
        form = self.get_object()
        user = request.user

        approved_by_ids = {u.pk for u in form.approved_by.all()}
        user_has_approved = user.pk in approved_by_ids

        if form.status == WorkingForm.Status.IN_PROGRESS and not user_has_approved:
            return Response(
                {
                    "message": "Form is already in progress and you have not approved it."
                },
                status=status.HTTP_200_OK,
            )

        if user_has_approved:
            form.approved_by.remove(user)

        form.status = WorkingForm.Status.IN_PROGRESS
        form.save(update_fields=["status"])

        prefetch_related_objects([form], "approved_by")

        response_data = {
            "action_result": "unapproved_for_edit",
            "is_fully_approved": False,
            "form_status": form.status,
            "approved_by": SimpleEmployeeSerializer(
                form.approved_by.all(), many=True
            ).data,
        }

        channel_layer = get_channel_layer()
        form_group_name = f"form_{form.id}"

        async_to_sync(channel_layer.group_send)(
            form_group_name,
            {"type": "approval_update", "data": response_data},
        )

        return Response(response_data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="create-evaluation",
    )
    def create_evaluation_form(self, request, slug=None):
        """
        Creates a new EvaluationForm from this (APPROVED) WorkingForm.
        """

        working_form = self.get_object()

        input_serializer = CreateEvaluationFormSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        prepared_data = input_serializer.save()

        try:
            evaluation_form = clone_working_to_evaluation(
                working_form=working_form, **prepared_data
            )
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = RecruiterEvaluationSerializer(
            evaluation_form, context={"request": request}
        )

        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="clone",
    )
    def clone(self, request, slug=None):
        """
        Clone WorkingForm.
        - GET: Return fields (WorkingFormCreateSerializer),
               filled data from 'original_form'.
        - POST: Take updated data, validate it, create deep copy with new data.
        """
        original_form = self.get_object()

        if request.method == "GET":
            initial_data = {
                "vacancy": f"{original_form.vacancy} (Copy)",
                "level": original_form.level,
                "project": original_form.project,
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

        elif request.method == "POST":
            context = self.get_serializer_context()
            context["request"] = request

            serializer = self.get_serializer(data=request.data, context=context)
            serializer.is_valid(raise_exception=True)

            try:
                new_form = clone_working_from_working(
                    original_form=original_form,
                    validated_data=serializer.validated_data,
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to clone form: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            output_serializer = WorkingFormDetailSerializer(new_form, context=context)
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)

        return Response(
            {"detail": "Method not allowed."}, status=status.HTTP_405_METHOD_NOT_ALLOWED
        )


class WorkingFormItemViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """ """

    queryset = WorkingFormItem.objects.select_related(
        "form_topic__working_form", "origin_question"
    ).prefetch_related("deleted_by")

    def get_permissions(self):
        if self.action in ["update", "partial_update"]:
            return [permissions.IsAuthenticated(), CanInteractWithWorkingForm()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Filter items to only those belonging to the specified working form.
        All optimization logic is now in the manager.
        """
        return WorkingFormItem.objects.get_annotated_list().filter(
            form_topic__working_form__slug=self.kwargs["working_form_slug"],
            is_removed=False,
        )

    def get_serializer_class(self):
        return WorkingFormItemSerializer

    def perform_update(self, serializer) -> dict:
        """
        Update WorkingFormItem instance.
        Send message to WebSocket about changed item.
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
        Proxies item data (dict), which return perform_update,
        and put it to response without double serialization
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        serialized_data = self.perform_update(serializer)

        return Response(serialized_data)


class WorkingFormTopicViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for interacting with topics within a specific WorkingForm.
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
        if self.action in ["add_question", "restore_item"]:
            return [permissions.IsAuthenticated(), CanInteractWithWorkingForm()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "add_question":
            return AddQuestionToTopicSerializer
        if self.action == "retrieve":
            return WorkingFormTopicDetailSerializer
        return WorkingFormTopicListSerializer

    def get_queryset(self):
        """
        Filter topics to only those belonging to the specified working form.
        """
        queryset = (
            super()
            .get_queryset()
            .filter(
                working_form__slug=self.kwargs["working_form_slug"], is_removed=False
            )
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
        POST: Add new question to the topic.
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
        GET: Returns a list of soft-deleted items for this topic.
        Restoration is handled via WebSocket 'toggle_delete_vote' action.
        """
        form_topic = self.get_object()

        deleted_items = WorkingFormItem.objects.get_annotated_list().filter(
            form_topic=form_topic, is_removed=True
        )

        serializer = WorkingFormItemSerializer(
            deleted_items, many=True, context={"request": request}
        )
        return Response(serializer.data)
