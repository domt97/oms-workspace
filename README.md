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
- `architecture/generated/` — facts extracted from code by `scripts/extract_facts.py` (services: endpoints, listeners, events, tables; oms-web: backend calls checked against the endpoints; oms-core: public types; development: what the local stack defines) (refreshed daily by `.github/workflows/refresh-facts.yml`)
- `.claude/hooks/guard_git.py` — hook that blocks the git/gh commands `CLAUDE.md` forbids (push to `master`/`develop`, force push, tags, …), registered in `.claude/settings.json`. It needs `python3`: without it, or if the hook times out, the command falls through to the `ask`/`deny` rules
- `scripts/tests/` — unit tests of the extractor and the hook: `python3 -m unittest discover -s scripts/tests` (CI: `.github/workflows/scripts-test.yml`)
- `repos.txt` — list of repos to sync (services, `oms-core`, `development`, `oms-web`); add new services here
