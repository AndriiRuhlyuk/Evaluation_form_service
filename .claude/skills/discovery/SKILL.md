---
name: discovery
description: >
  14-phase ideation skill for the evaluation-form pipeline. Design-tree interview in
  Ukrainian, stage gate before anything else, competitive research, 3 strategic
  approaches via parallel sub-agents, four-lens review (Engineer / Interviewer /
  Hiring side / Candidate), devil's advocate turned into falsifiable assumptions,
  Claude-proposed RICE and Feasibility. Depth regulator (easy / medium / hard).
  Stage gate with three independent cross-checks before any product question. Produces
  docs/features/<slug>/idea-brief.md with 17 sections and per-section word budgets.
  Triggers on "нова фіча", "бриф для", "розкопай ідею", "discovery для <slug>",
  "raw idea", "idea brief", "/discovery <slug>". Depends on no vendored plugin; the only
  outside skill it calls is fix-term-local, for the glossary batch. Not the same as the
  sdlc plugin's `interview` skill -
  this one knows the four-stage form pipeline and refuses to brief two stages at once.
---

# Skill: discovery (ideation for the evaluation-form pipeline)

Ideation runner for this repository. Same 14-phase shape as a generic ideation skill,
but three things are wired to *this* product: the stage gate opens the interview, the
review personas are the people who actually touch a hiring form, and the length budget
is per-section instead of one number for the whole document.

Output: `docs/features/<slug>/idea-brief.md`, 17 sections.

## Why this exists next to a generic ideation skill

A generic skill produces a competent brief about anything. It does not know that in this
repository the first question of any task is «which stage», that `score` and `max score`
are different scales, or that a field added to one stage has to be carried by hand into
the next two. Those are not preferences - they are where this codebase actually breaks.

## Owner

Idea author. Tech Lead joins at phase 6 if the stage gate flagged more than one stage.

## When to use

- «нова фіча <slug>», «бриф для <фіча>», «розкопай ідею <slug>».
- `/discovery <slug>` as explicit invocation.
- A raw idea in prose plus «оформи це як бриф».
- Skip if `docs/features/<slug>/idea-brief.md` already exists with `status: Confirmed`
  and is younger than two weeks. Update it, do not rewrite.

## Inputs

- `<slug>` - kebab-case, short. If absent, propose 2-3 and let the user pick.
- (Optional) an id from `Features_list.json`. If given, quote it in `ticket:`.

## Depth regulator

Eight sub-agents on an XS idea is not rigour, it is a tax. The depth is chosen once, at
phase 0.25, and recorded in the brief's frontmatter as `depth:`.

| Depth | Interview | Phases 4-8 | Phases 9-11 |
|---|---|---|---|
| easy | at most 2 rounds of the design tree | no sub-agents: 1-2 searches for §6, three approaches of one paragraph each, an own list of 3-5 attack vectors instead of the devil's advocate | RICE and recommendation merged into one confirm |
| medium (default) | tree runs until the frontier empties | full protocol below | separate confirms |
| hard | tree runs to empty plus one extra round on whatever the four lenses disagreed about | full protocol, §6 widened to 5+ competitors | separate confirms |

Two things never scale down. **The stage gate is always full** - all three cross-checks
run at every depth, because the answer they protect is inherited by every later section
and is the cheapest one in the brief to get wrong. **All 17 sections are always filled**;
easy makes them shorter, never absent.

Easy does not make the checkpoints optional either. Its handful of AskUserQuestion calls
are real, and fabricating one voids the run exactly as it does at medium.

## Mode handling

Phases 0-11 are read-only (Read, WebSearch, Agent, AskUserQuestion). `ExitPlanMode`
fires at 11.5; phases 12-14 write. The AskUserQuestion checkpoints in phases 0.25, 0.5,
1, 2, 9, 10, 11 are a data-input protocol, not clarifying questions: fabricating any of
them turns the artifact into a reconstruction from model memory and voids the whole run.
Auto Mode does not override them.

## Question style

Every AskUserQuestion here is Ukrainian, and written so that a recruiter with no
engineering background can answer without help.

- `question` holds three blocks: where we are and what is already collected; what breaks
  if the answer is wrong; what to look at before choosing.
- Every option `description` says what will physically change in the brief, restates the
  option in plain words, and names the hidden trade-off if there is one.
- Domain words from `CONTEXT.md` are used exactly as defined there. If a word is about to
  be used in a second sense, stop and say so - that is the failure this glossary exists
  to prevent.
- **Every question carries a recommended answer.** The recommendation is the first option
  and its label ends with `(Рекомендовано)`; its description says why this one and not the
  neighbour. Four equal-looking options put the whole burden of the decision on someone
  who came here with an idea, not with a ranking. A recommendation is easier to disagree
  with than a blank, and disagreement is the signal this interview is trying to collect.
- **Look first, then ask.** Before asking for a number, a date, a count or a name that
  lives in the repository, go read it. What may be read: `Features_list.json`,
  `docs/features/`, `CONTEXT.md`, `Progress.md`, and the `services.py` of the stage in
  question. What is never read: the database. It holds candidate personal data, and no
  product question is worth touching it.

  The search has three possible endings, and **two of them end in a question**:

  | What the search found | What to do |
  |---|---|
  | A clear answer | Offer it as the drafted answer and let the user correct it. Say where it came from. |
  | Something unclear, stale, or contradicting itself | **Ask.** Show what was found, say plainly why it is not enough, let the user settle it. |
  | Nothing | **Ask.** Say out loud that you looked and where, then ask in plain words. |

  «Not found» is never a reason to guess, to leave the section empty, or to quietly drop
  the question. It is a reason to ask a *better* question, because now you also know that
  the repository is silent on this - and telling the user that is itself useful, it may be
  the first time anyone noticed.

- **Plain words, always, and one example per question.** The person answering may be a
  recruiter who has never opened this repository. Three rules make that work:

  1. **No untranslated jargon.** Every technical or domain word gets a short gloss right
     there in the sentence, even if it is in `CONTEXT.md`. The glossary exists for the
     brief, not for the interview.
  2. **Every question carries a concrete example of an answer.** Not «як часто це
     трапляється?» but «як часто це трапляється? Наприклад: раз на тиждень, раз на
     вакансію, приблизно двічі на місяць». An example shows the *shape* of the expected
     answer, which is the thing a person most often cannot guess.
  3. **The self-test before sending.** Read the question as someone who knows hiring and
     nothing about code. If any sentence needs a second sentence to become clear, that
     second sentence was missing from the question.

  Worked before-and-after examples, including how to ask when the search found nothing:
  → [./references/ask-examples.md](./references/ask-examples.md)

- Forbidden: bare English labels, one-line descriptions, jargon without a gloss, a question
  with no recommended answer, a question with no example answer, and silently skipping a
  question because a lookup came back empty.

## Protocol

**14 phases. 0-11 read-only. 11.5 = ExitPlanMode. 12-14 write, self-check, propose commit.**

The fractional numbers (0.25, 0.5, 8.5, 11.5) are deliberate. Each was inserted next to the
phase it protects rather than renumbered onto the end, so a reference written in an older
brief still points where it did. Phase 8.5 runs right after the devil's advocate because it
consumes its output; phase 0.25 runs before the stage gate because depth changes how much
of the gate's disagreement can be researched.

### 0. Setup (read-only)

- **Read** `./templates/idea-brief.md` into session memory. Do not copy yet.
- **Read** root `CONTEXT.md` - load `## Glossary` and `## Invariants` as session state.
- **Read** `Features_list.json` - find whether this idea already has an id, or overlaps
  an existing entry. An idea that duplicates a registry entry is a registry problem
  first and a brief second.
- **Verify** the target brief does not already exist as Confirmed.

### 0.25. Depth checkpoint (AskUserQuestion - mandatory)

One question: easy, medium or hard (see «Depth regulator»). Recommend a depth from what
phase 0 already read - an idea that duplicates a `Features_list.json` entry, or one whose
slug has no adjacent brief anywhere, are different problems and deserve different depths.
Record the answer; it is written to frontmatter `depth:` in phase 12.

### 0.5. Stage gate (AskUserQuestion - mandatory, blocking)

Before any product question. Four stages exist and each is a clone of the previous one:

| Stage | What it is |
|---|---|
| question bank | reusable questions, topics, tech stacks |
| template form | reusable blueprint, draft and publish |
| working form | per-vacancy copy, collaborative voting and approval |
| evaluation form | per-candidate snapshot, scores, feedback, report |

Ask which stage the idea lives in. **If the answer is two or more, stop.** Offer to split
into that many slugs and brief them separately, in dependency order. Two stages in one
brief means every later section has to hedge, and the hedging is what makes a brief useless.

A cross-cutting idea that genuinely spans stages (notifications, audit, analytics) is not
an exception: brief the stage that must ship first, and record the rest in §16.

**The answer is never taken on trust.** Two checks run right here, a third fires later in
phase 12. None of them overrules the user: each one surfaces a disagreement together with
the evidence that produced it, and asks again.

**Check A - vocabulary markers.** Every stage owns distinctive words, and they are already
in `CONTEXT.md`. Count which family dominates the phase-1 raw idea:

| Words in the idea | Stage they point at |
|---|---|
| approval, approver, deletion vote, vacancy, panel | working form |
| score, feedback, report, completion, candidate, CRM note | evaluation form |
| draft, publish, blueprint, reuse | template form |
| difficulty, topic, tech stack, question author | question bank |

If the dominant family disagrees with the stated stage, show both and re-ask, quoting the
words that produced the count. This costs nothing: it counts words the user already said,
and it has no opinion to be talked out of.

**Check B - name one concrete thing.** Ask the user to name one element of that stage the
idea touches: a form, a field, a role, a moment in the flow. If nothing can be named, the
answer is almost certainly wrong - an idea genuinely belonging to a stage always has at
least one concrete anchor in it. Hesitation here is itself the signal; record what was
named, it becomes the first line of §16.

### 1. Idea capture (AskUserQuestion - mandatory)

One question, free text: «опиши ідею в 1-3 реченнях своїми словами». Store verbatim as
the §1 draft. Never edit it - it is the baseline the rest of the brief is checked against.

### 2. Design-tree interview (AskUserQuestion - mandatory)

Not a list of questions - a **tree**. Every answer settles one decision and branches into
the decisions that hang off it. The five categories below are the seed of the tree, not
the running order.

**The frontier** is every decision whose prerequisites are already settled: the questions
answerable *now* without guessing at something not yet heard. Ask the whole frontier in one
round. Then wait, and let the answers reshape the tree - settled decisions push the
frontier outward and unblock what depended on them. Recompute, ask the next round.

A question whose answer depends on another question still open in this round belongs to a
**later round**. This is the rule that a fixed bank of questions cannot express, and it is
the whole reason for the change: a question asked before its prerequisite gets an invented
answer, and an invented answer is indistinguishable from a real one three sections later.

Mechanics that matter in practice:

- `AskUserQuestion` carries at most four questions per call. A frontier wider than four is
  split across consecutive calls **inside the same round**, in the order the tree produced
  them. Never reorder to fill a call, and never promote a later-round question to pad one.
- Anything the repository can answer is looked up, not asked - see «Facts are found, never
  asked» above. A running lookup is an unsettled prerequisite: only the questions
  downstream of it wait, the rest of the frontier goes out now.
- **Termination is the empty frontier**, not a question count. At easy depth the tree is
  capped at two rounds, and whatever is still open goes to §15 as an open question with an
  owner - which is honest, unlike a tree silently declared finished.
- Record which round each answer came from. The order in which a decision became
  answerable is itself evidence about what depends on what, and §16 consumes it.

The seed categories, written for the people who use a hiring form rather than a generic
B2B buyer:

**Whose pain, precisely.** Which of the four roles - recruiter, hiring manager,
interviewer, candidate - loses time or information today? How often: per interview, per
vacancy, per quarter? What do they do instead right now, and what does that cost?

**Why this and not the cheaper thing.** What was tried before? Is this a product gap or a
process gap wearing a product costume? Would a template change, a checklist, or a
convention solve 80% of it without any code?

**What «worked» means in numbers.** Which number moves - feedback turnaround, share of
interviews with complete scores, agreement between interviewers, time to decision? What
is it today, what would be enough?

**Constraints that are already true.** Does it touch candidate personal data? Does anyone
outside the company see the output? Is there a moment in the hiring flow it must fit into,
or does it break the interviewer's attention during a live interview?

**Fit with what exists.** Does the same information already live in a form, a report, or
the CRM note? Duplicating it is cheaper to build and more expensive to keep true.

### 3. Glossary capture (deferred)

Collect every new domain word into `pending_glossary_terms`. Do not write to `CONTEXT.md`
here - that happens in phase 12.

For each candidate term also draft its **NOT-reference**: the concept it gets confused
with. A NOT-reference may legally point at exactly three things:

1. another term that has its own glossary entry,
2. a code object, named in backticks - that reads as «look in the code»,
3. something that deliberately does not exist in this system.

A NOT that names a fourth thing - a term-shaped word with no entry - is a defect: it
promises a definition and delivers nothing. Check the draft against the loaded glossary
before adding it.

Skip generic technology words. This product's real ambiguity lives in its own vocabulary:
the three form stages, `score` against `max score`, `vacancy level` against
`assessed level`, and the three different removal flags.

### 4. Competitive research (read-only, no user input)

3-5 competitors or adjacent solutions via WebSearch. Table: product, URL, features, value
per feature 1-5, gap. Each row footnotes the date and the query used. An internal-only
capability is written as `N/A - internal tool` with a reason. Inventing competitors
because the section looks empty is worse than an honest N/A.

### 5. Strategic approaches (3 parallel sub-agents, read-only)

Three personas, one message, parallel calls. Each returns: name of 3-5 words, a
one-sentence thesis in product language, who it serves from §3, one outcome metric with
baseline and target, one key trade-off, and an effort signal S/M/L.

- **A - Simplicity.** The shortest path. Fewest new concepts.
- **B - Differentiation.** The version that makes this product better than a spreadsheet
  plus a call recording.
- **C - Balanced.** The trade-off between the two.

Each sub-agent is additionally told the recurring forks of this product, and must say
which side of the relevant ones its approach takes, in domain language:

- a new stage in the pipeline, or a new field on a stage that already exists;
- computed while the user waits, or computed in the background and shown later;
- pushed to open forms as it happens, or visible on next open;
- guaranteed by a rule the data itself enforces, or by a check in one code path;
- copied into the next stage at clone time, or looked up from the earlier stage.

The last two matter more than they look. A rule enforced only in one code path is not
enforced in the admin, in a shell, or in a management command. Anything not copied at
clone time silently changes history when the earlier stage is edited.

### 6. Four-lens review (4 parallel sub-agents, read-only)

Two axes are deliberately mixed here, because they catch different things. **Expertise**
asks by what knowledge this is judged; **impact** asks who it lands on. One axis alone
leaves a blind spot the other would have covered.

Each persona sees all three approaches and returns 3-5 bullets per approach. Product
language only - no library, storage, or framework names.

- **Engineer** *(expertise)*. How many moving parts must agree for this to work, what
  breaks first and how anyone would notice, how much of it depends on something outside
  our control. Also judges whether the downstream cost stated in §16 is understated -
  a second opinion on the author's own estimate. Abstract only: complexity, failure
  modes, integration surface, never a named technology.
- **Interviewer** *(impact + usability)*. The person doing this during or right after a
  live interview, with the candidate still in the room. Attention cost, how much it adds
  to a form they already find long, whether it changes their judgement before they have
  committed to it. Usability half: would they find this feature without being told, and
  would they understand it the first time.
- **Hiring side** *(impact + business viability)*. Recruiter and hiring manager together:
  does it shorten time to decision, does it make a decision defensible, does it produce
  something worth sending to the CRM, what does it cost per vacancy. **One bullet is
  mandatory and is about opportunity cost**: name what does not get built while this does,
  by pointing at a real `Features_list.json` entry or an adjacent brief. Everything in a
  brief looks worth doing when nothing is standing next to it, and this is the only lens
  positioned to put something there.
- **Candidate** *(impact + usability)*. The one person affected who never sees the tool.
  Consent, what is recorded about them, whether a decision becomes less explainable.
  Usability half: would they accept this process if it were described to them in full,
  and would they understand what was decided about them and why.

Build the synthesis matrix, 4 personas by 3 approaches, six-word justification per cell.

Two notes on why this set and not the textbook trio. A separate usability researcher is
deliberately absent: in this product usability is not one thing, it is sharply different
for an interviewer mid-call and for a candidate who never opens the tool, so a single
persona would write the average of two people and describe neither. And the candidate
lens is not decoration - it is the only lens whose subject cannot complain, so nothing
else in the process will raise what it raises.

### 7. Trade-offs and edge cases (synthesis, read-only)

Pros and cons per approach, plus 5-8 edge cases any approach must survive. At least two
must come from the mechanics of this product rather than from the idea: what happens on a
form that is already completed, what happens when an interviewer never submits, what
happens when someone is removed from the panel mid-process, what happens to a candidate
who is interviewed twice for different vacancies.

### 8. Devil's advocate (1 sub-agent, clean context, read-only)

Spawn with no upstream session memory: «знайди, як це провалиться. 5-10 attack vectors,
кожен із сигналом, за яким це помітять - що саме зламається і як це проявиться».
The sharpest vector is reserved for the Risks half of §10, the rest join §9.

Clean context is the whole point. A devil's advocate that has read the optimism above
argues with it politely instead of attacking it.

### 8.5. Assumptions (synthesis, read-only)

A listed risk is a worry. Turn the 3-5 sharpest into **assumptions that can be proved
wrong**, and write them into the second half of §10. Each one is a sentence the brief is
currently betting on, stated so plainly that it is obvious what would refute it.

Three columns, and every one of them has to be fillable or the row is not an assumption:

| Column | What makes it valid |
|---|---|
| Assumption | A claim about the world, not about the plan. «Interviewers submit late because they forget» is one; «we will build reminders» is not. |
| If it is wrong | The concrete consequence for *this* brief - which approach dies, which section becomes false. «It would be bad» means the assumption was not sharp enough. |
| Cheapest check | Something doable before any code: read what is already in the repo, count rows in an existing report, ask three people, watch one interview. If the only check is «ship it and see», say so - that is a real answer and it belongs in Confidence. |

Rank by damage-if-wrong, not by likelihood. The assumption most likely to be wrong is
usually already known and hedged; the one nobody questioned is the one that ends the
feature. The top row feeds `Confidence` in phase 9 directly: an untested top assumption is
what a Confidence below 1.0 actually means, and naming it stops that number from being a
mood.

At easy depth this phase still runs - it is synthesis, not a sub-agent, so it costs almost
nothing and it is the only place the brief commits to being falsifiable.

### 9. RICE (AskUserQuestion - mandatory)

Claude computes, the user confirms or adjusts. Reach from §3. Impact from §2 severity
plus the hiring-side bullets. **Confidence from the assumptions in §10** - it is set by
whether the top assumption has a check that was actually run, and the count of open
questions in §15 only adjusts it from there. Effort from the §7 signal, S being 1-2
person-weeks, M being 3-5, L being 6-12. Each rationale quotes the section it came from.

Confidence is the number this framework invites you to fake, because it is the only input
with no external referent and it moves the result. Anchoring it to a named assumption is
what stops it from being set to whatever makes the ranking come out as expected.

Never ask the user for the four numbers directly. They have no grounding to answer, and
the result is a number that looks computed and is not.

### 10. Feasibility (read-only repo scan + AskUserQuestion - mandatory)

Scan before proposing, and name what was read. For this repository the useful evidence is:
`Features_list.json` for what already shipped in the same area, `docs/features/` for
adjacent briefs, the `services.py` of the stage named in phase 0.5, and `Progress.md` for
whether this already has a planned position.

Three checkboxes - Tech, Skills, Time - each with a rationale citing something the scan
actually found. «We know how» without a citation is a guess wearing a checkbox.

### 11. Recommendation (AskUserQuestion - mandatory)

Pick one approach, write 3-5 sentences. The rationale must cite the RICE score, the
feasibility state, at least one synthesis-matrix cell, and at least one competitive gap.
Then confirm with the user: accept, pick a different approach, or mark TBD.

### 11.5. ExitPlanMode handoff

Plan: create the directory, copy the template, hand the pending glossary terms to
`fix-term-local`, fill all 17 sections, run the self-check, propose the commit. If
`ExitPlanMode` is unavailable the run was not started in plan mode - go straight to 12.

### 12. Execute

Create `docs/features/<slug>/`, copy the template, fill every section from session memory.
Frontmatter: `status: Confirmed`, `depth` from phase 0.25, `stage_touched` from phase 0.5,
RICE and feasibility both `confirmed`, `updated_at` today. The two approaches not selected
go to §14 with a reason and a revisit trigger.

**Glossary terms go to `fix-term-local`**, as one batch, `pending_glossary_terms` from
phase 3. That skill already expects this batch by name; naming it back here closes a link
that was one-way. It decides per term whether the word belongs in the root `CONTEXT.md` or
in the feature's own delta, and it asks a human before writing either - do not write to
`CONTEXT.md` directly from this phase. If the skill is unavailable, leave the terms in §17
and say so in the handoff rather than guessing at the boundary yourself.

**Check C - the §16 trap.** §16 asks four yes/no questions about downstream cost: does a
new field appear that the clone has to carry forward, does what other people already have
open change, is completion and what it deletes involved, does the result reach the report
or the CRM note. **Two or more «yes» means the stage answer is probably wrong** - the idea
is reaching into a neighbouring stage even though it was declared to live in one. Re-open
the phase 0.5 question, quoting which two answers triggered it, and let the user decide:
narrow the idea, or split the brief.

This check fires here rather than at the gate on purpose. At the gate nobody knows the
downstream cost yet - it only becomes visible after the approaches exist. A check that can
only run early would miss exactly the cases that mature during the conversation.

### 13. Self-check

- **17 sections present**, none empty. `<!-- TBD -->` is allowed where something is
  honestly unknown; an empty heading is not.
- **No implementation vocabulary in the body.** Storage engines, brokers, library names,
  table schemas, endpoints, latency targets. This is a product brief.
- **Per-section word budgets**, not one number for the document:

  | Section | Budget |
  |---|---|
  | §1-§5 together | 350 |
  | §6 Competitive | 250 |
  | §7 Approaches | 450 |
  | §8 Four-lens review | 500 |
  | §9 Trade-offs and edge cases | 350 |
  | §10-§12 | 450 |
  | §13-§17 | 850 |
  | **Total** | **3200** |

  **This table is the only source.** The template used to carry its own copies of these
  numbers in HTML comments, and they had drifted apart - the template said 300 and 400
  where this table said 350 and 850, so the self-check agreed with whichever file was
  read last. The template now points here instead of restating.

  History, because these numbers are measured rather than legislated. The last two rows
  were corrected on 2026-09-02 after the first real run: inherited from a 15-section
  template and applied to a 17-section one, they left §16 and §17 with no words allocated.
  §10-§12 grew from 350 to 450 on 2026-09-05, when §10 took on the assumptions table.
  Treat every number here as measured-and-revisable - a budget invented rather than
  measured is the same disease it exists to cure, one level up.

  When a section is over, compress *that* section - the budget
  names the target, so compression has an address instead of «cut something».
  §8 and §9 are the last to be cut, because §13 cites them and the next stage consumes them.

- **§10 carries 3-5 assumptions**, each with all three columns filled. A row whose
  «cheapest check» is empty is a risk that got promoted without earning it.
- **§13 cites four upstream sections.**
- **§16 names exactly one stage**, matching phase 0.5, and carries fewer than two «yes»
  among its four downstream questions. Two or more means check C fired and was either
  resolved or explicitly accepted with a written reason.
- **Every NOT-reference drafted in §17 resolves** to a glossary entry, a backticked code
  object, or an explicitly non-existent thing.

Failing check: fix that section, re-run. Recording a check as failed with an honest
reason beats a green mark that is not true.

### 14. Propose commit and next owner

Propose, do not execute:

```
01: idea for <slug> via discovery
```

Next owner and next step, named rather than implied:

1. **`fix-term-local`** takes the §17 batch, if phase 12 could not reach it.
2. **Whoever writes the PRD** takes the brief. The gate they inherit is `status: Confirmed`
   plus exactly one stage in §16 - a brief that fails either is not ready to be read.
3. **`Features_list.json`** gets the entry, or has its existing entry updated with this
   slug. An idea that lives only in `docs/features/` is invisible to the registry that
   the rest of the process reads.

If the recommendation contains a hard-to-reverse choice, note it in §15 rather than
deciding it here.

## Definition of Done

- `docs/features/<slug>/idea-brief.md` exists, all 17 sections filled.
- Frontmatter records the `depth` chosen at phase 0.25.
- The design tree terminated on an empty frontier, or, at easy depth, on the two-round cap
  with every unanswered branch written into §15 with an owner.
- §10 carries 3-5 assumptions, each with a consequence and a cheapest check.
- §8 Hiring side carries its mandatory opportunity-cost bullet, pointing at a real
  `Features_list.json` entry or an adjacent brief.
- Confidence in §11 names the §10 assumption it was derived from.
- Every fact that could not be found in the repository became a question, not a guess, and
  the question said where the search had looked.
- Every question that reached the user was in plain words with a gloss on every domain term
  and at least one example of the shape of answer expected.
- Exactly one stage named in §16, and it matches the phase 0.5 answer.
- All three stage cross-checks ran: vocabulary markers (A), one named element (B), the
  §16 downstream trap (C). A disagreement is allowed to stand, but only in writing.
- Every glossary term added in this run has a NOT-reference that resolves.
- No implementation vocabulary in the body.
- Every section within its word budget, or over it with a written reason in the DoD block.
- Frontmatter Confirmed, RICE and feasibility both confirmed.
- §13 cites §6, §8, §11, §12.
- The AskUserQuestion checkpoints in phases 0.5, 1, 2, 9, 10, 11 actually fired.

## Anti-patterns

- **Skipping the stage gate.** It is phase 0.5 and not phase 5 because every later
  section inherits the answer. A brief that hedges across two stages produces a PRD that
  hedges, and a task list nobody can size.
- **A brief that spans two stages «because they are related».** They are always related.
  That is what a pipeline is.
- **Taking the stage answer on trust.** It is one sentence that every later section
  inherits, and it is the cheapest sentence in the whole brief to get wrong. Three checks
  exist for it; running none of them and calling the gate «done» is the failure this
  skill was written to prevent.
- **Overruling the user with a check.** All three cross-checks surface a disagreement
  with its evidence and ask again. None of them decides. A check that silently corrects
  the author teaches the author to stop reading it.
- **Using easy depth to skip the stage gate.** Depth scales the research, never the gate.
  A cheap run that briefs the wrong stage is not cheap, it is wasted plus misleading.
- **Padding a frontier round.** Pulling a later-round question forward to fill an
  `AskUserQuestion` call defeats the only thing the tree does: it asks that question before
  its prerequisite is settled, and gets an answer the user had to invent.
- **Declaring the tree finished because the answers got thin.** Termination is an empty
  frontier. Thin answers mean the questions were badly aimed, not that the branch is done.
- **Four equal options with no recommendation.** The person answering came with an idea,
  not with a ranking. A recommendation they can push back on collects more signal than a
  blank they have to fill.
- **Asking for a fact the repository holds.** Every such question spends attention on
  lookup that should have gone to judgement, and the user may well answer from memory less
  accurately than the file would have.
- **Treating an empty search as permission to guess.** This is the mirror failure of the
  one above, and it is worse, because the number it invents looks exactly like a number
  that was checked. Nothing found means ask - and say where you looked, because the silence
  of the repository is a finding in its own right.
- **Dropping a question because the search failed.** The question did not become less
  important; only the shortcut disappeared. A section filled from model memory rather than
  from a person is the exact artifact this skill exists to prevent.
- **Jargon in a question.** `CONTEXT.md` is the vocabulary of the *brief*, not of the
  interview. In a question, every domain word carries a short gloss in the same sentence,
  even one the glossary defines - the person answering has not read it.
- **A question with no example answer.** «Як часто це трапляється?» leaves the person
  guessing at what shape of answer is wanted. «Раз на тиждень? Раз на вакансію?» costs six
  words and removes the guessing.
- **Reading the database to answer a product question.** It holds candidate personal data.
  There is no brief worth that, and the files answer everything a brief actually needs.
- **Dropping the engineer lens to save a sub-agent.** It is the only one that judges
  whether the downstream cost in §16 is understated, and the author is the worst possible
  reviewer of their own estimate.
- **A new term without a NOT-reference.** In a product with three things called «form»
  and two scales called «бал», a definition without a boundary is half a definition.
- **A NOT-reference pointing at an undefined term.** Worse than no entry: a missing word
  is an honest gap, a dangling pointer is a promise that fails when someone follows it.
- **User-entered RICE numbers.** The user has no grounding for Reach or Effort. Claude
  proposes from upstream sections, the user confirms.
- **Confidence set without naming an assumption.** It is the one input with no external
  referent and it moves the result, so it is the one that gets tuned until the ranking
  looks right. Anchor it to a §10 row or leave it TBD.
- **Assumptions that restate the plan.** «We will send reminders» is a plan. «Interviewers
  submit late because they forget» is an assumption: the world can disagree with it.
  A row nothing could refute is a sentence, not a check.
- **Ranking assumptions by likelihood.** The likely-wrong ones are already hedged. Rank by
  what it costs to be wrong, which is how the unquestioned one surfaces.
- **A brief where nothing was given up.** If the Hiring side lens found no opportunity
  cost, it did not look. Something is always waiting in `Features_list.json`.
- **Writing `CONTEXT.md` from phase 12.** Terms go to `fix-term-local` as a batch; it
  knows the canon-versus-delta boundary and asks a human. Bypassing it puts words into the
  canonical glossary that no human approved.
- **Restating a word budget in the template.** The table in phase 13 is the only source.
  Two copies drift, and the drift is invisible until the self-check quietly agrees with the
  wrong one - which is exactly what happened here between 2026-09-02 and 2026-09-05.
- **Implementation vocabulary in the body.** Storage engines and endpoints belong to later
  stages. Stage names, form names, and scoring words are domain vocabulary and are welcome.
- **Devil's advocate sharing the session context.** It will agree politely. Spawn clean.
- **Feasibility without a citation.** Name the file the scan read, or mark it TBD.
- **Skipping the candidate lens** because the candidate is not the buyer. Consent and
  explainability surface nowhere else, and they surface late and expensively.
- **Cutting §8 or §9 to hit a word count.** They are cited by §13 and consumed by the
  next stage. Cut §6 and §7 first; if the document is still over, say so in the DoD block
  instead of removing content the next stage needs.
- **Silently rewriting a Confirmed brief.** Update it, and say what changed.

## Template and references

- Brief skeleton → [./templates/idea-brief.md](./templates/idea-brief.md)
- How to word a question, with worked before-and-after pairs and the three ways a failed
  lookup turns into a question → [./references/ask-examples.md](./references/ask-examples.md)

## Example invocation

> **User:** «нова фіча: інтерв'юери забувають здати фідбек, рекрутер дізнається про це
> через тиждень»
>
> **Skill:**
> 1. **Phase 0** - proposes the slug `feedback-reminders`. Reads `CONTEXT.md` and
>    `Features_list.json`, finds `FN-1` already covers notifications, and says so.
> 2. **Phase 0.5** - stage gate. The user answers «working form and evaluation form».
>    The skill stops and offers two slugs: approval reminders on the working form,
>    feedback deadlines on the evaluation form. The user picks the second. Check A agrees
>    - «фідбек», «дедлайн», «завершення» all belong to the evaluation-form family.
>    Check B: the user names «фідбек, який інтерв'юер ще не здав», so the anchor is real.
> 3. **Phase 0.25** - depth. Recommends medium, because `FN-1` overlaps and the overlap
>    needs the four lenses to resolve. The user takes it.
> 4. **Phase 1** - raw idea captured verbatim.
> 5. **Phase 2, round 1** - the frontier holds three decisions, each with a recommended
>    answer: whose deadline it is, whether it is one date or one per interviewer, and what
>    counts as «submitted». «How many interviews per quarter» is *not* asked - it is read
>    off `Features_list.json` and offered as a drafted answer, which the user corrects
>    downwards. «What share of interviews end with no feedback at all» *is* asked: the same
>    search came back empty, so the question says so out loud, names the four places it
>    looked, and offers «roughly one in three» as the recommended shape of an answer.
> 6. **Phase 2, round 2** - «one per interviewer» settled in round 1 unblocks two branches
>    that were previously unanswerable: who is told when the deadline passes, and whether
>    a late submission still counts. Both go out together. Frontier empty after round 3.
> 7. **Phase 3** - «нагадування» and «дедлайн фідбеку» go to the pending list, each with
>    a drafted NOT-reference against `completion`.
> 8. **Phases 4-8** - research, three approaches, four-lens review, devil's advocate.
>    The candidate lens asks whether a chased interviewer writes a worse feedback; the
>    engineer lens flags that «visible to everyone already in the form» is a second
>    moving part nobody counted; the hiring-side lens names `FN-1` as what waits.
> 9. **Phase 8.5** - the top assumption becomes «інтерв'юери спізнюються, бо забувають, а
>    не бо не мають що сказати». If it is wrong, every approach here is aimed at the wrong
>    cause. Cheapest check: ask three interviewers who were late last quarter.
> 10. **Phases 9-11** - Confidence set to 0.7 and cites that unchecked assumption by name,
>    feasibility cites `tasks.py` as the adjacent scheduled work, recommendation accepted.
> 11. **Phases 12-14** - brief written, terms handed to `fix-term-local`, self-check finds
>    §7 over budget by 60 words and compresses §7 only, commit proposed as
>    `01: idea for feedback-deadlines via discovery`.
