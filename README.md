# oms-workspace

Cross-repo knowledge base and Claude Code workspace for the OMS.

```bash
git clone git@github.com:domt97/oms-workspace.git
cd oms-workspace
./scripts/sync-repos.sh     # clone/update every repo over SSH (GIT_PROTOCOL=https for HTTPS); finished branches go back to develop/master
claude                      # start Claude Code here
```

- `CLAUDE.md` — system map Claude reads first
- `architecture/` — vision & context map, business rules, domain map, integration catalog, flows, ADRs, contracts, open questions
- `.claude/agents/` — `oms-architect`, one expert per context, `plan-reviewer` (independent critic)
- `.claude/skills/sa-*/` — solution-architect knowledge preloaded into the agents (analysis checklist, DDD, messaging, data, concurrency, performance/scale, API design, multi-tenancy/security, resilience/observability, testing, AWS platform)
- `.claude/skills/feature-impact/` — `/feature-impact <feature>` for a standard cross-service analysis
- `.claude/skills/ship/` — `/ship <service> <feature|fix> <slug>` to implement a change and open a PR into `develop`
- `architecture/generated/` — facts extracted from code by `scripts/extract_facts.py` (refreshed daily by `.github/workflows/refresh-facts.yml`)
- `repos.txt` — list of repos to sync; add new services here
