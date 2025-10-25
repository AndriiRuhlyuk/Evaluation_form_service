from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.urls import reverse

from question.models import Question
from working_form.custom_fields import M2MListField
from working_form.models import WorkingForm, WorkingFormItem, WorkingFormTopic


Employee = get_user_model()


class SimpleEmployeeSerializer(serializers.ModelSerializer):
    """Helper serializer for displaying user info."""

    class Meta:
        model = Employee
        fields = (
            "email",
            "fullname",
        )


class WorkingFormCreateSerializer(serializers.Serializer):
    """
    Validates input data (User IDs) for creating a WorkingForm.
    Optimized to use only ONE database query to fetch all users.
    """

    vacancy = serializers.CharField(max_length=500)
    level = serializers.ChoiceField(choices=WorkingForm.Level.choices)
    project = serializers.CharField(max_length=255, required=False, allow_blank=True)

    interviewers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=True
    )
    approvers = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        min_length=1,
        error_messages={
            "min_length": "At least one approver is required.",
            "empty": "At least one approver is required.",
        },
    )

    class Meta:
        fields = ("vacancy", "level", "project", "interviewers", "approvers")

    def validate(self, data):
        """
        1. Validates that approvers are a subset of interviewers.
        2. Fetches all users in a single query (only interviewers cose approvers is subset of interviewers).
        3. Replaces user IDs with user objects in validated_data.
        """
        interviewer_ids = data.get("interviewers", [])
        approver_ids = data.get("approvers", [])

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

        interviewer_id_set = set(interviewer_ids)
        approver_id_set = set(approver_ids)

        if not approver_id_set.issubset(interviewer_id_set):
            raise serializers.ValidationError(
                "All approvers must also be listed as interviewers."
            )

        all_ids_to_fetch = list(interviewer_id_set)

        if not all_ids_to_fetch:
            data["interviewers"] = []
            data["approvers"] = []
            return data

        users = Employee.objects.filter(pk__in=all_ids_to_fetch)

        user_map = {user.id: user for user in users}

        if len(users) != len(all_ids_to_fetch):
            missing_ids = all_ids_to_fetch - set(user_map.keys())
            raise serializers.ValidationError(
                f"The following user IDs were not found: {missing_ids}"
            )

        data["interviewers"] = [user_map[id] for id in interviewer_ids]
        data["approvers"] = [user_map[id] for id in approver_ids]

        return data


class WorkingFormUpdateSerializer(serializers.ModelSerializer):
    """
    Validates the input data for updating a WorkingForm from.
    """

    vacancy = serializers.CharField(max_length=500)
    level = serializers.ChoiceField(choices=WorkingForm.Level.choices)
    project = serializers.CharField(max_length=255, required=False, allow_blank=True)
    interviewers = M2MListField(required=False)
    approvers = M2MListField(required=False)

    class Meta:
        model = WorkingForm
        fields = (
            "name",
            "vacancy",
            "level",
            "project",
            "interviewers",
            "approvers",
        )

    def validate(self, data):
        """
        Validate all IDs by one request:
        - Check thst lists are empty
        - Take unique IDs
        - Teke objects by IDs + validation
        - return data (with replacement integers to objects)
        """
        interviewer_ids = data.get("interviewers", [])
        approver_ids = data.get("approvers", [])

        if "approvers" in data and not approver_ids:
            raise serializers.ValidationError(
                {"approvers": "At least one approver is required."}
            )
        if "interviewers" in data and not interviewer_ids:
            raise serializers.ValidationError(
                {"interviewers": "At least one interviewer is required."}
            )

        all_ids = set(interviewer_ids) | set(approver_ids)

        if all_ids:

            users = Employee.objects.filter(pk__in=all_ids)
            user_map = {user.id: user for user in users}

            if len(users) != len(all_ids):
                missing_ids = all_ids - set(user_map.keys())
                raise serializers.ValidationError(f"Users not found: {missing_ids}")

            if "interviewers" in data:
                data["interviewers"] = [user_map[id] for id in interviewer_ids]
            if "approvers" in data:
                data["approvers"] = [user_map[id] for id in approver_ids]

        final_interviewers = data.get(
            "interviewers", list(self.instance.interviewers.all())
        )
        final_approvers = data.get("approvers", list(self.instance.approvers.all()))
        final_interviewer_ids = {user.id for user in final_interviewers}
        final_approver_ids = {user.id for user in final_approvers}

        if not final_approver_ids.issubset(final_interviewer_ids):
            raise serializers.ValidationError(
                "All approvers must also be listed as interviewers."
            )

        return data

    def update(self, instance, validated_data):
        """
        - Take new data (interviewers/approvers)
        - Teke old data (before save/ remove) - Prefetched
        - Send old or new data (depends updated data) to WebSocket in update method in View
        - Update M2M fields (interviewers/approvers)
        """

        new_interviewers = validated_data.pop("interviewers", None)
        new_approvers = validated_data.pop("approvers", None)

        old_interviewers = list(self.instance.interviewers.all())
        old_approvers = list(self.instance.approvers.all())

        self._interviewers_list = (
            new_interviewers if new_interviewers is not None else old_interviewers
        )
        self._approvers_list = (
            new_approvers if new_approvers is not None else old_approvers
        )

        instance = super().update(instance, validated_data)
        if new_interviewers is not None:
            old_ids = {user.id for user in old_interviewers}
            new_ids = {user.id for user in new_interviewers}

            to_add_ids = new_ids - old_ids
            to_remove_ids = old_ids - new_ids

            if to_add_ids:
                instance.interviewers.add(*to_add_ids)
            if to_remove_ids:
                instance.interviewers.remove(*to_remove_ids)

        if new_approvers is not None:
            old_ids = {user.id for user in old_approvers}
            new_ids = {user.id for user in new_approvers}

            to_add_ids = new_ids - old_ids
            to_remove_ids = old_ids - new_ids

            if to_add_ids:
                instance.approvers.add(*to_add_ids)
            if to_remove_ids:
                instance.approvers.remove(*to_remove_ids)

        return instance


class WorkingFormListSerializer(serializers.ModelSerializer):
    """Serializer for List WorkingForm instances."""

    tech_stack = serializers.StringRelatedField()
    working_form_detail_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkingForm
        fields = (
            "id",
            "name",
            "tech_stack",
            "status",
            "working_form_detail_url",
        )

    def get_working_form_detail_url(self, instance):
        """
        Generate URL for instance detail view.
        """

        request = self.context.get("request")
        if not request:
            return None

        kwargs = {"slug": instance.slug}
        view_name = "working_form:working-form-detail"

        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class WorkingFormTopicListSerializer(serializers.ModelSerializer):
    """
    Serializer for a topic list within the main WorkingForm detail view.
    Used in WorkingFormDetailSerializer (topic field)
    """

    id = serializers.IntegerField(source="topic.id", read_only=True)
    name = serializers.CharField(source="topic.name", read_only=True)

    delete_votes = serializers.IntegerField(source="topic_delete_votes", read_only=True)
    is_effectively_deleted = serializers.SerializerMethodField()

    question_count = serializers.IntegerField(source="questions_count", read_only=True)
    detail_url = serializers.SerializerMethodField()
    candidates_for_deletion_count = serializers.IntegerField(
        source="candidate_for_deletion_count", read_only=True
    )

    class Meta:
        model = WorkingFormTopic
        fields = (
            "id",
            "name",
            "delete_votes",
            "is_effectively_deleted",
            "question_count",
            "detail_url",
            "candidates_for_deletion_count",
        )

    def get_is_effectively_deleted(self, instance: WorkingFormTopic) -> bool:
        """
        Calculates deleted satus for topic.
        Use prefetch data or instance property
        """

        if not hasattr(instance, "total_approvers_annotated"):
            return instance.is_effectively_deleted

        return instance._calculate_effective_deletion(
            total_approvers=instance.total_approvers_annotated,
            delete_votes=instance.topic_delete_votes,
        )

    def get_detail_url(self, instance):
        """
        Generate URL for instance detail view.
        """
        request = self.context.get("request")
        if not request:
            return None

        return request.build_absolute_uri(
            reverse(
                "working_form:working-form-topics-detail",
                kwargs={
                    "working_form_slug": instance.working_form.slug,
                    "pk": instance.pk,
                },
            )
        )


class WorkingFormDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for single instance WorkingForm,
    including all topics.
    """

    tech_stack = serializers.StringRelatedField(read_only=True)
    interviewers = SimpleEmployeeSerializer(many=True, read_only=True)
    approvers = SimpleEmployeeSerializer(many=True, read_only=True)
    topics = WorkingFormTopicListSerializer(
        source="form_topics", many=True, read_only=True
    )
    is_fully_approved = serializers.SerializerMethodField()

    class Meta:
        model = WorkingForm
        fields = (
            "id",
            "name",
            "status",
            "tech_stack",
            "topics",
            "created_at",
            "interviewers",
            "approvers",
            "is_fully_approved",
        )

    def get_is_fully_approved(self, instance: WorkingForm) -> bool:
        """
        Calculates approval status using pre-fetched data.
        """

        approvers_count = len(instance.approvers.all())

        if approvers_count == 0:
            return False

        approved_by_count = len(instance.approved_by.all())

        return approved_by_count >= approvers_count


class WorkingFormItemSerializer(serializers.ModelSerializer):
    """
    Serializer for a single item within a WorkingForm.
    Displays the state of deletion votes.
    """

    detail_url = serializers.SerializerMethodField()
    delete_votes = serializers.IntegerField(read_only=True)
    is_effectively_deleted = serializers.SerializerMethodField()
    voted_by_current_user = serializers.SerializerMethodField()
    difficulty = serializers.CharField(
        source="get_difficulty_snapshot_display", read_only=True
    )
    difficulty_snapshot = serializers.ChoiceField(
        choices=WorkingFormItem.Difficulty.choices, write_only=True, required=False
    )

    class Meta:
        model = WorkingFormItem
        fields = (
            "id",
            "text_snapshot",
            "difficulty",
            "difficulty_snapshot",
            "delete_votes",
            "is_effectively_deleted",
            "voted_by_current_user",
            "source_snapshot",
            "detail_url",
        )

    def update(self, instance, validated_data):
        """
        If 'text_snapshot' is updated,
        automatically set 'source_snapshot' to 'CHANGED'.
        """

        if "text_snapshot" in validated_data:
            validated_data["source_snapshot"] = Question.QuestionSource.CHANGED

        return super().update(instance, validated_data)

    def get_is_effectively_deleted(self, instance: WorkingFormItem) -> bool:
        """
        Calculates deleted satus for item.
        Use prefetch data or instance property
        """

        if not hasattr(instance, "total_approvers"):
            return instance.is_effectively_deleted

        return instance._calculate_effective_deletion(
            total_approvers=instance.total_approvers, delete_votes=instance.delete_votes
        )

    def get_voted_by_current_user(self, instance) -> bool:
        """
        Return True if user has voted for delete this item, else False.
        """

        user = self.context.get("request").user
        if not user or user.is_anonymous:
            return False
        prefetched_users = instance.deleted_by.all()
        user_ids_who_voted = {u.id for u in prefetched_users}

        return user.id in user_ids_who_voted

    def get_detail_url(self, instance: WorkingFormItem):
        """
        Generate URL for instance detail view.
        """
        request = self.context.get("request")
        if not request:
            return None

        kwargs = {
            "working_form_slug": instance.form_topic.working_form.slug,
            "pk": instance.pk,
        }

        view_name = "working_form:working-form-items-detail"

        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))


class WorkingFormTopicDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single topic, including all its questions.
    """

    questions = serializers.SerializerMethodField()

    class Meta:
        model = WorkingFormTopic
        fields = ("questions",)

    def get_questions(self, instance: WorkingFormTopic):
        """
        Teke WorkingForm Topic instance and redirect items from
        prefetched cash, to WorkingFormItemSerializer.
        """

        active_items = [item for item in instance.items.all() if not item.is_removed]

        return WorkingFormItemSerializer(
            active_items, many=True, context=self.context
        ).data


class AddQuestionToTopicSerializer(serializers.Serializer):
    """
    Serializer for adding a question to a topic.
    Used in add_question (WorkingFormTopicViewSet).
    """

    origin_question = serializers.IntegerField(required=False)
    question_text = serializers.CharField(required=False)
    difficulty_snapshot = serializers.ChoiceField(
        choices=WorkingFormItem.Difficulty.choices, required=False
    )

    def validate(self, data):
        is_existing = "origin_question" in data
        is_new = "question_text" in data and "difficulty_snapshot" in data
        if not is_existing and not is_new:
            raise serializers.ValidationError(
                "Provide either 'origin_question' or both 'question_text' and 'difficulty'."
            )
        return data


class AddTopicSerializer(serializers.Serializer):
    """
    Serializer for adding topic to working form.
    Used in add_topic action (WorkingFormViewSet).
    """

    id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get("id") and not data.get("name"):
            raise serializers.ValidationError(
                "Either 'id' or 'name' must be provided for a topic."
            )
        return data
