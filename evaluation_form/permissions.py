from rest_framework import permissions

from evaluation_form.models import (
    EvaluationForm,
    EvaluationFeedback,
    EvaluationScore,
    EvaluationFormItem,
)


class CanScoreOrFeedback(permissions.BasePermission):
    """
    Permission for 'EvaluationScoreViewSet' and 'EvaluationFeedbackViewSet'
    Check:
    - READ (GET):
        - if form is 'COMPLETED': Can see any is_authenticated=True user.
        - if form is 'IN_PROGRESS': Can see  author and admins (superuser, manager, hm, recruiter).
    - WRITE (POST/PATCH):
        - Can edit/create ONLY author, IF form is_submitted=False.
    """

    message = "You can no longer edit this evaluation."

    def has_object_permission(self, request, view, obj):

        user = request.user

        if user.is_superuser:
            return True

        try:
            if isinstance(obj, EvaluationFeedback):
                feedback = obj
                evaluation_form = obj.evaluation_form
                interviewer = obj.interviewer

            elif isinstance(obj, EvaluationScore):
                evaluation_form = obj.item.form_topic.evaluation_form
                interviewer = obj.interviewer

                feedback = EvaluationFeedback.objects.get(
                    evaluation_form=evaluation_form, interviewer=interviewer
                )
            else:
                return False
        except Exception:
            return False

        if request.method in permissions.SAFE_METHODS:

            if evaluation_form.status == EvaluationForm.Status.COMPLETED:
                return user.is_authenticated

            is_form_manager = user == evaluation_form.manager
            is_hiring_manager = user == evaluation_form.hiring_manager

            is_assigned_recruiter = False
            if "recruiters" in evaluation_form._prefetched_objects_cache:
                recruiter_ids = {r.pk for r in evaluation_form.recruiters.all()}
                is_assigned_recruiter = user.pk in recruiter_ids
            else:
                is_assigned_recruiter = evaluation_form.recruiters.filter(
                    pk=user.pk
                ).exists()

            is_admin_user = (
                is_form_manager or is_hiring_manager or is_assigned_recruiter
            )
            is_author = interviewer == user

            return is_author or is_admin_user

        if evaluation_form.status == EvaluationForm.Status.PENDING:
            self.message = "This interview has not started yet."
            return False

        is_author = interviewer == user
        if not is_author:
            self.message = "You can only edit your own scores and feedback."

        try:
            if isinstance(obj, EvaluationFeedback):
                feedback = obj
            else:
                feedback = EvaluationFeedback.objects.get(
                    evaluation_form=evaluation_form, interviewer=user
                )
        except EvaluationFeedback.DoesNotExist:
            return False

        is_not_submitted = feedback.is_submitted == False
        is_not_completed = evaluation_form.status != EvaluationForm.Status.COMPLETED

        if not is_not_submitted:
            self.message = "You have already submitted your feedback."
        elif not is_not_completed:
            self.message = "This evaluation is completed and locked."

        return is_not_submitted and is_not_completed


class CanCreateScore(permissions.BasePermission):
    """
    Permission for 'EvaluationScoreViewSet.create()' (POST / upsert).
    Chack, that feedback NOT "submitted", BEFORE create/'update' score.
    """

    message = "You cannot add or edit scores in submitted form."

    def has_permission(self, request, view):

        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if request.method != "POST":
            return True

        item_id = request.data.get("item")
        if not item_id:
            return True

        try:
            item = EvaluationFormItem.objects.select_related(
                "form_topic__evaluation_form"
            ).get(pk=item_id)
            evaluation_form = item.form_topic.evaluation_form

            if evaluation_form.status == EvaluationForm.Status.COMPLETED:
                self.message = "This evaluation is completed and locked."
                return False

            if evaluation_form.status == EvaluationForm.Status.PENDING:
                self.message = "This interview has not started yet."
                return False

            feedback = EvaluationFeedback.objects.filter(
                evaluation_form=evaluation_form, interviewer=user
            ).first()

            if feedback:
                if feedback.is_submitted:
                    self.message = "You have already submitted your feedback and cannot change scores."
                    return False
            else:
                if not evaluation_form.interviewers.filter(pk=user.pk).exists():
                    self.message = (
                        "You are not assigned as an interviewer for this form."
                    )
                    return False

            return True

        except (EvaluationFormItem.DoesNotExist, EvaluationFeedback.DoesNotExist):
            self.message = "Invalid item ID or you do not have feedback on this form."
            return False

        except Exception:
            return False
