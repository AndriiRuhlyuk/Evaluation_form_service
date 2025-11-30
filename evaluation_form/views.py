from django.contrib.auth import get_user_model
from django.db.models import prefetch_related_objects, Prefetch, Q
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from working_form.permissions import IsRecruiter
from .permissions import CanScoreOrFeedback, CanCreateScore
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from evaluation_form.models import (
    EvaluationForm,
    EvaluationFeedback,
    EvaluationScore,
    EvaluationFormItem,
    Candidate,
)
from evaluation_form.serializers import (
    RecruiterEvaluationSerializer,
    InterviewerEvaluationSerializer,
    EvaluationFormListSerializer,
    EvaluationFeedbackSerializer,
    EvaluationScoreSerializer,
    EvaluationFormUpdateSerializer,
    EmptySerializer,
    EvaluationScoreLiteSerializer,
    CandidateDetailSerializer,
    CandidateListSerializer,
)
from .services import (
    check_and_complete_evaluation,
    generate_html_report,
    PeopleForceService,
)

Employee = get_user_model()


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for view candidates and them history.
    Used for:
    1. Search candidate when create EvaluationForm (Autocomplete).
    2. View candidate profile with (History).
    """

    queryset = Candidate.objects.all()
    serializer_class = CandidateListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) | Q(email__icontains=search)
            )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("evaluations")

        return queryset

    def get_serializer_class(self):
        """
        - If LIST (/candidates/) -> CandidateListSerializer
        - If RETRIEVE (/candidates/1/) -> CandidateDetailSerializer
        """
        if self.action == "list":
            return CandidateListSerializer

        return CandidateDetailSerializer


class EvaluationFormViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Provides read-only access to Evaluation Forms.
    Shows different data based on user role and form status.
    """

    queryset = EvaluationForm.objects.all()
    lookup_field = "slug"

    def get_permissions(self):
        """
        Protect 'update' and 'destroy'.
        """
        if self.action in ["update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), IsRecruiter()]

        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Optimized 'list' and 'retrieve' request
        'retrieve' should load 'hiring_manager' and 'recruiters'
        for 'get_serializer_class', to avoid N+1.
        """

        queryset = super().get_queryset()

        if self.action == "list":
            queryset = queryset.select_related("candidate", "manager", "hiring_manager")

        if self.action == "retrieve":
            queryset = queryset.select_related(
                "manager", "hiring_manager"
            ).prefetch_related("recruiters")

        return queryset

    def get_object(self):
        """
        Take object ONCE and Cache it in 'self._instance'.
        That mean - 'get_serializer_class' do NOT make double request.
        """

        if getattr(self, "_instance", None) is None:
            self._instance = super().get_object()

        return self._instance

    def get_serializer_class(self):
        """
        Lens Switch.
        Call 'get_object()', that return cached '_instance'.
        """

        if self.action == "sync_crm":
            return EmptySerializer

        if self.action in ["update", "partial_update"]:
            return EvaluationFormUpdateSerializer

        if self.action == "list":
            return EvaluationFormListSerializer

        instance = self.get_object()
        user = self.request.user

        if user.is_superuser:
            return RecruiterEvaluationSerializer

        if instance.status == EvaluationForm.Status.COMPLETED:
            return RecruiterEvaluationSerializer

        if user == instance.manager:
            return RecruiterEvaluationSerializer

        if user == instance.hiring_manager:
            return RecruiterEvaluationSerializer

        recruiter_ids = {recruit.pk for recruit in instance.recruiters.all()}
        if user.pk in recruiter_ids:
            return RecruiterEvaluationSerializer

        return InterviewerEvaluationSerializer

    def retrieve(self, request, *args, **kwargs):
        """
        Method that:
        1. Take object with cached ('recruiters').
        2. Choose, Serializer ("lens").
        3. Load *final* data (scores/feedbacks) for choose "lens".
        """
        instance = self.get_object()
        serializer_class = self.get_serializer_class()
        user = self.request.user

        if serializer_class == RecruiterEvaluationSerializer:
            prefetch_related_objects(
                [instance],
                Prefetch(
                    "feedbacks",
                    queryset=EvaluationFeedback.objects.select_related("interviewer"),
                ),
                Prefetch(
                    "form_topics__items__scores",
                    queryset=EvaluationScore.objects.select_related("interviewer"),
                ),
            )
        else:
            prefetch_related_objects(
                [instance],
                Prefetch(
                    "feedbacks",
                    queryset=EvaluationFeedback.objects.filter(interviewer=user),
                    to_attr="my_feedback_cache",
                ),
                Prefetch(
                    "form_topics__items",
                    queryset=EvaluationFormItem.objects.prefetch_related(
                        Prefetch(
                            "scores",
                            queryset=EvaluationScore.objects.filter(interviewer=user),
                            to_attr="my_scores_cache",
                        )
                    ),
                ),
            )

        serializer = serializer_class(instance, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsRecruiter],
    )
    def sync_crm(self, request, slug=None):
        form = self.get_object()
        candidate = form.candidate

        if form.status != EvaluationForm.Status.COMPLETED:
            return Response({"error": "Complete the form first."}, 400)
        if not candidate.pf_link:
            return Response(
                {
                    "error": "Candidate does not have a PeopleForce link in their profile."
                },
                400,
            )

        generate_html_report(form)

        report_url = request.build_absolute_uri(form.report_file.url)

        decisions = form.feedbacks.values_list("decision", flat=True)
        final_decision_str = (
            "Move Forward"
            if all(d == "next_step" for d in decisions)
            else "Mixed/Refuse"
        )

        feedbacks_summary = ""
        for fb in form.feedbacks.all():
            feedbacks_summary += (
                f"- {fb.interviewer.get_full_name()}: {fb.get_decision_display()}\n"
            )

        pf_service = PeopleForceService()
        try:
            pf_service.add_evaluation_note(
                pf_link=candidate.pf_link,
                report_url=report_url,
                decision=final_decision_str,
                summary=feedbacks_summary,
            )
        except ValidationError as e:
            return Response({"error": str(e)}, status=502)

        return Response(
            {
                "status": "synced",
                "message": "Report generated and attached to form.",
                "report_url": report_url,
                "candidate_crm_link": candidate.pf_link,
            }
        )


class EvaluationScoreViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """
    Interviewer can create scores.
    """

    serializer_class = EvaluationScoreSerializer

    def get_permissions(self):
        """
        Protect 'create' (POST) action.
        'list' (GET) protected in 'get_queryset'.
        """
        if self.action == "create":
            return [permissions.IsAuthenticated(), CanCreateScore()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Load Data for CanScoreOrFeedback permission.
        - For 'list': Return ONLY scores by current user.
        - For 'create': Return 'reload' queryset (with all prefetch).
        """
        user = self.request.user

        if self.action == "list":

            return EvaluationScore.objects.filter(
                interviewer=user,
                item__form_topic__evaluation_form__status=EvaluationForm.Status.IN_PROGRESS,
            ).select_related("item")

        queryset = EvaluationScore.objects.select_related(
            "item__form_topic__evaluation_form__hiring_manager",
            "item__form_topic__evaluation_form__manager",
            "interviewer",
        ).prefetch_related(
            "item__form_topic__evaluation_form__recruiters",
            "item__form_topic__evaluation_form__interviewers",
        )
        if user.is_superuser:
            return queryset

        return queryset

    def perform_create(self, serializer):
        serializer.save(interviewer=self.request.user)

    def create(self, request, *args, **kwargs):
        """
        Override 'create', to reload object
        with prefetch-cache BEFORE, Permission check.
        """

        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        validated_data = input_serializer.validated_data
        item = validated_data["item"]

        defaults = {
            "score": validated_data.get("score"),
            "comment": validated_data.get("comment", ""),
            "lacks_expertise": validated_data.get("lacks_expertise", False),
        }

        try:
            score_obj, created = EvaluationScore.objects.update_or_create(
                item=item,
                interviewer=request.user,
                defaults=defaults,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = EvaluationScoreLiteSerializer(score_obj)

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(output_serializer.data, status=status_code)


class EvaluationFeedbackViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """
    Interviewer can create and update feedbacks and submit it.
    """

    queryset = EvaluationFeedback.objects.select_related(
        "evaluation_form", "interviewer"
    )
    permission_classes = [permissions.IsAuthenticated, CanScoreOrFeedback]

    def get_serializer_class(self):
        if self.action == "submit":
            return EmptySerializer

        return EvaluationFeedbackSerializer

    def get_queryset(self):
        """
        Load Data for CanScoreOrFeedback permission.
        """
        user = self.request.user
        queryset = EvaluationFeedback.objects.select_related(
            "evaluation_form__manager", "evaluation_form__hiring_manager", "interviewer"
        ).prefetch_related(
            "evaluation_form__recruiters",
        )

        if user.is_superuser:
            return queryset
        return queryset

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):

        feedback = self.get_object()
        interviewer = request.user
        evaluation_form = feedback.evaluation_form

        pros = feedback.pros
        cons = feedback.cons
        dec = feedback.decision

        if not pros or not cons or not dec:
            return Response(
                {
                    "error": "Pros, Cons, and Decision fields must all be filled to submit."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        all_form_item_ids = list(
            EvaluationFormItem.objects.filter(
                form_topic__evaluation_form=evaluation_form
            ).values_list("id", flat=True)
        )
        required_item_ids = set(
            EvaluationScore.objects.filter(
                item__id__in=all_form_item_ids, score__isnull=False
            ).values_list("item_id", flat=True)
        )
        my_submitted_item_ids = set(
            EvaluationScore.objects.filter(
                item__id__in=all_form_item_ids, interviewer=interviewer
            )
            .filter(Q(score__isnull=False) | Q(lacks_expertise=True))
            .values_list("item__id", flat=True)
        )

        missing_to_score_ids = list(required_item_ids - my_submitted_item_ids)
        if missing_to_score_ids:
            return Response(
                {
                    "error": "You have not scored all questions that were asked by your colleagues. "
                    "Please score them or mark them as 'lacks expertise'.",
                    "missing_item_ids": missing_to_score_ids,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        feedback.is_submitted = True
        feedback.save(update_fields=["is_submitted"])

        check_and_complete_evaluation(feedback.evaluation_form_id)
        return Response({"status": "submitted"}, status=status.HTTP_200_OK)
