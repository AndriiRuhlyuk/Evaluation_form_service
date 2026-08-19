#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Find and apply source mutations through the syntax tree (AST).

Why AST instead of pattern matching on lines: `return (` opens an expression
that spans several lines. Replacing only the first line leaves the tail without
its head, the file stops being valid Python, the suite dies on SyntaxError -
and the mutation looks "caught" while nothing was actually verified.

The tree gives exact node boundaries (lineno..end_lineno), so the whole node is
replaced. The tree is used for LOCATING only; the replacement itself is textual,
so comments, indentation and formatting of the rest of the file survive - unlike
ast.unparse(), which would rewrite the entire file.

Two mutation kinds:
  return   `return <expr>`  ->  `return None`   (whole node replaced)
  compare  `a == b`         ->  `not (a == b)`  (single-line comparisons only,
           because the replacement works on column offsets)

Stdlib only, so `python3 mutate.py` works even without uv.
JSON or TSV to stdout, diagnostics to stderr.
Exit: 0 success, 2 usage error.

Examples:
  uv run scripts/mutate.py list question/views.py
  python3 scripts/mutate.py list question/views.py --format tsv
  python3 scripts/mutate.py apply question/views.py 3 --dry-run
"""

from __future__ import annotations

import argparse
import ast
import json
import sys

MUTATION_MARK = "  # mutation"


def _label(source_lines: list[str], node: ast.AST) -> str:
    """Short source excerpt for the report."""
    return source_lines[node.lineno - 1].strip()[:60]


def collect(path: str, kinds: set[str]) -> list[dict]:
    """Mutation candidates, ordered by position in the file."""
    source = open(path, encoding="utf-8").read()
    source_lines = source.splitlines()
    tree = ast.parse(source)

    items: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            if "return" not in kinds:
                continue
            # mutating `return None` is pointless - it is already None
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                continue
            # The whole node is replaced by one line, so a return that shares
            # its first line with something else (`def a(): return 1`) would
            # take that something else with it and delete the def header.
            if not source_lines[node.lineno - 1].lstrip().startswith("return"):
                continue
            items.append(
                {
                    "kind": "return",
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "label": _label(source_lines, node),
                }
            )
        elif isinstance(node, ast.Compare) and node.lineno == node.end_lineno:
            if "compare" not in kinds:
                continue
            # multi-line comparisons are skipped: the replacement is column
            # based, and columns only make sense within a single line
            items.append(
                {
                    "kind": "compare",
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "col": node.col_offset,
                    "end_col": node.end_col_offset,
                    "label": _label(source_lines, node),
                }
            )

    items.sort(key=lambda item: (item["lineno"], item.get("col", 0)))
    for index, item in enumerate(items):
        item["index"] = index
    return items


def mutated_lines(path: str, item: dict) -> list[str]:
    """The file content after the mutation, without touching disk."""
    lines = open(path, encoding="utf-8").readlines()

    if item["kind"] == "return":
        first = lines[item["lineno"] - 1]
        indent = first[: len(first) - len(first.lstrip())]
        # the whole node, first line through last, collapses into one line
        lines[item["lineno"] - 1 : item["end_lineno"]] = [
            f"{indent}return None{MUTATION_MARK}\n"
        ]
    else:  # compare
        # ast reports col_offset in UTF-8 BYTES, not characters. Slicing the
        # line as str drifts by one position per non-ASCII byte, and comments
        # in this repo are routinely Ukrainian - the replacement would land in
        # the middle of the expression and corrupt the file. Slice bytes.
        raw = lines[item["lineno"] - 1].encode("utf-8")
        original = raw[item["col"] : item["end_col"]].decode("utf-8")
        patched = (
            raw[: item["col"]]
            + f"not ({original})".encode("utf-8")
            + raw[item["end_col"] :]
        )
        # Deliberately NO marker comment here, unlike the return branch. A
        # comparison can live inside a triple-quoted string, where appending
        # `# mutation` becomes part of the string VALUE: a test asserting on
        # that text then fails because of the comment rather than because the
        # comparison flipped, and the run scores a false "caught". The
        # double-apply guard is worth less than that correctness.
        lines[item["lineno"] - 1] = patched.decode("utf-8")

    return lines


def cmd_list(args: argparse.Namespace) -> int:
    items = collect(args.file, set(args.kinds))
    if args.format == "json":
        print(json.dumps({"file": args.file, "candidates": items}, indent=2))
    else:
        for item in items:
            print(f"{item['index']}|{item['kind']}|{item['lineno']}|{item['label']}")
    print(f"{len(items)} candidate(s) in {args.file}", file=sys.stderr)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    items = collect(args.file, set(args.kinds))
    if not 0 <= args.index < len(items):
        print(
            f"no mutation with index {args.index}: {args.file} has "
            f"{len(items)} candidate(s), valid range is 0..{max(len(items) - 1, 0)}",
            file=sys.stderr,
        )
        return 2

    item = items[args.index]

    # Applying to an already-mutated file compounds the damage, because indices
    # are recomputed against the mutated source. Refuse rather than corrupt.
    # Only return mutations leave a marker, so this guard is blind to a repeated
    # compare mutation - `not (not (a == b))` is a semantic no-op that nothing
    # here detects. Restoring the file between applications is the real defence.
    if not args.dry_run and not args.force and item["kind"] == "return":
        if MUTATION_MARK.strip() in open(args.file, encoding="utf-8").read():
            print(
                f"{args.file} already contains a mutation marker "
                f"('{MUTATION_MARK.strip()}'). Restore the file first, or pass "
                f"--force if you know the marker is part of the original source.",
                file=sys.stderr,
            )
            return 2

    lines = mutated_lines(args.file, item)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "applied": False,
                    "mutation": item,
                    "new_line": lines[item["lineno"] - 1].rstrip("\n"),
                },
                indent=2,
            )
        )
        return 0

    open(args.file, "w", encoding="utf-8").writelines(lines)
    print(json.dumps({"applied": True, "mutation": item}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mutate.py",
        description="Locate and apply AST-based mutations in one Python file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
subcommand flags:
  list  <file> [--format json|tsv] [--kinds return compare]
  apply <file> <index> [--dry-run] [--force] [--kinds return compare]

`apply` REWRITES the file in place and takes no backup - verify-tests.sh is the
caller that keeps one. Run it directly with --dry-run unless you are prepared to
restore the file yourself. The double-apply guard covers return mutations only;
comparisons leave no marker, so applying one twice silently yields a no-op.

Exit: 0 success, 2 usage error (bad index, unreadable or unwritable file,
      already mutated).

Examples:
  mutate.py list question/views.py --format tsv
  mutate.py apply question/views.py 3 --dry-run""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_kinds(target: argparse.ArgumentParser) -> None:
        # Declared per subcommand rather than globally: `list` and `apply` must
        # be given the same value, because indices are positions within the
        # filtered candidate list.
        target.add_argument(
            "--kinds",
            nargs="+",
            choices=("return", "compare"),
            default=["return", "compare"],
            help="mutation kinds to consider (default: both)",
        )

    listing = sub.add_parser("list", help="list mutation candidates")
    listing.add_argument("file")
    listing.add_argument(
        "--format", choices=("json", "tsv"), default="json", help="default: json"
    )
    add_kinds(listing)
    listing.set_defaults(func=cmd_list)

    applying = sub.add_parser("apply", help="apply one mutation in place")
    applying.add_argument("file")
    applying.add_argument("index", type=int)
    applying.add_argument(
        "--dry-run", action="store_true", help="show the change, write nothing"
    )
    applying.add_argument(
        "--force",
        action="store_true",
        help="apply even if the file already carries a mutation marker",
    )
    add_kinds(applying)
    applying.set_defaults(func=cmd_apply)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except SyntaxError as error:
        print(f"{args.file} is not valid Python: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"no such file: {args.file}", file=sys.stderr)
        return 2
    except OSError as error:
        # A traceback here would break the documented 0/2 contract and leave the
        # caller reading a nonzero code it has no rule for.
        print(f"cannot read or write {args.file}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
