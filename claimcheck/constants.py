"""Version and milestone markers shared by the CLI and reports."""

__version__ = "0.1.0"
MILESTONE = "1"

# Scan in this milestone extracts claims and then stops. The label is a
# placeholder so a report is never mistaken for a finding.
STUB_MODE = "milestone-1-stub"
STUB_RATIONALE = (
    "Milestone 1 does not look at code, benchmark scripts, or benchmark results. "
    "This unverifiable label is a placeholder, not a judgment about the claim."
)
STUB_LIMITATIONS = (
    "Milestone 1 extracts claims only.",
    "Evidence retrieval is not implemented, so no file or line is cited as "
    "supporting or contradicting evidence.",
    "Every verdict is unverifiable on purpose. Do not read these labels as findings.",
)
