import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gitscan import (
    _process_git_result,
    commits_since,
    coverage_line,
    extract_ids,
    parse_log,
    validate_iso_date,
)


class TestValidateIsoDate(unittest.TestCase):
    def test_valid_iso_date(self):
        # Should not raise for valid YYYY-MM-DD dates.
        validate_iso_date("2026-08-28")
        validate_iso_date("2000-01-01")
        validate_iso_date("2099-12-31")

    def test_invalid_format_short_year(self):
        # Year must be 4 digits.
        with self.assertRaises(ValueError):
            validate_iso_date("26-08-28")

    def test_invalid_format_two_digit_month(self):
        # Month must be 2 digits with leading zero.
        with self.assertRaises(ValueError):
            validate_iso_date("2026-8-28")

    def test_invalid_format_two_digit_day(self):
        # Day must be 2 digits with leading zero.
        with self.assertRaises(ValueError):
            validate_iso_date("2026-08-8")

    def test_invalid_format_wrong_separators(self):
        # Must use hyphen separators.
        with self.assertRaises(ValueError):
            validate_iso_date("2026/08/28")

    def test_invalid_format_no_separators(self):
        # Must have separators.
        with self.assertRaises(ValueError):
            validate_iso_date("20260828")

    def test_invalid_month_value(self):
        # Month must be 01-12.
        with self.assertRaises(ValueError):
            validate_iso_date("2026-13-28")

    def test_invalid_day_value(self):
        # Day must be valid for the month.
        with self.assertRaises(ValueError):
            validate_iso_date("2026-02-30")

    def test_empty_string(self):
        # Empty string is invalid.
        with self.assertRaises(ValueError):
            validate_iso_date("")

    def test_whitespace_only(self):
        # Whitespace is invalid.
        with self.assertRaises(ValueError):
            validate_iso_date("   ")


class TestProcessGitResult(unittest.TestCase):
    def test_success_with_commits(self):
        # Successful git run returns parsed commits.
        stdout = "7a8598f Docs: щось\nb0086cf Fix: ARCH-5\n"
        result = _process_git_result(0, stdout, "")
        self.assertEqual(
            result, [("7a8598f", "Docs: щось"), ("b0086cf", "Fix: ARCH-5")]
        )

    def test_success_no_commits(self):
        # Successful git run with no commits returns empty list.
        result = _process_git_result(0, "", "")
        self.assertEqual(result, [])

    def test_git_error_with_stderr(self):
        # Non-zero exit code raises RuntimeError with stderr text.
        stderr = "fatal: not a git repository (or any of the parent directories): .git"
        with self.assertRaises(RuntimeError) as context:
            _process_git_result(128, "", stderr)
        self.assertIn(stderr, str(context.exception))

    def test_git_error_no_stderr(self):
        # Non-zero exit code raises RuntimeError even if stderr is empty.
        with self.assertRaises(RuntimeError):
            _process_git_result(1, "", "")


class TestExtractIds(unittest.TestCase):
    def test_single_id(self):
        self.assertEqual(extract_ids("Fix: ARCH-5 полагоджено"), {"ARCH-5"})

    def test_several_ids(self):
        text = "Docs: ARCH-20, CFG-1 і CFG-2"
        self.assertEqual(extract_ids(text), {"ARCH-20", "CFG-1", "CFG-2"})

    def test_no_ids(self):
        self.assertEqual(extract_ids("Update: дрібні правки"), set())

    def test_unknown_series_ignored(self):
        self.assertEqual(extract_ids("Fix: ZZZ-1"), set())

    def test_range_notation_takes_first_only(self):
        # відома межа: "ARCH-24..26" дає лише ARCH-24.
        # Діапазони не розгортаються навмисно - це здогад, а не факт.
        self.assertEqual(extract_ids("ARCH-24..26"), {"ARCH-24"})

    def test_lowercase_not_matched(self):
        self.assertEqual(extract_ids("fix: arch-5"), set())


class TestParseLog(unittest.TestCase):
    def test_two_lines(self):
        raw = "7a8598f Docs: щось\nb0086cf Fix: ARCH-5\n"
        self.assertEqual(
            parse_log(raw),
            [("7a8598f", "Docs: щось"), ("b0086cf", "Fix: ARCH-5")],
        )

    def test_empty_input(self):
        self.assertEqual(parse_log(""), [])

    def test_blank_lines_skipped(self):
        self.assertEqual(parse_log("\n\n7a8598f Subject\n\n"), [("7a8598f", "Subject")])

    def test_subject_without_space(self):
        self.assertEqual(parse_log("7a8598f"), [("7a8598f", "")])


def _make_repo(path, subject):
    """Мінімальний git-репозиторій з одним комітом і заданою темою."""
    path.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.com",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.com",
    }
    (path / "f.txt").write_text("x", encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["add", "f.txt"],
        ["commit", "-q", "-m", subject],
    ):
        subprocess.run(
            ["git", *args], cwd=path, env=env, check=True, capture_output=True
        )


class TestCommitsSinceIsAnchored(unittest.TestCase):
    """Important 5 (фінальний раунд ревʼю): `commits_since` була останнім
    непривʼязаним підпроцесом у інструменті.

    `git log` запускався БЕЗ `cwd`, тобто в робочій директорії процесу, тоді
    як усе інше в інструменті виводиться з `guard.REPO_ROOT`. Запуск ззовні
    репозиторію читав ЧУЖУ історію і віддавав ті теми комітів агентові, який
    потім правив ЦЕЙ реєстр: неправильний вхід, жодної помилки, і I4
    задоволений проти не того набору комітів.
    """

    def test_reads_the_repo_given_by_cwd_not_the_process_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            other = Path(tmp) / "other"
            _make_repo(target, "Fix: ARCH-777 цільовий репозиторій")
            _make_repo(other, "Fix: CFG-999 сторонній репозиторій")

            previous = os.getcwd()
            os.chdir(other)
            try:
                commits = commits_since("2000-01-01", target)
            finally:
                os.chdir(previous)

        subjects = [subject for _, subject in commits]
        self.assertEqual(subjects, ["Fix: ARCH-777 цільовий репозиторій"])

    def test_cwd_is_required_no_silent_default(self):
        # Умовчання тут було б місцем, де хибне значення проходить мовчки -
        # рівно той дефект, який фіксується. Обовʼязковий аргумент робить
        # привʼязку видимою в єдиному місці виклику.
        with self.assertRaises(TypeError):
            commits_since("2000-01-01")


class TestCoverageLine(unittest.TestCase):
    def test_counts(self):
        commits = [
            ("a1", "Fix: ARCH-5"),
            ("a2", "Update: без id"),
            ("a3", "Docs: CFG-1 і CFG-2"),
        ]
        line = coverage_line(commits, {"ARCH-5", "CFG-1", "CFG-2"})
        self.assertIn("3 commits in range", line)
        self.assertIn("2 reference a feature id", line)
        self.assertIn("1 do not", line)


if __name__ == "__main__":
    unittest.main()
