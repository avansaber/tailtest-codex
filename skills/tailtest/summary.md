---
name: summary
description: Print a plain-text summary of this tailtest session and write it to .tailtest/reports/.
---

Show a summary of this tailtest session.

Read `.tailtest/session.json`. If the file does not exist or `generated_tests` is empty, say:
"No tests were generated this session."

Otherwise output a plain-text summary following the tailtest /summary format in AGENTS.md.

Also write the summary to the `report_path` stored in session.json (create `.tailtest/reports/` if it does not exist). If `report_path` is absent from session.json, skip writing.
