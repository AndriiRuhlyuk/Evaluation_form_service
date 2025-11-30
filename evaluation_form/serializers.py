from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

from evaluation_form.models import (
    EvaluationScore,
    EvaluationFormItem,
    EvaluationFeedback,
    EvaluationFormTopic,
    EvaluationForm,
    Candidate,
)


class CandidateFillSerializer(serializers.ModelSerializer):
    """Helper serializer for input candidate info."""

    class Meta:
        model = Candidate
        fields = ("full_name", "email", "pf_link")
        extra_kwargs = {
            "email": {"validators": [], "required": False, "allow_blank": True},
            "full_name": {"required": False, "allow_blank": True},
            "pf_link": {"required": False, "allow_blank": True},
        }


class CandidateListSerializer(serializers.ModelSerializer):
    """
    ListSerializer ONLY for list.
    """

    class Meta:
        model = Candidate
        fields = ("id", "full_name", "email", "pf_link")


class EvaluationHistorySerializer(serializers.ModelSerializer):
    """Helper serializer for showing list of passed interviews (evaluation forms)."""

    detail_url = serializers.SerializerMethodField()
    report_url = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationForm
        fields = (
            "id",
            "name",
            "status",
            "interview_datetime",
            "level_snapshot",
            "vacancy_snapshot",
            "detail_url",
            "report_url",
        )

    def get_detail_url(self, obj) -> str | None:
        """
        Generate absolute url =dor EvaluationForm Detail.
        """

        request = self.context.get("request")
        if not request:
            return None

        try:
            url_path = reverse(
                "evaluation_form:evaluation-form-detail",
                kwargs={"slug": obj.slug},
            )
            return request.build_absolute_uri(url_path)
        except Exception:
            return None

    def get_report_url(self, obj) -> str | None:
        """Return url HTML report"""

        request = self.context.get("request")
        if obj.report_file and request:
            return request.build_absolute_uri(obj.report_file.url)
        return None


class CandidateDetailSerializer(serializers.ModelSerializer):
    """Serializer for showing details of candidate and history of passed interviews."""

    evaluations = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = ("id", "full_name", "email", "pf_link", "evaluations")

    def get_evaluations(self, obj):
        """
        Return history, sorted by interview datetime.
        """

        qs = obj.evaluations.all().order_by("-interview_datetime")
        return EvaluationHistorySerializer(qs, many=True, context=self.context).data


class CreateEvaluationFormSerializer(serializers.Serializer):
    """
    Validates input data for creating an EvaluationForm.
    Allows pass ID current candidate or create a new one.
    """

    candidate_id = serializers.IntegerField(required=False, allow_null=True)
    candidate_data = CandidateFillSerializer(
        required=False, write_only=True, allow_null=True
    )
    interview_datetime = serializers.DateTimeField()

    def validate_interview_datetime(self, value):
        """
        Validate that interview_datetime is in the future.
        """
        if value and value <= timezone.now():
            raise serializers.ValidationError(
                "Interview date and time must be in the future."
            )
        return value

    def validate(self, data):
        """Validate that passed candidate_id or candidate_data"""
        candidate_id = data.get("candidate_id")
        candidate_data = data.get("candidate_data") or {}

        candidate_data = {key: value for key, value in candidate_data.items() if value}

        data["candidate_data"] = candidate_data

        if not candidate_id and not candidate_data:
            raise serializers.ValidationError("Provide candidate_id OR candidate_data.")

        if not candidate_id:
            email = candidate_data.get("email")
            full_name = candidate_data.get("full_name")
            pf_link = candidate_data.get("pf_link")

            if not email:
                raise serializers.ValidationError(
                    {"candidate_data": {"email": "This field is required."}}
                )

            email_exists = Candidate.objects.filter(email=email).exists()

            if not email_exists:
                if not full_name:
                    raise serializers.ValidationError(
                        {
                            "candidate_data": {
                                "full_name": "This field is required for new candidates."
                            }
                        }
                    )

                elif not pf_link:
                    raise serializers.ValidationError(
                        {
                            "candidate_data": {
                                "pf_link": "This field is required for new candidates."
                            }
                        }
                    )
            else:
                pass
        return data

    def create(self, validated_data):
        """
        Get or Create the Candidate object from 'candidate_data'.
        This serializer doesn't save the form, just prepares the data.
        """

        candidate_id = validated_data.pop("candidate_id", None)
        candidate_data = validated_data.pop("candidate_data", {})

        candidate = None

        if candidate_id:
            try:
                candidate = Candidate.objects.get(pk=candidate_id)
                if candidate_data:
                    for attr, value in candidate_data.items():
                        if value:
                            setattr(candidate, attr, value)
                    candidate.save()
            except Candidate.DoesNotExist:
                raise serializers.ValidationError(
                    f"Candidate with id {candidate_id} not found."
                )

        elif candidate_data:
            email = candidate_data.get("email")
            full_name = candidate_data.get("full_name")
            pf_link = candidate_data.get("pf_link", "")

            defaults = {"pf_link": pf_link}
            if full_name:
                defaults["full_name"] = full_name

            candidate, created = Candidate.objects.get_or_create(
                email=email,
                defaults=defaults,
            )

            if not created:
                updated = False
                if full_name and candidate.full_name != full_name:
                    candidate.full_name = full_name
                    updated = True
                if pf_link and candidate.pf_link != pf_link:
                    candidate.pf_link = pf_link
                    updated = True

                if updated:
                    candidate.save()

        validated_data["candidate"] = candidate

        return validated_data


class EvaluationFormUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an EvaluationForm.
    """

    candidate_full_name = serializers.CharField(source="candidate.full_name")
    candidate_email = serializers.EmailField(source="candidate.email")
    candidate_pf_link = serializers.URLField(source="candidate.pf_link")

    class Meta:
        model = EvaluationForm
        fields = (
            "candidate_full_name",
            "candidate_email",
            "candidate_pf_link",
            "interview_datetime",
        )

    def validate_interview_datetime(self, value):
        """
        Validate that interview_datetime is in the future.
        """
        if value <= timezone.now():
            raise serializers.ValidationError(
                "New interview date and time must be in the future."
            )
        return value

    def update(self, instance, validated_data):

        candidate_data = validated_data.pop("candidate", {})

        instance = super().update(instance, validated_data)

        if candidate_data:
            candidate = instance.candidate
            for attr, value in candidate_data.items():
                setattr(candidate, attr, value)

            candidate.save()

        return instance


class EvaluationScoreLiteSerializer(serializers.ModelSerializer):
    """
    Light serializer, for give ID and accept saving.
    """

    class Meta:
        model = EvaluationScore
        fields = ("id", "item", "score", "comment", "lacks_expertise")


class EvaluationScoreSerializer(serializers.ModelSerializer):

    item = serializers.PrimaryKeyRelatedField(queryset=EvaluationFormItem.objects.all())
    lacks_expertise = serializers.BooleanField(required=False)

    class Meta:
        model = EvaluationScore
        fields = (
            "id",
            "interviewer",
            "item",
            "score",
            "comment",
            "lacks_expertise",
        )

        read_only_fields = ("id", "interviewer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request:
            form_id = request.query_params.get("form_id")

            if form_id:
                self.fields["item"].queryset = EvaluationFormItem.objects.filter(
                    form_topic__evaluation_form_id=form_id
                )

    def validate(self, data):
        """
        Validate: can't mark "lacks_expertise=True" and put
        score in the same time.
        """
        if data.get("lacks_expertise") and data.get("score") is not None:
            raise serializers.ValidationError(
                "You cannot provide a score and also claim 'lack of expertise'."
            )
        return data


class EvaluationItemForRecruiterSerializer(serializers.ModelSerializer):

    scores = EvaluationScoreSerializer(many=True)

    class Meta:
        model = EvaluationFormItem
        fields = ("id", "text_snapshot", "scores")


class EvaluationFeedbackSerializer(serializers.ModelSerializer):

    interviewer_name = serializers.SerializerMethodField()
    feedback_detail = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationFeedback
        fields = (
            "id",
            "interviewer_name",
            "pros",
            "cons",
            "decision",
            "candidates_level",
            "is_submitted",
            "feedback_detail",
        )
        read_only_fields = ("id", "is_submitted", "feedback_detail")

    def get_interviewer_name(self, obj):
        request = self.context.get("request")
        if request and obj.interviewer == request.user:
            return f"{obj.interviewer.fullname} (You)"

        return obj.interviewer.fullname

    def get_feedback_detail(self, obj):
        """
        Generate URL to edit page feedback.
        """

        request = self.context.get("request")
        if not request or not obj.pk:
            return None

        try:
            url = reverse(
                "evaluation_form:evaluation-feedback-detail", kwargs={"pk": obj.pk}
            )
            return request.build_absolute_uri(url)
        except Exception:
            return None


class EvaluationTopicForRecruiterSerializer(serializers.ModelSerializer):
    items = EvaluationItemForRecruiterSerializer(many=True)

    class Meta:
        model = EvaluationFormTopic
        fields = ("id", "topic_name_snapshot", "items")


class RecruiterEvaluationSerializer(serializers.ModelSerializer):

    feedbacks = EvaluationFeedbackSerializer(many=True)
    topics = EvaluationTopicForRecruiterSerializer(
        many=True, source="form_topics", read_only=True
    )

    class Meta:
        model = EvaluationForm
        fields = (
            "id",
            "recruiters",
            "candidate",
            "interview_datetime",
            "vacancy_snapshot",
            "level_snapshot",
            "project_snapshot",
            "status",
            "topics",
            "feedbacks",
        )


class EmptySerializer(serializers.Serializer):
    """
    Empty serializer, for 'actions', that need only 'POST'.
    """

    pass


class EvaluationItemForInterviewerSerializer(serializers.ModelSerializer):

    my_score = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationFormItem
        fields = (
            "id",
            "text_snapshot",
            "my_score",
        )

    def get_my_score(self, item) -> int | None:
        """
        Do not make request item.scores.filter(interviewer=user)
        Read from cache 'my_scores_cache', that load ViewSet
        """

        if hasattr(item, "my_scores_cache") and item.my_scores_cache:
            return item.my_scores_cache[0].score
        return None


class EvaluationTopicForInterviewerSerializer(serializers.ModelSerializer):
    items = EvaluationItemForInterviewerSerializer(many=True)

    class Meta:
        model = EvaluationFormTopic
        fields = ("id", "topic_name_snapshot", "items")


class InterviewerEvaluationSerializer(serializers.ModelSerializer):
    my_feedback = serializers.SerializerMethodField()
    topics = EvaluationTopicForInterviewerSerializer(many=True, source="form_topics")
    scores_url = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationForm
        fields = (
            "id",
            "interview_datetime",
            "recruiters",
            "candidate",
            "status",
            "topics",
            "scores_url",
            "my_feedback",
        )

    def get_my_feedback(self, item) -> int | None:
        """
        Do not make request form.feedbacks.filter(interviewer=user)
        Read from cache 'my_feedback_cache', that load ViewSet
        Return serialized feedback object or empty dict
        """

        if hasattr(item, "my_feedback_cache") and item.my_feedback_cache:
            feedback_object = item.my_feedback_cache[0]
            return EvaluationFeedbackSerializer(
                feedback_object, context=self.context
            ).data
        return None

    def get_scores_url(self, item) -> str | None:
        """
        Generate url for list of scores, filtered by EvaluationForm instance.
        """

        request = self.context.get("request")
        if not request:
            return None

        try:
            url_path = reverse("evaluation_form:evaluation-score-list")
            full_url = request.build_absolute_uri(url_path)
            return f"{full_url}?form_id={item.pk}"
        except Exception:
            return None


class EvaluationFormListSerializer(serializers.ModelSerializer):

    detail_url = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationForm
        fields = ("id", "name", "status", "interview_datetime", "detail_url")

    def get_detail_url(self, obj: EvaluationForm) -> str | None:
        """
        Generate, URL to 'retrieve' for this EvaluationForm.
        """
        request = self.context.get("request")
        if not request:
            return None

        try:
            url = reverse(
                "evaluation_form:evaluation-form-detail", kwargs={"slug": obj.slug}
            )
        except Exception:
            return None

        return request.build_absolute_uri(url)


class EmptySerializer(serializers.Serializer):
    """
    Use for actions, which no need input data (only POST-request).
    """

    pass
