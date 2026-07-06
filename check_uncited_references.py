#!/usr/bin/env python3
"""
Check whether every entry in references.bib is cited in LaTeX source files.

By default, this script ignores ``\\nocite{*}`` because it only forces all
bibliography entries to appear; it does not mean those entries are cited in
the manuscript text.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


BIB_ENTRY_RE = re.compile(
    r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,",
    re.MULTILINE,
)

CITE_COMMAND_RE = re.compile(
    r"""
    \\(?P<command>
        citation|nocite|
        cite|cites|Cite|Cites|
        citep|citet|citealp|citealt|citeauthor|citeyear|citeyearpar|
        parencite|textcite|autocite|footcite|supercite|onlinecite
    )
    \s*
    (?:\[[^\[\]]*\]\s*)*
    \{(?P<keys>[^{}]+)\}
    """,
    re.VERBOSE,
)


def strip_latex_comments(text: str) -> str:
    """Remove unescaped LaTeX comments while keeping escaped percent signs."""
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        for index, char in enumerate(line):
            if char != "%":
                continue

            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1

            if backslashes % 2 == 0:
                line = line[:index]
                break

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def read_bib_keys(bib_path: Path) -> list[str]:
    text = bib_path.read_text(encoding="utf-8-sig")
    keys = [match.group(1).strip() for match in BIB_ENTRY_RE.finditer(text)]
    return list(dict.fromkeys(keys))


def split_citation_keys(raw_keys: str) -> list[str]:
    return [key.strip() for key in raw_keys.replace("\n", " ").split(",") if key.strip()]


def read_citation_keys(
    tex_paths: list[Path],
    *,
    include_nocite: bool,
    include_nocite_star: bool,
) -> tuple[set[str], bool]:
    cited_keys: set[str] = set()
    saw_nocite_star = False

    for tex_path in tex_paths:
        text = strip_latex_comments(tex_path.read_text(encoding="utf-8-sig"))
        for match in CITE_COMMAND_RE.finditer(text):
            command = match.group("command").lower()
            keys = split_citation_keys(match.group("keys"))

            if command == "nocite":
                if "*" in keys:
                    saw_nocite_star = True
                    if not include_nocite_star:
                        keys = [key for key in keys if key != "*"]
                if not include_nocite:
                    continue

            cited_keys.update(key for key in keys if key != "*")

    return cited_keys, saw_nocite_star


def resolve_tex_paths(tex_args: list[str], base_dir: Path) -> list[Path]:
    if tex_args:
        paths: list[Path] = []
        for item in tex_args:
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = base_dir / candidate
            paths.append(candidate)
    else:
        paths = sorted(base_dir.glob("*.tex"))

    missing = [path for path in paths if not path.is_file()]
    if missing:
        missing_text = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Cannot find TeX file(s):\n{missing_text}")

    if not paths:
        raise FileNotFoundError(f"No .tex files found in {base_dir}")

    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare citation keys in .tex files with entries in references.bib.",
    )
    parser.add_argument(
        "--bib",
        default="references.bib",
        help="Path to the .bib file. Default: references.bib",
    )
    parser.add_argument(
        "--tex",
        action="append",
        default=[],
        help="TeX file to check. Can be used more than once. Default: all *.tex files in this folder.",
    )
    parser.add_argument(
        "--include-nocite",
        action="store_true",
        help="Treat explicit \\nocite{key} commands as cited.",
    )
    parser.add_argument(
        "--include-nocite-star",
        action="store_true",
        help="Treat \\nocite{*} as meaning every bib entry is cited.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only uncited bib keys.",
    )
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Return exit code 1 when uncited or missing bib keys are found.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_dir = Path(__file__).resolve().parent

    bib_path = Path(args.bib)
    if not bib_path.is_absolute():
        bib_path = base_dir / bib_path
    if not bib_path.is_file():
        raise FileNotFoundError(f"Cannot find bib file: {bib_path}")

    tex_paths = resolve_tex_paths(args.tex, base_dir)
    bib_keys = read_bib_keys(bib_path)
    cited_keys, saw_nocite_star = read_citation_keys(
        tex_paths,
        include_nocite=args.include_nocite,
        include_nocite_star=args.include_nocite_star,
    )

    if saw_nocite_star and args.include_nocite_star:
        cited_keys.update(bib_keys)

    bib_key_set = set(bib_keys)
    uncited_keys = [key for key in bib_keys if key not in cited_keys]
    cited_without_bib = sorted(cited_keys - bib_key_set)

    if args.quiet:
        for key in uncited_keys:
            print(key)
    else:
        print(f"Bib file: {bib_path}")
        print("TeX files:")
        for tex_path in tex_paths:
            print(f"  - {tex_path}")
        print(f"\nBib entries: {len(bib_keys)}")
        print(f"Cited keys found: {len(cited_keys)}")

        if saw_nocite_star and not args.include_nocite_star:
            print("Note: found \\nocite{*}, but ignored it for text-citation checking.")

        print(f"\nUncited bib entries ({len(uncited_keys)}):")
        if uncited_keys:
            for key in uncited_keys:
                print(f"  - {key}")
        else:
            print("  None")

        if cited_without_bib:
            print(f"\nCited keys missing from bib ({len(cited_without_bib)}):")
            for key in cited_without_bib:
                print(f"  - {key}")

    has_issues = bool(uncited_keys or cited_without_bib)
    return 1 if args.fail_on_issues and has_issues else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
