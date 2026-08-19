---
description: How implementation work runs here - TDD via superpowers skill, and always offering subagent-driven execution for plans.
paths:
  - "**/*.py"
  - "docs/plans/**"
---

# Implementation workflow: TDD first, subagents offered every time

## TDD is mandatory for any implementation

Invoke `superpowers:test-driven-development` BEFORE writing implementation code - every
feature and bugfix goes red-green-refactor: a failing test first, then the minimal code,
then cleanup. This holds even when an approved plan lists tests as a late step: reorder
tests to the front of each task during plan review, or raise it with the user - never
silently follow a test-last plan. A test written after the code bends to the
implementation; `testing.md` already explains why a green run proves little here.

## Offer subagent-driven execution before running any plan

Before executing a plan, ALWAYS offer the user the choice between direct execution
(`superpowers:executing-plans`) and `superpowers:subagent-driven-development`, where each
plan task is delegated to a fresh-context subagent with code review between tasks. One or
two sentences on the trade-off are enough: subagents give isolated context and a per-task
review gate, but run slower and cost more tokens. Wait for the choice when the user is
available; in autonomous runs default to subagents for plans with independent tasks and
say so. Do not decide silently - the omission itself is the mistake.
