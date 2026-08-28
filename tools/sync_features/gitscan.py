import re
import subprocess
from datetime import datetime

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


def validate_iso_date(iso_date: str) -> None:
    """Перевірити, що дата у форматі YYYY-MM-DD. Піднімає ValueError якщо ні.

    Гарантує, що typo у дату Features_list.json не залишиться мовчазним
    (git silently падає назад на умовчасну парсинг, не повідомляючи про помилку).
    """
    if not iso_date or not iso_date.strip():
        raise ValueError("ISO date cannot be empty")
    # Перевірити точний формат YYYY-MM-DD (з нулями попереду)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date):
        raise ValueError(f"Invalid ISO date format: '{iso_date}'. Expected YYYY-MM-DD.")
    # Перевірити, що дата валідна календарна дата
    try:
        datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid ISO date format: '{iso_date}'. Expected YYYY-MM-DD.")


def _process_git_result(
    returncode: int, stdout: str, stderr: str
) -> list[tuple[str, str]]:
    """Обробити результат git log. Піднімає RuntimeError якщо повернувся код помилки.

    Розділяє I/O (commits_since) від логіки, щоб можна було тестувати помилки
    без підміни subprocess.
    """
    if returncode != 0:
        raise RuntimeError(f"git log failed with code {returncode}: {stderr}")
    return parse_log(stdout)


def commits_since(iso_date: str) -> list[tuple[str, str]]:
    """Коміти після вказаної дати. Викликає git.

    Піднімає ValueError для невалідного формату дати, RuntimeError для git помилок.
    """
    validate_iso_date(iso_date)
    result = subprocess.run(
        ["git", "log", f"--since={iso_date}", "--oneline", "--no-merges"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return _process_git_result(result.returncode, result.stdout, result.stderr)


def coverage_line(commits: list[tuple[str, str]], ids_in_answer: set[str]) -> str:
    """Рядок звіту про покриття. Вимірює, а не вимагає 1:1 (спец, розділ 4)."""
    with_ids = sum(1 for _, subject in commits if extract_ids(subject))
    return (
        f"{len(commits)} commits in range, {with_ids} reference a feature id, "
        f"{len(commits) - with_ids} do not; "
        f"agent answer mentions {len(ids_in_answer)} ids"
    )
