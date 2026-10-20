# oms-workspace

Cross-repo knowledge base and Claude Code workspace for the OMS.

```bash
git clone https://github.com/domt97/oms-workspace.git
cd oms-workspace
./scripts/sync-repos.sh     # clones every service into repos/
claude                      # start Claude Code here
```

- `CLAUDE.md` — system map Claude reads first
- `architecture/` — domain map, integration catalog, flows, ADRs, contracts, open questions
- `.claude/agents/` — `oms-architect` + one expert per context
- `.claude/skills/feature-impact/` — `/feature-impact <feature>` for a standard cross-service analysis
- `.claude/skills/ship/` — `/ship <service> <feature|fix> <slug>` to implement a change and open a PR into `develop`
- `architecture/generated/` — facts extracted from code by `scripts/extract_facts.py` (refreshed daily by `.github/workflows/refresh-facts.yml`)
- `repos.txt` — list of repos to sync; add new services here
