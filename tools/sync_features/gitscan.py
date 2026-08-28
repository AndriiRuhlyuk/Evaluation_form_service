import re
import subprocess

_SERIES = "AUTH|CORE|TPL|WF|EVAL|FORM|INT|OPS|BUG|TD|QA|AI|LD|FN|ARCH|CFG|FE"
ID_PATTERN = re.compile(rf"\b({_SERIES})-\d+\b")


def extract_ids(text: str) -> set[str]:
    """Усі id фіч, згадані в тексті. Діапазони не розгортаються."""
    return {match.group(0) for match in ID_PATTERN.finditer(text)}


def parse_log(raw: str) -> list[tuple[str, str]]:
    """Розібрати вивід `git log --oneline` у пари (sha, subject)."""
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        out.append((sha, subject))
    return out


def commits_since(iso_date: str) -> list[tuple[str, str]]:
    """Коміти після вказаної дати. Викликає git, тому без юніт-тестів."""
    result = subprocess.run(
        ["git", "log", f"--since={iso_date}", "--oneline", "--no-merges"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return parse_log(result.stdout)


def coverage_line(commits: list[tuple[str, str]], ids_in_answer: set[str]) -> str:
    """Рядок звіту про покриття. Вимірює, а не вимагає 1:1 (спец, розділ 4)."""
    with_ids = sum(1 for _, subject in commits if extract_ids(subject))
    return (
        f"{len(commits)} commits in range, {with_ids} reference a feature id, "
        f"{len(commits) - with_ids} do not; "
        f"agent answer mentions {len(ids_in_answer)} ids"
    )
