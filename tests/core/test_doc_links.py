"""Test that all file paths referenced in documentation actually exist."""

import re
from pathlib import Path


DOC_FILES = [Path("README.md"), Path("CONTRIBUTING.md")] + sorted(Path("docs").glob("*.md"))

# Pattern: markdown link targets that look like local file paths
# Matches [text](path) or [text](path "title") where path is a repo-relative file
MD_LINK_PATTERN = re.compile(r"""
    \[ [^\]]* \]                     # link text
    \(                               # opening paren
    \s*
    (                                # capture the URL/path
        (?:src/|tests/|docs/|parsers/|core/|integrations/|batch/|ui/|assets/)
        [A-Za-z0-9_./-]+
        \.(?:py|json|md|pdf|toml|spec|ico|png|yaml|txt|ini|cfg)
    )
    (?:\s+"[^"]*")?                  # optional title
    \s*
    \)
""", re.VERBOSE)


def extract_paths(text: str) -> list[str]:
    """Extract all documented file paths from markdown links."""
    matches = []
    for match in MD_LINK_PATTERN.finditer(text):
        path = match.group(1)
        path = path.replace("\\", "/")
        if "://" in path:
            continue
        matches.append(path)
    return matches


def test_documentation_paths_exist():
    """All file paths referenced in .md files must exist in the repo."""
    missing = {}
    for doc_path in DOC_FILES:
        if not doc_path.exists():
            continue
        text = doc_path.read_text(encoding="utf-8")
        for path_str in extract_paths(text):
            path = Path(path_str)
            if not path.exists():
                missing.setdefault(str(path), []).append(str(doc_path))

    if missing:
        lines = ["Broken documentation paths:"]
        for path, sources in sorted(missing.items()):
            lines.append(f"  {path} (referenced in: {', '.join(sorted(sources))})")
        raise AssertionError("\n".join(lines))


if __name__ == "__main__":
    test_documentation_paths_exist()
    print("All documentation paths exist.")