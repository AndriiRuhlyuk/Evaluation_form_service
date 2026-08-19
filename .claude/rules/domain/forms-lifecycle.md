---
description: Snapshots, the three clone functions, the two opposite quorum rules, soft delete, draft/publish.
paths:
  - "template_form/**"
  - "working_form/**"
  - "evaluation_form/**"
---

# Form lifecycle: snapshots, cloning, quorum, soft delete

## Snapshot pattern

`BaseFormItems` (`template_form/models.py:177`) stores `*_snapshot` copies of question text,
difficulty, topic and max score, so a form stays historically accurate when the source
`Question` later changes. `EvaluationFormItem` and `EvaluationFormTopic` snapshot
independently and carry no voting logic.

`populate_snapshot_from_question()` (`template_form/services.py:214`) is the only place that
fills snapshots. Add new snapshot fields there, not at call sites.

Scoring: `max_score = difficulty × Question.SCORE_MULTIPLIER`, where `SCORE_MULTIPLIER = 3`
(`question/models.py:18`) and difficulty 1/2/3 means Easy/Medium/Hard. Interviewers score
0-3 per item (`EvaluationScore`): one score per interviewer per item, and one
`EvaluationFeedback` (pros / cons / decision / level) per interviewer per form.

## Cloning

- `clone_template_to_working()` - `template_form/services.py:729`
- `clone_working_to_evaluation()` - `working_form/services.py:342`
- `clone_working_from_working()` - `working_form/services.py:484`

Every clone copies snapshot fields, re-parents topics and items, and resets voting and
approval state. A new field on any form model needs an explicit line in each clone function -
nothing propagates on its own. Read all three before adding a stage or a field.

## Two quorum rules - do not conflate them

They look symmetrical and are not. Both special-case zero approvers, in opposite directions.

**Deletion is by majority.** `EffectiveDeletionMixin.calculate_effective_deletion()`
(`working_form/utils.py:51`) returns `delete_votes > total_approvers / 2`. Approvers vote via
the `deleted_by` M2M; `toggle_item_vote()` and `toggle_topic_vote()`
(`working_form/services.py:177,254`) own that logic. Zero approvers → never deleted.

**Approval is unanimous.** `WorkingForm.is_fully_approved` (`working_form/models.py:172`)
requires `approvers_count == approved_by_count`. Zero approvers → not approved. Only an
`APPROVED` working form can be cloned into an evaluation form.

## Soft delete: three flags, and `is_removed` means two different things

| Flag | Model | Manager behaviour |
|---|---|---|
| `is_active` | `Topic`, `TechStack`, `Question`, `Project` | plain default manager; each viewset exposes a `restore` action |
| `is_removed` | `WorkingFormTopic`, `WorkingFormItem` | `objects` filters removed out, `all_objects` does not |
| `is_removed` | `TemplateFormItems`, `TemplateFormTopic` | **no custom managers at all** |
| `is_deleted` | `TemplateForm`, `WorkingForm`, `EvaluationForm` (inherited from `BaseForm`) | `objects` (SoftDeleteManager) filtered, `all_objects` unfiltered and also used for slug-uniqueness checks |

The trap is the middle two rows. In `working_form` you pick a manager deliberately
(`working_form/models.py`, topic/item managers). In `template_form` items/topics there is
nothing to pick: `Model.all_objects` raises `AttributeError`, and `Model.objects` silently
returns removed rows, so filter `is_removed=False` by hand.

**Form-level soft delete (all three stages).** DELETE endpoints call
`instance.soft_delete(request.user)` via `perform_destroy`; it stamps
`deleted_at`/`deleted_by` and saves with `update_fields` (a full save would regenerate
name/slug on `WorkingForm`/`EvaluationForm`). Deleting an IN_PROGRESS evaluation raises a
DRF ValidationError (400). `report_file` is never touched - the PeopleForce note links to
it. Restore is admin-only: each form admin lists deleted rows via `all_objects` and offers
a bulk-`update()` restore action (bypasses `save()` on purpose); the standard admin delete
remains the hard-delete escape hatch. No API restore endpoint exists.

`employee.Employee.is_active` is Django's standard auth flag (login enabled/disabled) and has
nothing to do with this convention.

**Exception to soft delete:** `check_and_complete_evaluation()` hard-deletes unscored
`EvaluationFormItem`s and then empty `EvaluationFormTopic`s when a form completes.

## Draft / publish on TemplateForm

Edits land in the `draft_data` JSONField plus a `has_unpublished_changes` flag
(`template_form/models.py:148,154`). `save_template_draft()` stores them and
`publish_template_form()` applies them (`template_form/services.py:627,653`), so templates
already cloned into working forms stay stable until someone publishes explicitly.
