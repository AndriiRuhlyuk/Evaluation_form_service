#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Probe this repo's test environment before a single test line is written.

Black-box probe: it only reads state and never mutates the repo, so it is safe
to re-run at any point. Stdlib only, so it also runs as `python3 preflight.py`
when uv is not on PATH.

Checks:
  * compose services that are actually up (db, redis, celery)
  * Postgres reachability through the celery container
  * coverage.py availability inside that container
  * tests.py vs tests/ collision in the target app (Python resolves only one)
  * startapp stub files still holding "Create your tests here"
  * existing test count for the target app

JSON to stdout, human-readable log to stderr.
Exit code 0 means ready to write tests, 1 means a blocking problem was found,
2 means usage error.

Examples:
  uv run scripts/preflight.py --app question
  uv run scripts/preflight.py --app project --target project/views.py --format text
  python3 scripts/preflight.py --app topic --no-docker
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKIP_DIRS = {".venv", ".git", "node_modules", "staticfiles", "media", "__pycache__"}
STUB_MARKER = "Create your tests here"
REQUIRED_SERVICES = ("db", "celery")


@dataclass
class Check:
    name: str
    status: str  # ok | blocked | warn | skipped
    detail: str
    fix: str = ""


@dataclass
class Report:
    app: str | None
    target: str | None
    ready: bool = True
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)
        if check.status == "blocked":
            self.ready = False


def run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """Run a command, never raise. Returns (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def check_compose(report: Report, timeout: int) -> bool:
    """True when the compose stack looks usable for a test run."""
    code, out, err = run(
        ["docker-compose", "ps", "--services", "--filter", "status=running"], timeout
    )
    if code == 127:
        report.add(
            Check(
                "compose",
                "blocked",
                "docker-compose is not on PATH",
                "Install Docker Desktop, or pass --no-docker and set TEST_CMD "
                "to a command that reaches a live Postgres.",
            )
        )
        return False
    if code != 0:
        report.add(
            Check(
                "compose",
                "blocked",
                f"docker-compose ps failed: {err or 'unknown error'}",
                "Start Docker, then run: docker-compose up -d db redis celery",
            )
        )
        return False

    running = [line.strip() for line in out.splitlines() if line.strip()]
    missing = [svc for svc in REQUIRED_SERVICES if svc not in running]
    if missing:
        report.add(
            Check(
                "compose",
                "blocked",
                f"running: {running or 'none'}; missing: {missing}",
                f"docker-compose up -d {' '.join(missing)}",
            )
        )
        return False

    report.add(Check("compose", "ok", f"running: {running}"))
    return True


def check_database(report: Report, timeout: int) -> None:
    code, _, err = run(
        [
            "docker-compose",
            "exec",
            "-T",
            "celery",
            "python",
            "manage.py",
            "wait_for_db",
        ],
        timeout,
    )
    if code == 0:
        report.add(
            Check("database", "ok", "Postgres reachable from the celery container")
        )
        return
    hint = "wait_for_db never returned" if code == 124 else (err or "non-zero exit")
    report.add(
        Check(
            "database",
            "blocked",
            f"wait_for_db failed: {hint}",
            "Check POSTGRES_* in .env and that the db service is healthy "
            "(docker-compose logs db).",
        )
    )


def check_coverage(report: Report, timeout: int) -> None:
    code, _, _ = run(
        ["docker-compose", "exec", "-T", "celery", "python", "-c", "import coverage"],
        timeout,
    )
    if code == 0:
        report.add(Check("coverage", "ok", "coverage.py importable in the container"))
    else:
        report.add(
            Check(
                "coverage",
                "warn",
                "coverage.py is not installed - the coverage step will be skipped",
                "docker-compose exec celery pip install coverage "
                "(or add it to requirements.txt and rebuild).",
            )
        )


def iter_test_files(root: Path):
    for path in root.rglob("tests*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def check_layout(report: Report, root: Path, app: str | None) -> None:
    """tests.py next to tests/ is unresolvable for Python - one of them vanishes."""
    collisions = []
    for pkg in root.glob("*/tests/__init__.py"):
        sibling = pkg.parent.parent / "tests.py"
        if sibling.exists():
            collisions.append(str(sibling))
    if collisions:
        report.add(
            Check(
                "layout",
                "blocked",
                f"tests.py coexists with tests/ in: {collisions}",
                "Move the module's contents into the package and delete the "
                "stray tests.py before adding anything.",
            )
        )
    else:
        report.add(Check("layout", "ok", "no tests.py / tests/ collision"))

    if app:
        app_dir = root / app
        if not app_dir.is_dir():
            report.add(
                Check(
                    "app",
                    "blocked",
                    f"no such app directory: {app}",
                    "Pass an app name that exists at the repo root.",
                )
            )
            return
        pkg = app_dir / "tests"
        destination = (
            f"{app}/tests/tests_<topic>.py"
            if pkg.is_dir()
            else f"{app}/tests.py (append)"
        )
        report.add(Check("destination", "ok", destination))


def check_stubs(report: Report, root: Path) -> None:
    stubs = [
        str(path)
        for path in iter_test_files(root)
        if path.stat().st_size < 200 and STUB_MARKER in path.read_text(encoding="utf-8")
    ]
    if stubs:
        report.add(
            Check(
                "stubs",
                "warn",
                f"startapp stubs still present: {stubs}",
                "Offer to delete them in the same commit - an empty stub reads "
                "as 'this app has tests' to the next person.",
            )
        )
    else:
        report.add(Check("stubs", "ok", "no startapp stubs left"))


def count_tests(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    pattern = re.compile(r"^\s*def test_", re.MULTILINE)
    for path in iter_test_files(root):
        app = path.relative_to(root).parts[0]
        text = path.read_text(encoding="utf-8", errors="replace")
        counts[app] = counts.get(app, 0) + len(pattern.findall(text))
    return dict(sorted(counts.items(), key=lambda item: item[1]))


def check_target(report: Report, root: Path, target: str | None) -> None:
    if not target:
        return
    path = root / target
    if not path.is_file():
        report.add(
            Check(
                "target",
                "blocked",
                f"no such file: {target}",
                "Pass a path relative to the repo root, e.g. project/views.py.",
            )
        )
        return
    report.add(Check("target", "ok", f"{target} ({path.stat().st_size} bytes)"))


def render_text(report: Report, counts: dict[str, int]) -> str:
    symbols = {"ok": "ok  ", "warn": "warn", "blocked": "STOP", "skipped": "skip"}
    lines = [f"preflight: {'READY' if report.ready else 'BLOCKED'}"]
    for check in report.checks:
        lines.append(f"  [{symbols[check.status]}] {check.name}: {check.detail}")
        if check.fix and check.status != "ok":
            lines.append(f"           fix: {check.fix}")
    if counts:
        lines.append("  test counts per app:")
        for app, count in counts.items():
            flag = "  <- no tests" if count == 0 else ""
            lines.append(f"    {app:<20} {count}{flag}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preflight.py",
        description="Probe the test environment of this repo. Read-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit: 0 ready, 1 blocking problem, 2 usage error.

Examples:
  preflight.py --app question --target question/views.py --format text
  preflight.py --app project --no-docker""",
    )
    parser.add_argument("--app", help="app to be covered, e.g. question")
    parser.add_argument("--target", help="module under test, e.g. project/views.py")
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    parser.add_argument(
        "--format", choices=("json", "text"), default="json", help="default: json"
    )
    parser.add_argument(
        "--no-docker", action="store_true", help="skip every container probe"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the probes that would run, execute none",
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="per-command timeout in seconds"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"--root is not a directory: {args.root}", file=sys.stderr)
        return 2

    if args.dry_run:
        planned = ["layout", "stubs", "test counts"]
        if not args.no_docker:
            planned = ["compose", "database", "coverage"] + planned
        if args.target:
            planned.append("target")
        print(json.dumps({"dry_run": True, "would_check": planned}, indent=2))
        return 0

    report = Report(app=args.app, target=args.target)

    if args.no_docker:
        report.add(Check("compose", "skipped", "--no-docker was passed"))
    elif check_compose(report, args.timeout):
        check_database(report, args.timeout)
        check_coverage(report, args.timeout)

    check_layout(report, root, args.app)
    check_stubs(report, root)
    check_target(report, root, args.target)

    counts = count_tests(root)
    payload = asdict(report) | {"test_counts": counts}

    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(report, counts))

    # One-line verdict on stderr so a caller piping stdout into a parser still
    # sees what happened.
    blocked = [check.name for check in report.checks if check.status == "blocked"]
    warned = [check.name for check in report.checks if check.status == "warn"]
    print(
        f"preflight: {'ready' if report.ready else 'blocked'}"
        f"{'; blocking: ' + ', '.join(blocked) if blocked else ''}"
        f"{'; warnings: ' + ', '.join(warned) if warned else ''}",
        file=sys.stderr,
    )

    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
