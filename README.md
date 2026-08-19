# Evaluation Form Service

A Django REST Framework backend for running structured technical interviews end-to-end: build a question bank, assemble reusable interview templates, collaboratively review and approve per-vacancy working forms in real time, then evaluate candidates with per-question scoring, interviewer feedback, auto-generated HTML reports, and PeopleForce CRM synchronization.

## Table of Contents

- [How It Works](#how-it-works)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [API Overview](#api-overview)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Development](#development)
- [Git Workflow](#git-workflow)

## How It Works

The core domain is a four-stage form lifecycle. Each stage is a **clone with snapshots** of the previous one, so historical data never changes retroactively:

```
┌───────────────┐    ┌───────────────┐    ┌────────────────┐    ┌──────────────────┐
│ Question Bank │ →  │ TemplateForm  │ →  │  WorkingForm   │ →  │  EvaluationForm  │
│ topics, tech  │    │ reusable      │    │ per-vacancy,   │    │ per-candidate,   │
│ stacks,       │    │ blueprint,    │    │ team approval  │    │ scoring, feedback│
│ questions     │    │ draft/publish │    │ + live voting  │    │ report, CRM sync │
└───────────────┘    └───────────────┘    └────────────────┘    └──────────────────┘
```

1. **Question Bank** — questions organized by topic and tech stack, with difficulty (Easy/Medium/Hard), source tracking (template / added / modified / AI-generated), usage counters, and soft deletion.
2. **Template Form** — a manager assembles topics and questions into a reusable interview blueprint. Edits are saved as a **draft** (`draft_data`) and only affect live forms after explicit **publish**, so templates already in use stay stable.
3. **Working Form** — created from a template for a specific vacancy (level, project, interviewers, recruiters, hiring manager). Interviewers collaborate in **real time over WebSockets**: adding topics/questions, voting to remove items, and approving the form. An item is effectively removed only when *all* approvers vote for deletion; the form becomes `approved` when every approver signs off.
4. **Evaluation Form** — a recruiter clones an approved working form for a specific candidate and interview datetime. Interviewers score each question (0–3: No/Weak/Medium/Strong answer, max score = difficulty × 3), flag questions outside their expertise, and submit final feedback (pros, cons, hire decision, assessed level). When every interviewer submits, the form is completed, a static **HTML report** is generated, and the result can be pushed as a note to the candidate's **PeopleForce** card.

Status automation: a Celery beat task moves evaluation forms from `pending` to `in_progress` one hour before the scheduled interview.

## Key Features

- **JWT authentication** (access/refresh rotation + blacklist) with a custom email-based user model
- **Role model**: Hiring Manager, Manager, Recruiter, Interviewer — with fine-grained object-level permissions per action (only assigned interviewers can score, only recruiters create evaluations from approved forms, etc.)
- **Real-time collaboration** on working forms via Django Channels + Redis (votes, approvals, added questions broadcast to all connected users); WebSocket auth via JWT middleware
- **Snapshot pattern** — form items store copies of question text/difficulty/topic/score so past interviews remain historically accurate
- **Soft deletion & voting-based removal** with full history preserved
- **Draft/publish workflow** for templates
- **HTML evaluation reports** rendered from a template and stored in media
- **PeopleForce CRM integration** — evaluation summary + report link posted to the candidate profile
- **Background processing** — Celery worker + beat (DB scheduler) + Flower monitoring
- **OpenAPI documentation** — Swagger UI and ReDoc via drf-spectacular
- **Modern admin** — django-unfold + nested inlines, read-only proxy views for templates
- **API hygiene** — pagination, anon/user throttling, django-filter, nested routers

## Tech Stack

| Layer | Technology |
|---|---|
| Language / Framework | Python 3.12, Django 5.2, Django REST Framework 3.16 |
| Async / Real-time | Daphne (ASGI), Django Channels 4, channels-redis |
| Database | PostgreSQL 16 (psycopg 3) |
| Cache / Broker | Redis |
| Background jobs | Celery 5.5, django-celery-beat, Flower |
| Auth | djangorestframework-simplejwt |
| API docs | drf-spectacular (Swagger / ReDoc) |
| Admin | django-unfold, django-nested-admin |
| Static files | WhiteNoise |
| Tooling | black, flake8, django-debug-toolbar |
| Deployment | Docker, docker-compose |

## Project Structure

```
evaluation_form_service/
├── evaluation_form_service/   # settings, urls, asgi (Channels routing), celery config
├── employee/                  # custom user model (email login, roles, levels)
├── techstack/                 # tech stacks + wait_for_db management command
├── topic/                     # question topics
├── question/                  # question bank (difficulty, source, usage stats)
├── project/                   # projects vacancies belong to
├── template_form/             # reusable templates, draft/publish, snapshot base models
├── working_form/              # per-vacancy forms: approval, voting, WebSocket consumers
├── evaluation_form/           # candidate evaluations: scores, feedback, reports, CRM sync
├── templates/reports/         # HTML report template
├── fixtures/initial_data.json # seed data
├── docker-compose.yaml        # app + db + redis + celery + beat + flower
└── Dockerfile
```

Each app follows the same layout: `models.py`, `serializers.py`, `views.py`, `permissions.py`, `urls.py`, and — for multi-model workflows — `services.py` (business logic lives here, views stay thin).

## API Overview

Base URL: `/api/`. Interactive docs: **`/api/doc/swagger/`** and **`/api/doc/redoc/`**, schema at `/api/schema/`.

| Prefix | Purpose |
|---|---|
| `/api/employees/` | users, JWT token obtain/refresh |
| `/api/projects/`, `/api/techstacks/`, `/api/topics/`, `/api/questions/` | reference data & question bank CRUD |
| `/api/template-form/` | templates: CRUD, draft save, publish, clone to working form |
| `/api/working-form/` | working forms + nested `/topics/` and `/items/`, approval & voting actions |
| `/api/evaluation-form/` | evaluation forms, `evaluation-scores`, `evaluation-feedbacks` (with `submit`), `candidates`, `sync_crm` action |
| `ws/working_form/<form_id>/` | WebSocket: live votes, approvals, form updates |

## Getting Started

### Prerequisites

- Docker + Docker Compose (recommended), or Python 3.12 with local PostgreSQL and Redis

### Run with Docker

```bash
git clone <repository-url>
cd evaluation_form_service
cp .env.example .env   # create and fill in (see Environment Variables)
docker-compose up --build
```

This starts: API (Daphne) at http://localhost:8000, PostgreSQL at :5432, Redis at :6379, Celery worker, Celery beat, and Flower at http://localhost:5555.

```bash
# create an admin user and load seed data
docker-compose exec evaluation_form python manage.py createsuperuser
docker-compose exec evaluation_form python manage.py loaddata fixtures/initial_data.json
```

### Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py wait_for_db
python manage.py migrate
python manage.py runserver          # or: daphne evaluation_form_service.asgi:application
```

## Environment Variables

Create a `.env` file in the project root:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | `True` / `False` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | database connection |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | e.g. `redis://redis:6379/0` |
| `PEOPLEFORCE_API_KEY`, `PEOPLEFORCE_API_URL` | PeopleForce CRM integration |

## Development

```bash
python manage.py test               # run tests
python manage.py test working_form  # tests for one app
flake8                              # lint
black .                             # format
```

See [CLAUDE.md](CLAUDE.md) for an architecture deep-dive, [Features_list.json](Features_list.json) for the feature backlog, and [Progress.md](Progress.md) for the improvement roadmap (AI integrations, analytics, L&D).

## Git Workflow — Feature Branch Flow

```
main        # Stable version (Prod)
develop     # Current development
feature/*   # New functions
bugfix/*    # Bug fixing
hotfix/*    # Immediate fixing
```

1. **Start a feature**: `git checkout develop && git checkout -b feature/function-name`
2. **Branch naming**: `feature/user-authentication`, `bugfix/fix-validation-error`, `hotfix/security-patch`
3. **Commit prefixes**: `Add:` new feature · `Fix:` bugfix · `Update:` change existing code · `Remove:` deletion
   - e.g. `Add: User registration API endpoint`, `Fix: validation error in evaluation form`
4. **Pull Request** into `develop` with description (what changed, tests written, manual testing done, docs updated), reviewer approval required before merge
5. **After merge**: `git checkout develop && git pull origin develop && git branch -d feature/function-name`
