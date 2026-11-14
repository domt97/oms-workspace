---
name: docs-sync
description: Steps to bring the hand-written architecture docs back in line with the generated facts. Use on an architecture-drift PR from refresh-facts, or when the user asks to update the docs to match the code.
---
# Bring the docs back in line with the code

`architecture/generated/` is written by `scripts/extract_facts.py`; it wins over hand-written docs. Never edit it by hand.

1. Read the diff of `architecture/generated/*.md` (the `bot/refresh-facts` PR, or run the script after `sync-repos.sh`).
2. A "Contract check failed" or "No contract schema" note comes first: find out whether the code, the schema in
   `architecture/contracts/events/` or the script is wrong, and say which — do not paper over it in the docs.
3. For each changed endpoint, listener, event, table or migration, update the place that describes it:
   `integration.md` (endpoints and messages, *Front-end consumers*), `domain-map.md` (ownership, tables), the flow that
   uses it. Describe the present; no history. Do not copy the generated lists into prose — link to them.
4. Remove from `open-questions.md` what the change resolved. Add nothing that the user did not decide.
5. Work on a `docs/<slug>` branch of oms-workspace. This is review level 1: `docs-reviewer`, one round.
