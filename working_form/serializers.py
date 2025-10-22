from django.contrib.auth.models import User
from rest_framework import serializers
from django.urls import reverse

from working_form.models import WorkingForm, WorkingFormItem, WorkingFormTopic


class SimpleUserSerializer(serializers.ModelSerializer):
    """Helper serializer for displaying user info."""

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name")


class WorkingFormCreateSerializer(serializers.Serializer):
    """
    Validates the input data for creating a WorkingForm from a template.
    """

    vacancy = serializers.CharField(max_length=500)
    level = serializers.ChoiceField(choices=WorkingForm.Level.choices)
    project = serializers.CharField(max_length=255, required=False, allow_blank=True)
    interviewers = serializers.SlugRelatedField(
        slug_field="username", queryset=User.objects.all(), many=True, required=False
    )
    approvers = serializers.SlugRelatedField(
        slug_field="username",
        queryset=User.objects.all(),
        many=True,
    )

    class Meta:
        fields = ("vacancy", "level", "project", "interviewers", "approvers")

    def validate_interviewers(self, value):
        ids = [user.id for user in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "Interviewers must be unique. Please remove any duplicates."
            )
        return value

    def validate(self, data):
        """
        Checks that all approvers are also in the interviewers list.
        """

        interviewers = data.get("interviewers", [])
        approvers = data.get("approvers", [])

        interviewer_ids = {user.id for user in interviewers}
        approver_ids = {user.id for user in approvers}

        if not approver_ids.issubset(interviewer_ids):
            raise serializers.ValidationError(
                "All approvers must also be listed as interviewers."
            )

        if not approvers:
            raise serializers.ValidationError("At least one approver is required.")

        return data


class WorkingFormUpdateSerializer(serializers.ModelSerializer):
    """
    Validates the input data for updating a WorkingForm from.
    """

    vacancy = serializers.CharField(max_length=500)
    level = serializers.ChoiceField(choices=WorkingForm.Level.choices)
    project = serializers.CharField(max_length=255, required=False, allow_blank=True)
    interviewers = serializers.SlugRelatedField(
        slug_field="username", queryset=User.objects.all(), many=True, required=False
    )
    approvers = serializers.SlugRelatedField(
        slug_field="username", queryset=User.objects.all(), many=True, required=False
    )

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
        Ensures that approvers are a subset of interviewers during an update.
        Handles partial updates where only one of the fields might be provided.
        """

        interviewers = data.get("interviewers", self.instance.interviewers.all())
        approvers = data.get("approvers", self.instance.approvers.all())

        self._interviewers_list = list(interviewers)
        self._approvers_list = list(approvers)

        interviewer_ids = {user.id for user in self._interviewers_list}
        approver_ids = {user.id for user in self._approvers_list}

        if not approver_ids.issubset(interviewer_ids):
            raise serializers.ValidationError(
                "All approvers must also be listed as interviewers."
            )

        if "approvers" in data and not self._approvers_list:
            raise serializers.ValidationError("At least one approver is required.")

        if "interviewers" in data and not self._interviewers_list:
            raise serializers.ValidationError("At least one interviewer is required.")

        return data


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
    interviewers = SimpleUserSerializer(many=True, read_only=True)
    approvers = SimpleUserSerializer(many=True, read_only=True)
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
