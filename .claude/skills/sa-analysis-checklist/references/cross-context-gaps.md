# A gap in a bounded context this work does not change

Part of `sa-analysis-checklist` §1, kept here because it applies to few changes.

- [ ] A gap that sits in **another bounded context that this piece of work does not design or change** (e.g. an
      inventory PR that finds a gap in order-service's saga) is recorded as an open question (`open-questions.md`,
      business half in `business-rules.md` *Open business questions*) together with **what this context guarantees**
      for every choice the other side may make. Do not write a new rule or obligation for that context into an ADR or
      flow as decided unless the user decided it (cite the date) — cross-context designs done with `/feature-impact`
      or `oms-architect` decide such obligations with the user, as ADR 0006 did. If an existing rule or obligation is
      called into question, propose in the plan a note on that item — "Under review (YYYY-MM-DD, open question N)" —
      leaving the ADR status and any BR status unchanged (for a BR, append the note to the status column, after the
      existing status, and cite the business question id too: "Under review (YYYY-MM-DD, open question N, Qn)" —
      open-questions numbers and business Q-ids are different series); apply it only once the user approves the plan. Remove the note when open question N is
      resolved: the ADR or BR is then updated, or superseded by a new ADR, with the user's decision.
