import unittest

from gitscan import coverage_line, extract_ids, parse_log


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
