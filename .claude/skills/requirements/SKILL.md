---
name: requirements
description: >
  Writes and updates docs/features/<slug>/PRD.md in this repository. Use whenever a
  feature has to become something a developer can build from, or an existing document
  under docs/features/ needs extending, correcting or checking - even when nobody types
  "PRD": "напиши вимоги", "що саме будуємо", "опиши фічу для розробників", "оформи бриф
  у вимоги", "що передати розробникам", "щоб можна було віддати в роботу", "критерії
  приймання для <фіча>", "специфікація <slug>", "requirements <slug>", "PRD для <slug>".
  Also use when asked to change one thing inside such a document: a retention period, an
  error message, a criterion, a metric. Not the idea stage - that is discovery. Not
  endpoints, schemas or storage - that is the architecture stage.
---

# Skill: requirements (stage 03 - PRD for the evaluation-form pipeline)

Takes `docs/features/<slug>/idea-brief.md` at `status: Confirmed` and produces
`docs/features/<slug>/PRD.md` with 12 sections.

Output is a **product** document: what a person can observe, and what the team is betting on.
Storage engines, endpoints and schemas belong to the architecture stage. The one exception is
§6, and it is deliberate.

Why this skill exists next to a generic one, why each prohibition below is a prohibition, and
what broke in earlier revisions → [./references/rationale.md](./references/rationale.md). Not
run-time reading; read it before changing this file.

**Owner:** whoever owns the feature. Tech Lead joins at the four-risks check if feasibility is
contested.

## When to use

- «PRD для <slug>», «напиши вимоги для <фіча>», «специфікація <slug>», «що передати
  розробникам», «оформи бриф у вимоги», «requirements <slug>».
- There is **no `/requirements` slash command** in this repository - `.claude/commands/` does
  not exist - so never print one as a next step.
- If `docs/features/<slug>/PRD.md` already exists, this is an **update**. Go to «Update mode».

## Inputs and gate

**Hard gate - refuse if any is missing, and say which:**

- **The slug.** Match what the user said against the directories under `docs/features/`. Zero
  matches or more than one: show the list and ask, rather than picking the closest. People name
  features in words («фіча про нагадування»), and the closest match is wrong often enough to
  matter.
- `docs/features/<slug>/idea-brief.md` at `status: Confirmed`. Missing or still `Draft` → stop:
  «спершу `discovery <slug>`». A PRD written without a brief is a guess with sections. `Frozen`
  counts as Confirmed: frozen means finished, not abandoned.
- A glossary: root `CONTEXT.md`, plus `docs/features/<slug>/CONTEXT.md` if the feature has its
  own delta. Missing → stop: the roles in §4 have nowhere to come from.

**Read, do not require:** `docs/features/<slug>/.size` (absent → establish it at step 1 and
write it, so no later stage silently defaults to the middle); `Features_list.json`; a reference
module if the user names one or passes `--reference <path>` - read it for the conventions
actually in use, not the ones you would prefer.

## Depth regulator

| Depth | Interview | §5 walk at 9.25 | Analyses |
|---|---|---|---|
| easy | at most 2 rounds of the design tree, then the ledger at 9.4 | rendered whole, none walked one by one | four-risks check and assumptions still run; one-way doors drafted by the skill and shown in one call, each still accepted or struck individually |
| medium (default) | tree runs until the frontier empties | error, permission and domain-rule criteria | full |
| hard | tree to empty plus one round on whatever the four-risks check flagged | every criterion | full |

Five things never scale down. **The stage gate. The critic. The three §5 floors. The glossary
batch at 9.4.** And **a one-way door is never recorded as confirmed without a name against
it**: easy saves calls, not consent.

Depth tunes how much is asked, never how complete the document is. Easy is where that promise
is easiest to break, which is why easy owes a ledger.

## Rules for the whole run

**Nothing writes before phase 10.** `ExitPlanMode` fires at 9.5. There is no tool lock enforcing
this - the Agent Skills spec has one tool field, `allowed-tools`, an allowlist, and
`disallowed-tools` is not a field - so it is a rule, along with: never `git commit`, never
`git push`, never delete anything.

**The `AskUserQuestion` checkpoints - 0.25, 0.5, 1, 2, 7, 8, 9.25, 9.4, 11 - are a data-input
protocol, not clarifying questions.** Answering them on the person's behalf turns the PRD into
a reconstruction from model memory that reads exactly like an interview, and nobody downstream
can tell. An autonomous mode does not override them. If `AskUserQuestion` is unavailable or a
call is refused, **stop and say so** - do not route around it by writing the answer in as an
assumption. An assumption is something we chose to bet on; this would be something we chose not
to find out.

## Update mode

A PRD that already exists is updated, not rewritten:

- The gate still requires a Confirmed brief, because the update has to agree with it.
- Phase 2 walks **only the branches the change touches**. Re-interviewing settled decisions
  wastes attention and invites a different answer out of boredom.
- Phase 9.25 walks **only the criteria the change touched**, at any depth.
- Phase 9.4 skips the ledger, keeps the glossary batch - an edit is exactly what brings in a
  new word.
- Phase 12.5 touches the registry only when the row is missing or the size changed.
- The critic still runs. It is the only thing that sees cross-section damage, which is what a
  partial edit causes.
- **`status: Approved` is never silently lowered.** If the update materially changes §5, §8 or
  §9, say what changed and ask whether it goes back to Draft.
- Say what changed, in the response and in §1 ¶4.

**A document this skill did not write.** No §6 and no §9 means another tool produced it,
usually with eight sections. **Do not renumber it and do not convert it** as a side effect of
an unrelated edit. Work inside the shape you found, and when a change has nowhere to go - an
irreversible decision with no §9, a new error with no §6 - write it in prose in the nearest
section and **say in the response that it has no proper home here**, then offer the migration
as separate work with its own confirmation. The §5 floors still apply to whatever the criteria
section is called; «12 sections» does not, and the validator downgrades it to a warning.

## Audit mode

«Чи можна це віддавати?», «глянь і скажи, чого бракує», «він готовий?» is a **third mode**,
and it is neither a new document nor an update. It has no gate: a document already exists, so
there is nothing to refuse.

1. Run `validate-prd.sh` and quote its verdict rather than re-deriving the checks in prose.
2. Run the critic (phase 11) on the document as it stands, with an empty edits log and a note
   saying the log is empty because this run made no changes. This is the half the script cannot
   do, and skipping it turns an audit into a lint.
3. Report blocking findings separately from advisory ones, and say which section each is in.
4. **Change nothing.** The person asked whether it can ship, not for it to be fixed. Offer the
   fix as a separate run and say which of its parts need answers from them.

Both arms of the 2026-09-07 evaluation improvised this mode differently because it was not
written down, and one of them silently skipped the critic. Two runs of the same request should
not return different depths.

## Question style

**The contract lives in [./references/ask-examples.md](./references/ask-examples.md), and
phase 0.25 reads it before asking anything.** It is a contract rather than advice because this
is the half most PRD skills get wrong, and the failure is invisible: a bad question produces an
answer that looks exactly like a good one.

Five lines of it, so you know what you are reading for. Ukrainian throughout. Three blocks per
question - про що це, чому це важливо, на що подивитись. A recommended first option marked
`(Рекомендовано)`. An example of the shape of the answer. The consequence of each option inside
the option. And: look in the five named places before asking, never in the database.

## Protocol

**20 steps, 0 to 13 with fractions. Everything up to 9.4 is read-only. 9.5 = ExitPlanMode. 10
writes, 11 criticises, 12 self-checks, 12.5 registers, 13 proposes the commit.** A step number
and a section number are different things - step 5 writes §5 and §6 - so each heading names
both.

### The edits log

**Steps 2, 7, 9.25, 9.4 and 11 append to one in-memory list.** It is the only thing that lets
the critic tell a deliberate choice from a drift, and two of its nine failure classes read it.

One entry per decision that **changed** the draft from what the skill proposed:

```
{item: "AC-04" | "US-02" | "§7 latency" | "§9 door 1",
 action: "add" | "edit" | "drop" | "to_open_question",
 before: "<verbatim text before, or null for add>",
 after:  "<verbatim text after, or null for drop>",
 reason: "<the person's own words, verbatim - not a paraphrase>"}
```

Accepted-as-proposed is **not** logged: unchanged proposals are the baseline, and logging them
buries the four entries that matter under forty that do not. `reason` is quoted, not
summarised - a summary is the skill agreeing with itself about why the person disagreed.

### 0. Setup (read-only)

Read the template, both glossaries, the brief, `Features_list.json`, and the reference module
if one was named. Verify the gate. Copy nothing yet.

### 0.25. Depth and owner (AskUserQuestion - mandatory)

Two questions in one call. **Depth:** recommend from what phase 0 found - a brief with four
open questions deserves more than one with none. **Owner:** offer the brief's `owner` as the
drafted answer. The document names a person because §9 records who confirmed each irreversible
decision, and an unsigned confirmation is not one.

### 0.5. Stage gate (AskUserQuestion - mandatory, blocking)

Ask which of the four stages the feature lives in. **Ask even when the brief already says**,
showing what it said: between ideation and requirements the idea usually grew, and the stage is
the sentence every later section inherits. A brief from `discovery` records it in §16 and in
frontmatter `stage_touched`; a brief from anywhere else records it nowhere, so say that and
treat the answer as new information rather than a confirmation.

| Stage | What it is |
|---|---|
| question bank | reusable questions, topics, tech stacks |
| template form | reusable blueprint, draft and publish |
| working form | per-vacancy copy, collaborative voting and approval |
| evaluation form | per-candidate snapshot, scores, feedback, report |

Because `AskUserQuestion` cannot express «both» when the options are four stages, **the
question carries that option itself**: «це дві стадії» as a fifth option, in plain words.
Without it a person who means «both» has to pick one and is not lying, only cornered.

**If the answer is two or more stages, stop.** Offer to split into that many slugs, written
separately in dependency order. Every later section of a two-stage PRD has to hedge, and the
hedging is what makes a document nobody can size and nobody can test. A cross-cutting idea -
notifications, audit, analytics - is not an exception: write the stage that must ship first and
record what the others need in §12 with an owner.

If the answer differs from the brief, stop and show both. One of the two is wrong, and finding
out here is cheaper than three stages later.

### 1. Size (AskUserQuestion, skipped if `.size` exists)

| Signal | Fires when |
|---|---|
| Merges | more than two changes have to land before anything is usable |
| Stage boundary | a new field has to be carried into the next stage by hand |
| Existing behaviour | something that works today starts working differently |
| New personal data | anything is stored about a person who is not a user of the system |

Zero signals is XS, one S, two M, three L, four XL. Two overrides: **new personal data alone
never scores below M**, because it drags in consent and retention whatever else is true; and
anything the person calls a quarter of work is L regardless. If the brief's frontmatter has a
non-empty `feature_size`, offer it as the drafted answer and say where it came from.

**File format:** one line, one of `XS S M L XL`, nothing else. No frontmatter, no comment, no
trailing prose - other tools read this file by pattern and a second line breaks them silently.

### 2. Design-tree interview (AskUserQuestion - mandatory)

Not a list, a **tree**: every answer settles a decision and branches into the decisions hanging
off it.

**Seeding.** The root is the brief's own Open questions - the things already known to be
unanswered by the person who wrote them. A question whose `до:` names this stage, or a date
already past, goes in the first round. Briefs in practice often carry neither owner nor date
there. **Do not guess which are urgent:** say the brief left them unprioritised, show the list,
and ask which block this document. That question is itself the first round.

**The frontier** is every decision whose prerequisites are settled. Ask the whole frontier in
one round, let the answers reshape the tree, recompute, ask again. A question whose answer
depends on something still open belongs to a **later round** - asked early it gets an invented
answer, indistinguishable from a real one four sections down. **Termination is an empty
frontier**, not a question count; at easy the cap is two rounds and the remainder goes to §12
with an owner.

`AskUserQuestion` carries at most four questions per call, so a wider frontier splits across
consecutive calls inside the same round, in tree order. **Never promote a later-round question
to fill a call.**

**Log it.** An answer that overrides the draft you offered is an `edit`; one that closes a
branch you opened is a `drop`. An answer that accepts your draft gets nothing.

### 3. Four-risks check (read-only, no user input)

Check that the brief and the answers so far cover the four ways a product fails. Name any gap;
it becomes an assumption in §9 or a question in the next round.

| Risk | The question it asks | Where its answer lives |
|---|---|---|
| Value | Will anyone choose to use this? | §2 Goals, §11 KPIs |
| Usability | Can they work out how? | §4 stories, §5 criteria |
| Feasibility | Can it be built with what we have? | §7 NFR, §10 Migration |
| Viability | Does it work for the business, legally and operationally? | §8 Security, §9 Assumptions |

The fourth is the one that gets skipped, because it has no obvious owner in a small team. In
this product it is also the one with consequences outside the company.

### 4. Draft §1-§4 (read-only)

Roles come from the glossary **verbatim** - never invent `user` or `admin` when the glossary
names `interviewer` and `recruiter`. Every goal in §2 gets at least one story in §4; a goal no
story serves is either not a goal or a missing story, and both are worth knowing.

### 5. Draft §5 criteria + §6 error catalogue (read-only)

**Read [./references/ac-floors.md](./references/ac-floors.md) before writing a single
criterion.** It holds the whole contract - five kinds, three floors, forbidden tokens, and the
line between a genuine error and a state where the system worked and has nothing to show yet.
It is the single source; nothing restates it.

In one line, so you know what you are reading for: §5 is business language only, Given / When /
Then from the actor's point of view, and every criterion names its observation point.

Two things in that file are newer than the rest and are the ones a run skips: **the shape of a
single criterion** - one actor, one action in `When`, one observable statement in `Then` - and
**the four sweeps** that no floor can catch, because a floor is satisfied by one criterion of
each kind. The sweeps are glossary invariants, the version of whoever judged, the state where
there is not enough data yet, and the right of the person the new data is about. Do all four
before calling §5 drafted; each of them found a real gap on 2026-09-07.

**§6 is where the codes live**, and only there. Each error criterion gets a row; a state gets
none. Format → [./references/error-catalogue.md](./references/error-catalogue.md).

### 6. Draft §7 NFR + §8 Security (read-only)

Numbers, never adjectives. «Fast» is not a requirement, it is a hope. Defaults →
[./references/nfr-defaults.md](./references/nfr-defaults.md).

Security is a **full section**: classification, personal data, legal basis with a source named,
permission changes, abuse cases with the business response, retention, verdict. In a product
holding candidate data, a four-line subsection is not a review.

### 7. Assumptions and one-way doors (AskUserQuestion - mandatory)

**Assumptions.** Three to five things the PRD is betting on, each with what breaks if wrong and
the **cheapest way to find out before writing code**. A claim about the world, not about the
plan: «interviewers submit late because they forget» is one, «we will send reminders» is not.
Rank by damage-if-wrong, not likelihood - the likely-wrong ones are already hedged.

**One-way doors.** Decisions expensive or impossible to reverse once shipped: data collected
about a person, a promise made to a candidate, a field carried into a later stage, anything
visible outside the company. Each gets a line on what makes it hard to undo, and each is
confirmed by the user - a one-way door is exactly the decision a skill must not make.

**Log it.** A struck door is the most useful entry the critic can get: it means the run
considered something irreversible and decided against it, and F1 asks whether the rest of the
document still believes that.

### 8. Migration and rollback (read-only draft + AskUserQuestion on the kill switch)

How the change reaches live data and how it is undone. The load-bearing question here is
stage-specific: **a new field on one stage does not travel to the next by itself**, because
each stage is a copy, not a reference. Say who carries it and when.

Rollback has two halves and only the first is usually written: turning the feature off, and
what remains after it is off. Data already collected does not un-collect.

### 9. Draft §11 KPIs + §12 Open questions (read-only)

Every metric: baseline → target → timeframe. `baseline: 0` is fine for something new;
`baseline: TBD` needs a measurement plan in the same line. Every open question carries an owner
and a due, where the due may be a stage. A question without both is not an open question, it is
a shrug. Every open question also carries **what holds until it is answered** - the default the
document runs on meanwhile. Without it the reader cannot tell an unanswered question from an
unmade decision.

**A metric that measures how people behave gets a corridor, not a ceiling.** Adoption, appeal
rate, how often something is opened: both edges mean something, and naming one edge hides the
other. «Appeals under 5% means nobody uses the channel, over 20% means nobody trusts the
machine» is a target. «No more than 20%» silently declares zero to be success, and zero is the
failure that looks like triumph.

### 9.25. Show the draft and walk §5 (AskUserQuestion - mandatory)

**9.25a. Render the whole of §5 in one message**, each criterion under the story it serves,
with its kind named in plain words. No question yet. Someone about to judge nine criteria one
at a time has to see the nine first, or the third answer contradicts the seventh and neither
knew.

**9.25b. Then one question per criterion**, four options:

| Опція | Що робить |
|---|---|
| Прийняти *(Рекомендовано)* | лишається дослівно, у журнал нічого не йде |
| Виправити | людина диктує формулювання, воно замінює моє цілком |
| Винести у відкриті | критерій зникає з §5 і зʼявляється рядком у §12 з власником і датою |
| Викинути | критерій зникає без сліду, бо він тут зайвий |

«Прийняти» is recommended, and that is honest rather than lazy: the criterion was drafted from
this person's own answers, so agreeing is the expected outcome.

**Which criteria get walked** is the one thing depth changes here:

| Depth | Walked one by one |
|---|---|
| easy | none - the ledger at 9.4 covers them in a single batch |
| medium | the error, permission and domain-rule ones. A wrong happy criterion is visible the first time anyone reads the feature; a wrong permission criterion is visible after it leaks |
| hard | every criterion, in order |

**9.25c. Re-run the three floors after the walk**, not before. The walk is what breaks
coverage: `Викинути` on the only permission criterion empties a kind, and `Винести у відкриті`
on the last criterion of a retained story leaves that story untestable. Criteria moved to §12
count toward no floor. When a floor breaks, draft one replacement and ask about that one alone.

**Never renumber during the walk.** A dropped `AC-04` leaves a gap and the gap is correct: §6
points at criteria by number, and renumbering silently repoints every catalogue row.

### 9.4. Ledger and glossary batch

**The ledger runs at easy depth only.** Every decision the skill took **instead of asking**
during phases 2 through 9 gets one line, and the list goes out in a single `AskUserQuestion` as
accept-all or name-the-ones-to-change:

```
- Прийняв: <рішення> = <значення>, бо <причина дефолту>.
```

This is what makes easy a speed setting rather than a quality setting. A vetoed line becomes
one real question, asked the medium way.

**The glossary batch runs at every depth.** Any domain word used in phases 2 through 9 that
neither `CONTEXT.md` defines goes into a list as it appears. Here each takes one of two exits:
**replaced** by the glossary word that already means this, or handed to `fix-term-local` as a
proposal. Neither exit is «leave it» - an undefined domain word is what the critic reports as
F4, and catching it here costs a line while catching it there costs a checkpoint.

### 9.5. ExitPlanMode handoff

Plan: create nothing until here, then copy the template, fill 12 sections, run the critic,
resolve, self-check, register, propose the commit. If `ExitPlanMode` is unavailable the run did
not start in plan mode - go straight to 10.

### 10. Write

Copy the template and fill every section from session memory, **including every frontmatter
field the template declares** - the list lives there and is not repeated here. Where each value
comes from: `depth` and `owner` from 0.25, `stage_touched` from 0.5, `feature_size` from 1,
`ticket` from `Features_list.json`, `brief` and `updated_at` from this run.

No `<placeholder>` survives into the file. An unfilled angle bracket in frontmatter is the
failure that looks like success: the document opens, reads fine, and names nobody.

**`status` stays `Draft`.** A document that approves itself has no gate at all.

### 11. Critic (1 sub-agent, clean context)

Spawn with no session memory. It reads the brief and both glossaries itself and receives the
draft plus the edits log. Prompt and failure classes →
[./references/critic.md](./references/critic.md). Clean context is the point: a critic that
watched the interview defends its conclusions.

**Log it.** Every disposition other than «Відхилити» changes the draft, so each appends an
entry.

Findings have four dispositions, defined once in `critic.md` rather than listed here.
Mechanical findings - a glossary violation, a code leaked into §5 - are fixed without asking:
there is no judgement in them, and spending a checkpoint there means not spending it where
judgement is actually needed.

### 12. Self-check

```
bash .claude/skills/requirements/scripts/validate-prd.sh <slug>
```

One pass over every mechanical check: sections, forbidden tokens, both §5 floors, the §6
columns and the criteria they point at, §7 numbers, §11 timeframes, §12 owners, frontmatter,
and the per-section budgets it reads out of
[./references/budgets.md](./references/budgets.md). The script is the list; this file does not
repeat it.

`FAIL` blocks; **`WARN` does not**. On a foreign document the missing sections and frontmatter
fields come back as warnings by design - the §5 floors still fail, because those hold in any
shape. A budget overrun is a warning: compress that section, named by number, per the cut order
in `budgets.md`. Overrunning with a stated reason beats cutting a criterion to hit a number.

**Then check by hand only what needs judgement:**

- §8: the legal basis names a **source**, not just a claim; retention is a number or an open
  question with an owner.
- §9: each assumption is a statement about the world with a consequence and a check that can be
  done before code; every one-way door carries a name and a date.
- §10: rollback says what **remains** after the switch is off.
- §6: nothing that is merely a state got a code - the test is in `ac-floors.md`, and it is the
  one a grep cannot make.
- Roles read verbatim from the glossary and mean there what they mean here.

### 12.5. Register the feature

**Do this, do not ask someone else to.** A feature that lives only in `docs/features/` is
invisible to `Features_list.json`, the list the rest of the process reads.

The registry holds exactly five fields per entry and **no slug field**, so the slug goes in
`description` or nothing connects the row to the folder:

```json
{"id": "<PREFIX>-<n>", "category": "<one already in use>",
 "name": "<the feature in 3-8 words>",
 "description": "<one sentence>. Slug: <slug>, size <XS|S|M|L|XL>, PRD Draft.",
 "done": false}
```

Read the file first and reuse an existing `category`; a nineteenth category for one feature
makes the registry unsortable. Take the `id` prefix from entries already in that category and
continue their numbering. Bump the top-level `updated`. If a row for this feature exists,
**edit it** rather than adding a second - a duplicate id is worse than a missing row, because
the missing row is visible.

### 13. Propose a commit and name the handoff

Propose, do not execute:

```
03: PRD for <slug> via requirements
```

Then name the handoff explicitly, because in a four-stage pipeline this is the join that fails
quietly:

1. **A person reads the document and sets `status: Approved`.** Nothing downstream starts
   before that, and nothing in this skill may do it for them.
2. **The architecture stage inherits three preconditions:** `status: Approved`, exactly one
   stage in frontmatter, and §6 filled for every error criterion. A missing third one is the
   usual cause of an architecture pass that invents its own error vocabulary.

## Definition of Done

Everything about the document's **shape** is one line, because the script owns it and a second
copy here would be a second place to drift:

- `validate-prd.sh <slug>` exits clean, or each remaining finding is recorded with a reason.

What the script cannot see, and therefore has to be checked here:

- Stage gate ran and agreed with the brief, or the disagreement is written down.
- The design tree terminated on an empty frontier, or on the easy cap with the remainder in §12.
- Four-risks check ran; any thin risk became an assumption or an open question.
- §5 was rendered whole at 9.25 and walked to the extent the depth requires; the three floors
  were re-run **after** the walk; nothing was renumbered during it.
- The four sweeps from `ac-floors.md` ran: glossary invariants, version of the judge, the
  not-enough-data state, and the right of the person the new data is about. A sweep that found
  nothing is fine; a sweep that did not run is the failure, and it is invisible afterwards.
- Every §7 row's third column names **where the number is measured**, not why it is that number.
- Every metric about how people behave carries both edges, not just a ceiling.
- Every §12 line says what holds until the question is answered.
- At easy depth the ledger went out and came back, every line accepted or turned into a real
  question.
- The glossary batch is empty: every domain word matches a `CONTEXT.md` entry or went to
  `fix-term-local`.
- The edits log has an entry for every change and none for anything accepted as proposed.
- The critic ran in clean context, received that log, and every finding was resolved,
  overridden or written into §12.
- §9 assumptions are claims about the world with checks that can be done before code; every
  one-way door is confirmed by name.
- §10 says what remains after rollback.
- `.size` was confirmed by a person if this run created it.
- `Features_list.json` holds exactly one row for this feature, `done: false`, slug in the
  description, `updated` bumped.
- Every AskUserQuestion carried a recommended answer, an example, and the consequence per
  option.

## Red flags - stop and reconsider

Each of these has cost a real run. The reasoning behind every line is in
[./references/rationale.md](./references/rationale.md); here they are short on purpose, so the
list stays scannable at the moment it is needed.

- No Confirmed brief, but the sections would fill plausibly anyway.
- Taking the brief's stage answer without re-asking.
- One document covering two pipeline stages.
- Pulling a later-round question forward to fill a call.
- Four options with nothing marked recommended.
- A question with no example of the shape of the answer.
- Asking for something `Features_list.json`, `Progress.md` or a `CONTEXT.md` already holds.
- Treating an empty search as permission to guess.
- Opening the database to answer a product question.
- An adjective where §7 wants a number.
- A §7 row whose third column explains the number instead of saying where to measure it.
- A criterion whose `When` carries two actors, or three actions with three different outcomes.
- An accumulating screen - a share, a trend, a profile - with no criterion for the moment when
  there is not enough data to mean anything.
- A feature that stores a judgement about a person and never says what happens to old
  judgements when the judge is replaced.
- A behaviour metric with a ceiling and no floor, where zero would count as success.
- A four-line §8 in a product that stores what a candidate said.
- A risk written without the assumption underneath it.
- A one-way door recorded as confirmed with no name against it.
- A rollback plan that stops at the switch.
- Renumbering criteria after a drop.
- Writing `Approved`, committing, or pushing.

## Template and references

Read a reference when its phase arrives, not at the start: a run touches at most two of them.

| File | Read at |
|---|---|
| [templates/PRD.md](./templates/PRD.md) | phase 0 and 10 |
| [scripts/validate-prd.sh](./scripts/validate-prd.sh) | **run** at phase 12; run it against an existing document whenever anyone asks whether one is ready |
| [references/ask-examples.md](./references/ask-examples.md) - the question contract plus five worked before-and-after pairs | phase 0.25, before the first question |
| **[references/ac-floors.md](./references/ac-floors.md)** - five kinds, three floors, forbidden tokens, error-versus-state | phase 5, again at 9.25c, and required reading for the critic |
| [references/error-catalogue.md](./references/error-catalogue.md) | phase 5 |
| [references/nfr-defaults.md](./references/nfr-defaults.md) | phase 6 |
| [references/critic.md](./references/critic.md) | phase 11 |
| [references/budgets.md](./references/budgets.md) | only when the validator warns on a section |
| [references/example-run.md](./references/example-run.md) | phase 0, **only when `docs/features/*/PRD.md` matches nothing**; once one real PRD exists, read that instead |
| [references/rationale.md](./references/rationale.md) | never during a run - before editing this skill |
