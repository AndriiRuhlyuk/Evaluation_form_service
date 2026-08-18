from django.db import IntegrityError  # For handling database constraint violations
from django.urls import reverse, NoReverseMatch  # For generating URLs to views
from django.utils import timezone  # For handling datetime operations
from rest_framework import serializers  # Base serializer classes

from evaluation_form.models import (
    EvaluationScore,  # Model for storing scores given by interviewers (e.g., score=4, comment="Good knowledge")
    EvaluationFormItem,  # Model for evaluation items/questions (e.g., "Explain REST API principles")
    EvaluationFeedback,  # Model for storing interviewer feedback (e.g., pros="Good communication", cons="Lacks experience")
    EvaluationFormTopic,  # Model for grouping evaluation items by topic (e.g., "Python", "Databases")
    EvaluationForm,  # Main model for evaluation forms (e.g., "Python Developer Interview - Junior")
    Candidate,  # Model for candidate information (e.g., full_name="John Doe", email="john@example.com")
)


class CandidateFillSerializer(serializers.ModelSerializer):
    """Helper serializer for input candidate info."""

    # Used for creating or updating candidate information
    # Example input data: {"full_name": "John Doe", "email": "john@example.com", "pf_link": "https://platform.com/johndoe"}

    class Meta:
        model = Candidate  # Uses the Candidate model
        fields = ("full_name", "email", "pf_link")  # Fields to include in serialization
        extra_kwargs = {
            # Configuration for field validation
            "email": {
                "validators": [],
                "required": False,
                "allow_blank": True,
            },  # Example: "john@example.com"
            "full_name": {
                "required": False,
                "allow_blank": True,
            },  # Example: "John Doe"
            "pf_link": {
                "required": False,
                "allow_blank": True,
            },  # Example: "https://platform.com/johndoe"
        }


class CandidateListSerializer(serializers.ModelSerializer):
    """
    ListSerializer ONLY for list.
    """

    # Used for displaying a list of candidates
    # Example output: [{"id": 1, "full_name": "John Doe", "email": "john@example.com", "pf_link": "https://platform.com/johndoe"}]

    class Meta:
        model = Candidate  # Uses the Candidate model
        fields = (
            "id",  # Example: 1 (integer)
            "full_name",  # Example: "John Doe" (string)
            "email",  # Example: "john@example.com" (string)
            "pf_link",  # Example: "https://platform.com/johndoe" (URL string)
        )


class EvaluationHistorySerializer(serializers.ModelSerializer):
    """Helper serializer for showing list of passed interviews (evaluation forms)."""

    # Used for displaying evaluation history for a candidate
    # Example output: [{"id": 1, "name": "Python Developer Interview", "status": "completed", "interview_datetime": "2023-05-15T14:00:00Z", ...}]

    detail_url = (
        serializers.SerializerMethodField()
    )  # URL to view evaluation details, example: "http://example.com/api/evaluations/python-dev-123/"
    report_url = (
        serializers.SerializerMethodField()
    )  # URL to download evaluation report, example: "http://example.com/media/reports/evaluation_123.pdf"

    class Meta:
        model = EvaluationForm  # Uses the EvaluationForm model
        fields = (
            "id",  # Example: 1 (integer)
            "name",  # Example: "Python Developer Interview" (string)
            "status",  # Example: "completed", "in_progress", "scheduled" (string)
            "interview_datetime",  # Example: "2023-05-15T14:00:00Z" (datetime)
            "level_snapshot",  # Example: "Junior" (string)
            "vacancy_snapshot",  # Example: "Python Developer" (string)
            "detail_url",  # Example: "http://example.com/api/evaluations/python-dev-123/" (URL string)
            "report_url",  # Example: "http://example.com/media/reports/evaluation_123.pdf" (URL string)
        )

    def get_detail_url(self, obj) -> str | None:
        """
        Generate absolute url for EvaluationForm Detail.
        """
        # Input: EvaluationForm object
        # Output: URL string or None
        # Example: "http://example.com/api/evaluations/python-dev-123/"

        request = self.context.get("request")
        if not request:
            return None

        try:
            url_path = reverse(
                "evaluation_form:evaluation-form-detail",
                kwargs={"slug": obj.slug},  # Example: "python-dev-123"
            )
            return request.build_absolute_uri(url_path)
        except NoReverseMatch:
            return None

    def get_report_url(self, obj) -> str | None:
        """Return url HTML report"""
        # Input: EvaluationForm object
        # Output: URL string or None
        # Example: "http://example.com/media/reports/evaluation_123.pdf"

        request = self.context.get("request")
        if obj.report_file and request:
            return request.build_absolute_uri(obj.report_file.url)
        return None


class CandidateDetailSerializer(serializers.ModelSerializer):
    """Serializer for showing details of candidate and history of passed interviews."""

    # Used for displaying detailed information about a candidate including their evaluation history
    # Example output: {"id": 1, "full_name": "John Doe", "email": "john@example.com", "pf_link": "https://platform.com/johndoe", "evaluations": [...]}

    evaluations = (
        serializers.SerializerMethodField()
    )  # List of evaluation forms for this candidate, populated by get_evaluations method

    class Meta:
        model = Candidate  # Uses the Candidate model
        fields = (
            "id",  # Example: 1 (integer)
            "full_name",  # Example: "John Doe" (string)
            "email",  # Example: "john@example.com" (string)
            "pf_link",  # Example: "https://platform.com/johndoe" (URL string)
            "evaluations",  # Example: list of evaluation forms (array of objects)
        )

    def get_evaluations(self, obj):
        """
        Return history, sorted by interview datetime.
        """
        # Input: Candidate object
        # Output: List of serialized EvaluationForm objects
        # Example: [{"id": 1, "name": "Python Developer Interview", "status": "completed", ...}, {...}]

        qs = obj.evaluations.all().order_by(
            "-interview_datetime"
        )  # Get all evaluations for this candidate, sorted by date (newest first)
        return EvaluationHistorySerializer(qs, many=True, context=self.context).data


class CreateEvaluationFormSerializer(serializers.Serializer):
    """
    Validates input data for creating an EvaluationForm.
    Allows pass ID current candidate or create a new one.
    """

    # Used for creating a new evaluation form
    # Example input: {"candidate_id": 1, "interview_datetime": "2023-06-15T14:00:00Z"}
    # Or: {"candidate_data": {"email": "john@example.com", "full_name": "John Doe", "pf_link": "https://platform.com/johndoe"}, "interview_datetime": "2023-06-15T14:00:00Z"}

    candidate_id = serializers.IntegerField(
        required=False, allow_null=True
    )  # ID of existing candidate, example: 1
    candidate_data = CandidateFillSerializer(
        required=False, write_only=True, allow_null=True
    )  # Data for creating/updating a candidate, example: {"email": "john@example.com", "full_name": "John Doe"}
    interview_datetime = (
        serializers.DateTimeField()
    )  # When the interview is scheduled, example: "2023-06-15T14:00:00Z"

    def validate_interview_datetime(self, value):
        """
        Validate that interview_datetime is in the future.
        """
        # Input: datetime object
        # Output: validated datetime object
        # Example input: datetime(2023, 6, 15, 14, 0, 0)

        if value and value <= timezone.now():
            raise serializers.ValidationError(
                "Interview date and time must be in the future."
            )
        return value

    def validate(self, data):
        """Validate that passed candidate_id or candidate_data"""
        # Input: dictionary with serializer data
        # Output: validated dictionary
        # Example input: {"candidate_id": None, "candidate_data": {"email": "john@example.com"}, "interview_datetime": datetime(2023,6,15,14,0,0)}

        candidate_id = data.get("candidate_id")  # Example: 1 or None
        candidate_data = (
            data.get("candidate_data") or {}
        )  # Example: {"email": "john@example.com"}

        # Filter out empty values from candidate_data
        candidate_data = {key: value for key, value in candidate_data.items() if value}

        data["candidate_data"] = candidate_data

        # Ensure either candidate_id or candidate_data is provided
        if not candidate_id and not candidate_data:
            raise serializers.ValidationError("Provide candidate_id OR candidate_data.")

        if not candidate_id:
            email = candidate_data.get("email")  # Example: "john@example.com"
            full_name = candidate_data.get("full_name")  # Example: "John Doe"
            pf_link = candidate_data.get(
                "pf_link"
            )  # Example: "https://platform.com/johndoe"

            # Email is required
            if not email:
                raise serializers.ValidationError(
                    {"candidate_data": {"email": "This field is required."}}
                )

            # Check if candidate with this email already exists
            email_exists = Candidate.objects.filter(email=email).exists()

            # For new candidates, full_name and pf_link are required
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
        # Input: validated data dictionary
        # Output: dictionary with candidate object added
        # Example input: {"candidate_data": {"email": "john@example.com"}, "interview_datetime": datetime(2023,6,15,14,0,0)}
        # Example output: {"candidate": <Candidate object>, "interview_datetime": datetime(2023,6,15,14,0,0)}

        candidate_id = validated_data.pop("candidate_id", None)  # Example: 1 or None
        candidate_data = validated_data.pop(
            "candidate_data", {}
        )  # Example: {"email": "john@example.com"}

        candidate = None

        # If candidate_id is provided, get the existing candidate
        if candidate_id:
            try:
                candidate = Candidate.objects.get(
                    pk=candidate_id
                )  # Get candidate by ID
                # Update candidate with any provided data
                if candidate_data:
                    for attr, value in candidate_data.items():
                        if value:
                            setattr(candidate, attr, value)
                    candidate.save()
            except Candidate.DoesNotExist:
                raise serializers.ValidationError(
                    f"Candidate with id {candidate_id} not found."
                )

        # If candidate_data is provided, get or create the candidate
        elif candidate_data:
            email = candidate_data.get("email")  # Example: "john@example.com"
            full_name = candidate_data.get("full_name")  # Example: "John Doe"
            pf_link = candidate_data.get(
                "pf_link", ""
            )  # Example: "https://platform.com/johndoe"

            defaults = {"pf_link": pf_link}
            if full_name:
                defaults["full_name"] = full_name

            # Try to get existing candidate by email, or create a new one
            try:
                candidate, created = Candidate.objects.get_or_create(
                    email=email,
                    defaults=defaults,
                )
            except IntegrityError:
                # Race condition: another request created this candidate simultaneously
                # Fetch the existing candidate instead of raising 500 error
                candidate = Candidate.objects.filter(email=email).first()
                if not candidate:
                    raise serializers.ValidationError(
                        {
                            "candidate_data": {
                                "email": "Failed to create candidate. Please try again."
                            }
                        }
                    )
                created = False

            # If candidate already existed, update fields if needed
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

        validated_data["candidate"] = candidate  # Add candidate to validated_data

        return validated_data


class EvaluationFormUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an EvaluationForm.
    """

    # Used for updating an existing evaluation form and its associated candidate
    # Example input: {"candidate_full_name": "John Doe", "candidate_email": "john@example.com", "candidate_pf_link": "https://platform.com/johndoe", "interview_datetime": "2023-06-15T14:00:00Z"}

    candidate_full_name = serializers.CharField(
        source="candidate.full_name"
    )  # Full name of the candidate, example: "John Doe"
    candidate_email = serializers.EmailField(
        source="candidate.email"
    )  # Email of the candidate, example: "john@example.com"
    candidate_pf_link = serializers.URLField(
        source="candidate.pf_link"
    )  # Platform link of the candidate, example: "https://platform.com/johndoe"

    class Meta:
        model = EvaluationForm  # Uses the EvaluationForm model
        fields = (
            "candidate_full_name",  # Example: "John Doe" (string)
            "candidate_email",  # Example: "john@example.com" (string)
            "candidate_pf_link",  # Example: "https://platform.com/johndoe" (URL string)
            "interview_datetime",  # Example: "2023-06-15T14:00:00Z" (datetime)
        )

    def validate_interview_datetime(self, value):
        """
        Validate that interview_datetime is in the future.
        """
        # Input: datetime object
        # Output: validated datetime object
        # Example input: datetime(2023, 6, 15, 14, 0, 0)

        if value <= timezone.now():
            raise serializers.ValidationError(
                "New interview date and time must be in the future."
            )
        return value

    def update(self, instance, validated_data):
        # Input: EvaluationForm instance and validated data dictionary
        # Output: Updated EvaluationForm instance
        # Example input: instance=<EvaluationForm object>, validated_data={"interview_datetime": datetime(2023,6,15,14,0,0), "candidate": {"full_name": "John Doe"}}

        candidate_data = validated_data.pop(
            "candidate", {}
        )  # Extract candidate data, example: {"full_name": "John Doe"}

        # Update the EvaluationForm instance
        instance = super().update(instance, validated_data)

        # Update the associated Candidate instance if candidate data is provided
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

    # Used for simple representation of evaluation scores
    # Example output: {"id": 1, "item": 5, "score": 4, "comment": "Good knowledge", "lacks_expertise": false}

    class Meta:
        model = EvaluationScore  # Uses the EvaluationScore model
        fields = (
            "id",  # Example: 1 (integer)
            "item",  # Example: 5 (integer, ID of EvaluationFormItem)
            "score",  # Example: 4 (integer, typically 1-5)
            "comment",  # Example: "Good knowledge of Python" (string)
            "lacks_expertise",  # Example: false (boolean)
        )


class EvaluationScoreSerializer(serializers.ModelSerializer):
    # Used for creating, updating and retrieving evaluation scores
    # Example input: {"item": 5, "score": 4, "comment": "Good knowledge", "lacks_expertise": false}
    # Example output: {"id": 1, "interviewer": 3, "item": 5, "score": 4, "comment": "Good knowledge", "lacks_expertise": false}

    item = serializers.PrimaryKeyRelatedField(
        queryset=EvaluationFormItem.objects.all()
    )  # Reference to the evaluation item being scored, example: 5 (ID of item)
    lacks_expertise = serializers.BooleanField(
        required=False
    )  # Flag indicating interviewer lacks expertise in this area, example: false

    class Meta:
        model = EvaluationScore  # Uses the EvaluationScore model
        fields = (
            "id",  # Example: 1 (integer)
            "interviewer",  # Example: 3 (integer, ID of User)
            "item",  # Example: 5 (integer, ID of EvaluationFormItem)
            "score",  # Example: 4 (integer, typically 1-5)
            "comment",  # Example: "Good knowledge of Python" (string)
            "lacks_expertise",  # Example: false (boolean)
        )

        read_only_fields = (
            "id",
            "interviewer",
        )  # These fields are set automatically, not by the client

    def __init__(self, *args, **kwargs):
        # Initializes the serializer and filters items based on form_id if provided
        # Example context: {"request": <Request object>}

        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request:
            form_id = request.query_params.get("form_id")  # Example: "5"

            if form_id:
                # Filter items to only those belonging to the specified form
                self.fields["item"].queryset = EvaluationFormItem.objects.filter(
                    form_topic__evaluation_form_id=form_id
                )

    def validate(self, data):
        # Перевірка конфлікту lacks_expertise + score
        # Перевірка статусу форми:
        # - Якщо status == COMPLETED → ValidationError
        # - Якщо status == PENDING → ValidationError
        # - Тільки IN_PROGRESS дозволяється
        """
        Validate:
        1. Can't mark "lacks_expertise=True" and put score in the same time.
        2. Form must be in IN_PROGRESS status to add/edit scores.
        """
        # Input: dictionary with serializer data
        # Output: validated dictionary
        # Example input: {"item": 5, "score": 4, "lacks_expertise": true}

        # Check if lacks_expertise and score conflict
        if data.get("lacks_expertise") and data.get("score") is not None:
            raise serializers.ValidationError(
                "You cannot provide a score and also claim 'lack of expertise'."
            )

        # Validate form status
        item = data.get("item")
        if item:
            evaluation_form = item.form_topic.evaluation_form
            if evaluation_form.status == EvaluationForm.Status.COMPLETED:
                raise serializers.ValidationError(
                    "This evaluation is completed and locked. You cannot add or edit scores."
                )
            if evaluation_form.status == EvaluationForm.Status.PENDING:
                raise serializers.ValidationError(
                    "This interview has not started yet. You cannot add scores."
                )

        return data


class EvaluationItemForRecruiterSerializer(serializers.ModelSerializer):
    # Used for displaying evaluation items with their scores for recruiters
    # Example output: {"id": 5, "text_snapshot": "Explain REST API principles", "scores": [{...}, {...}]}

    scores = EvaluationScoreSerializer(
        many=True
    )  # List of scores for this item from different interviewers

    class Meta:
        model = EvaluationFormItem  # Uses the EvaluationFormItem model
        fields = (
            "id",  # Example: 5 (integer)
            "text_snapshot",  # Example: "Explain REST API principles" (string)
            "scores",  # Example: list of score objects (array)
        )


class EvaluationFeedbackSerializer(serializers.ModelSerializer):
    # Used for creating, updating and retrieving interviewer feedback
    # Example input: {"pros": "Good communication", "cons": "Lacks experience", "decision": "hire", "candidates_level": "junior"}
    # Example output: {"id": 1, "interviewer_name": "Jane Smith (You)", "pros": "Good communication", "cons": "Lacks experience", "decision": "hire", "candidates_level": "junior", "is_submitted": true, "feedback_detail": "http://example.com/api/feedback/1/"}

    interviewer_name = (
        serializers.SerializerMethodField()
    )  # Name of the interviewer, example: "Jane Smith (You)"
    feedback_detail = (
        serializers.SerializerMethodField()
    )  # URL to the feedback detail page

    class Meta:
        model = EvaluationFeedback  # Uses the EvaluationFeedback model
        fields = (
            "id",  # Example: 1 (integer)
            "interviewer_name",  # Example: "Jane Smith (You)" (string)
            "pros",  # Example: "Good communication skills, strong problem-solving" (string)
            "cons",  # Example: "Lacks experience with Django, weak on SQL" (string)
            "decision",  # Example: "hire", "reject", "consider" (string)
            "candidates_level",  # Example: "junior", "middle", "senior" (string)
            "is_submitted",  # Example: true (boolean)
            "feedback_detail",  # Example: "http://example.com/api/feedback/1/" (URL string)
        )
        read_only_fields = (
            "id",
            "is_submitted",
            "feedback_detail",
        )  # These fields are set automatically

    def get_interviewer_name(self, obj):
        # Input: EvaluationFeedback object
        # Output: String with interviewer name, with "(You)" appended if it's the current user
        # Example: "Jane Smith (You)" or "John Doe"

        request = self.context.get("request")
        if request and obj.interviewer == request.user:
            return f"{obj.interviewer.fullname} (You)"

        return obj.interviewer.fullname

    def get_feedback_detail(self, obj):
        """
        Generate URL to edit page feedback.
        """
        # Input: EvaluationFeedback object
        # Output: URL string or None
        # Example: "http://example.com/api/feedback/1/"

        request = self.context.get("request")
        if not request or not obj.pk:
            return None

        try:
            url = reverse(
                "evaluation_form:evaluation-feedback-detail", kwargs={"pk": obj.pk}
            )
            return request.build_absolute_uri(url)
        except NoReverseMatch:
            return None


class EvaluationTopicForRecruiterSerializer(serializers.ModelSerializer):
    # Used for displaying evaluation topics with their items for recruiters
    # Example output: {"id": 2, "topic_name_snapshot": "Python", "items": [{...}, {...}]}

    items = EvaluationItemForRecruiterSerializer(
        many=True
    )  # List of evaluation items in this topic

    class Meta:
        model = EvaluationFormTopic  # Uses the EvaluationFormTopic model
        fields = (
            "id",  # Example: 2 (integer)
            "topic_name_snapshot",  # Example: "Python" (string)
            "items",  # Example: list of evaluation items (array)
        )


class RecruiterEvaluationSerializer(serializers.ModelSerializer):
    # Used for displaying complete evaluation form data for recruiters
    # Example output: {"id": 1, "recruiters": [3, 4], "candidate": {...}, "interview_datetime": "2023-06-15T14:00:00Z", ...}

    feedbacks = EvaluationFeedbackSerializer(
        many=True
    )  # List of feedback from all interviewers
    topics = EvaluationTopicForRecruiterSerializer(
        many=True, source="form_topics", read_only=True
    )  # List of topics with their items and scores

    class Meta:
        model = EvaluationForm  # Uses the EvaluationForm model
        fields = (
            "id",  # Example: 1 (integer)
            "recruiters",  # Example: [3, 4] (array of user IDs)
            "candidate",  # Example: {"id": 5, "full_name": "John Doe", ...} (object)
            "interview_datetime",  # Example: "2023-06-15T14:00:00Z" (datetime)
            "vacancy_snapshot",  # Example: "Python Developer" (string)
            "level_snapshot",  # Example: "Junior" (string)
            "project_snapshot",  # Example: "E-commerce Platform" (string)
            "status",  # Example: "completed", "in_progress", "scheduled" (string)
            "topics",  # Example: list of topics with items and scores (array)
            "feedbacks",  # Example: list of feedback from interviewers (array)
        )


class EvaluationItemForInterviewerSerializer(serializers.ModelSerializer):
    # Used for displaying evaluation items with the current interviewer's score
    # Example output: {"id": 5, "text_snapshot": "Explain REST API principles", "my_score": 4}

    my_score = (
        serializers.SerializerMethodField()
    )  # The score given by the current interviewer, example: 4

    class Meta:
        model = EvaluationFormItem  # Uses the EvaluationFormItem model
        fields = (
            "id",  # Example: 5 (integer)
            "text_snapshot",  # Example: "Explain REST API principles" (string)
            "my_score",  # Example: 4 (integer) or null
        )

    def get_my_score(self, item) -> int | None:
        """
        Do not make request item.scores.filter(interviewer=user)
        Read from cache 'my_scores_cache', that load ViewSet
        """
        # Input: EvaluationFormItem object
        # Output: Score value (integer) or None
        # Example: 4

        if hasattr(item, "my_scores_cache") and item.my_scores_cache:
            return item.my_scores_cache[0].score
        return None


class EvaluationTopicForInterviewerSerializer(serializers.ModelSerializer):
    # Used for displaying evaluation topics with their items for interviewers
    # Example output: {"id": 2, "topic_name_snapshot": "Python", "items": [{...}, {...}]}

    items = EvaluationItemForInterviewerSerializer(
        many=True
    )  # List of evaluation items in this topic with interviewer's scores

    class Meta:
        model = EvaluationFormTopic  # Uses the EvaluationFormTopic model
        fields = (
            "id",  # Example: 2 (integer)
            "topic_name_snapshot",  # Example: "Python" (string)
            "items",  # Example: list of evaluation items with scores (array)
        )


class InterviewerEvaluationSerializer(serializers.ModelSerializer):
    # Used for displaying evaluation form data for interviewers
    # Example output: {"id": 1, "interview_datetime": "2023-06-15T14:00:00Z", "recruiters": [3, 4], "candidate": {...}, "status": "in_progress", ...}

    my_feedback = (
        serializers.SerializerMethodField()
    )  # The current interviewer's feedback, populated by get_my_feedback method
    topics = EvaluationTopicForInterviewerSerializer(
        many=True, source="form_topics"
    )  # List of topics with their items and the interviewer's scores
    scores_url = (
        serializers.SerializerMethodField()
    )  # URL to access the interviewer's scores, populated by get_scores_url method

    class Meta:
        model = EvaluationForm  # Uses the EvaluationForm model
        fields = (
            "id",  # Example: 1 (integer)
            "interview_datetime",  # Example: "2023-06-15T14:00:00Z" (datetime)
            "recruiters",  # Example: [3, 4] (array of user IDs)
            "candidate",  # Example: {"id": 5, "full_name": "John Doe", ...} (object)
            "status",  # Example: "in_progress", "completed", "scheduled" (string)
            "topics",  # Example: list of topics with items and interviewer's scores (array)
            "scores_url",  # Example: "http://example.com/api/scores/?form_id=1" (URL string)
            "my_feedback",  # Example: {"pros": "Good communication", "cons": "Lacks experience", ...} (object)
        )

    def get_my_feedback(self, item) -> int | None:
        """
        Do not make request form.feedbacks.filter(interviewer=user)
        Read from cache 'my_feedback_cache', that load ViewSet
        Return serialized feedback object or empty dict
        """
        # Input: EvaluationForm object
        # Output: Serialized feedback object or None
        # Example: {"pros": "Good communication", "cons": "Lacks experience", "decision": "hire", ...}

        if hasattr(item, "my_feedback_cache") and item.my_feedback_cache:
            feedback_object = item.my_feedback_cache[
                0
            ]  # Get the feedback object from cache
            return EvaluationFeedbackSerializer(
                feedback_object, context=self.context
            ).data
        return None

    def get_scores_url(self, item) -> str | None:
        """
        Generate url for list of scores, filtered by EvaluationForm instance.
        """
        # Input: EvaluationForm object
        # Output: URL string or None
        # Example: "http://example.com/api/scores/?form_id=1"

        request = self.context.get("request")
        if not request:
            return None

        try:
            url_path = reverse(
                "evaluation_form:evaluation-score-list"
            )  # Get base URL for scores list
            full_url = request.build_absolute_uri(url_path)  # Make it absolute
            return f"{full_url}?form_id={item.pk}"  # Add query parameter for filtering
        except Exception:
            return None


class EvaluationFormListSerializer(serializers.ModelSerializer):
    # Used for displaying a list of evaluation forms
    # Example output: [{"id": 1, "name": "Python Developer Interview - John Doe", "status": "completed", "interview_datetime": "2023-06-15T14:00:00Z", "detail_url": "http://example.com/api/evaluations/python-dev-123/"}]

    detail_url = (
        serializers.SerializerMethodField()
    )  # URL to view evaluation details, populated by get_detail_url method

    class Meta:
        model = EvaluationForm  # Uses the EvaluationForm model
        fields = (
            "id",  # Example: 1 (integer)
            "name",  # Example: "Python Developer Interview - John Doe" (string)
            "status",  # Example: "completed", "in_progress", "scheduled" (string)
            "interview_datetime",  # Example: "2023-06-15T14:00:00Z" (datetime)
            "detail_url",  # Example: "http://example.com/api/evaluations/python-dev-123/" (URL string)
        )

    def get_detail_url(self, obj: EvaluationForm) -> str | None:
        """
        Generate, URL to 'retrieve' for this EvaluationForm.
        """
        # Input: EvaluationForm object
        # Output: URL string or None
        # Example: "http://example.com/api/evaluations/python-dev-123/"

        request = self.context.get("request")
        if not request:
            return None

        try:
            url = reverse(
                "evaluation_form:evaluation-form-detail",
                kwargs={"slug": obj.slug},  # Example slug: "python-dev-123"
            )
        except NoReverseMatch:
            return None

        return request.build_absolute_uri(url)


class EmptySerializer(serializers.Serializer):
    """
    Use for actions, which no need input data (only POST-request).
    """

    # Used for actions that don't require input data, only a POST request
    # Example: Used for submitting a form, canceling an interview, etc.
    # Example input: {} (empty object)
    # Example output: {} (empty object)

    pass
