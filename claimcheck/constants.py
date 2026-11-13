"""Version and milestone markers shared by the CLI and reports."""

__version__ = "0.2.0"
MILESTONE = "2"

SCAN_MODE = "milestone-2"
SCAN_LIMITATIONS = (
    "The symbol index is a Python AST walk. Other files use a def/class/function/fn line pattern.",
    "Text search is lexical. not_found means that search returned no line.",
    "Numbers are compared to JSON, CSV, and log metrics that share a word with the claim.",
    "contradicted is kept only when the cited line is counter-evidence and a second pass confirms.",
    "Otherwise that label becomes unverifiable.",
    "A git URL is cloned into a temporary directory and removed after the report is written.",
)
