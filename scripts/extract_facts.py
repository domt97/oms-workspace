#!/usr/bin/env python3
"""Extract architecture facts from the service repos in ./repos.

Deterministic, no AI: reads Java sources and Flyway migrations and writes
architecture/generated/<service>.md plus architecture/generated/facts.json.
These files are the ground truth the hand-written docs (domain-map.md,
integration.md, flows/) are compared against.

Usage: python3 scripts/extract_facts.py [--repos DIR] [--out DIR]
Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

HTTP_ANN = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
}
ANN_ARGS = r"(?:\((?P<args>(?:[^()]|\([^()]*\))*)\))?"
MAPPING_RE = re.compile(r"@(?P<ann>RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)" + ANN_ARGS)
METHOD_NAME_RE = re.compile(r"(?:public|protected|private)?\s*[\w<>\[\],\s?]+\s+(\w+)\s*\(")
STRING_RE = re.compile(r'"([^"]*)"')


def strip_comments(src: str) -> tuple[str, str]:
    """Return (code without comments, removed line-comment text)."""
    removed = []

    def keep_strings(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("/"):
            removed.append(s)
            return "\n" * s.count("\n")
        return s

    code = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', keep_strings, src, flags=re.S)
    return code, "\n".join(removed)


def first_path(args: str | None) -> str:
    if not args:
        return ""
    m = re.search(r'(?:value|path)\s*=\s*\{?\s*"([^"]*)"', args)
    if m:
        return m.group(1)
    m = re.match(r'\s*\{?\s*"([^"]*)"', args)
    return m.group(1) if m else ""


def join_path(a: str, b: str) -> str:
    p = "/" + "/".join(x.strip("/") for x in (a, b) if x and x.strip("/"))
    return p if p != "/" else "/"


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def extract_rest(java: Path, root: Path, code: str) -> list[dict]:
    if not re.search(r"@(Rest)?Controller\b", code):
        return []
    cls = re.search(r"\bclass\s+(\w+)", code)
    if not cls:
        return []
    header = code[: cls.start()]
    base = ""
    for m in MAPPING_RE.finditer(header):
        if m.group("ann") == "RequestMapping":
            base = first_path(m.group("args"))
    hidden = "@Hidden" in header
    out = []
    body = code[cls.end():]
    for m in MAPPING_RE.finditer(body):
        ann = m.group("ann")
        if ann == "RequestMapping":
            meth = re.search(r"RequestMethod\.(\w+)", m.group("args") or "")
            verb = meth.group(1) if meth else "ANY"
        else:
            verb = HTTP_ANN[ann]
        name = METHOD_NAME_RE.search(body, m.end())
        out.append({
            "method": verb,
            "path": join_path(base, first_path(m.group("args"))),
            "handler": f"{cls.group(1)}#{name.group(1) if name else '?'}",
            "visibility": "internal" if base.startswith("/internal") or hidden else "public",
            "hidden": hidden,
            "file": rel(java, root),
        })
    return out


def ann_attr(args: str, key: str) -> list[str]:
    m = re.search(key + r'\s*=\s*(\{[^}]*\}|"[^"]*")', args)
    return STRING_RE.findall(m.group(1)) if m else []


def extract_listeners(java: Path, root: Path, code: str, comments: str) -> list[dict]:
    out = []
    cls = re.search(r"\bclass\s+(\w+)", code)
    cname = cls.group(1) if cls else java.stem
    for text, active in ((code, True), (comments, False)):
        for m in re.finditer(r"@KafkaListener\s*\((?P<args>[^)]*)\)", re.sub(r"//\s*", "", text) if not active else text, re.S):
            args = m.group("args")
            out.append({
                "transport": "kafka", "class": cname, "active": active,
                "topics": ann_attr(args, "topics"), "group": (ann_attr(args, "groupId") or [""])[0],
                "file": rel(java, root),
            })
        for m in re.finditer(r'@SqsListener\s*\(\s*(?:value\s*=\s*)?"([^"]*)"', text):
            out.append({
                "transport": "sqs", "class": cname, "active": active,
                "topics": [m.group(1)], "group": "", "file": rel(java, root),
            })
    return out


def extract_published(java: Path, root: Path, code: str) -> list[dict]:
    if "OutboxEvent" not in code:
        return []
    return [{"event": e, "file": rel(java, root)}
            for e in sorted(set(re.findall(r'\.eventType\(\s*"([^"]+)"\s*\)', code)))]


def extract_migrations(svc: Path) -> dict:
    mig_dir = svc / "src/main/resources/db/migration"
    if not mig_dir.is_dir():
        return {"latest": None, "tables": []}
    files = sorted(mig_dir.glob("V*__*.sql"),
                   key=lambda p: [int(x) for x in re.findall(r"\d+", p.name.split("__")[0])])
    tables: dict[str, str] = {}
    for f in files:
        sql = re.sub(r"--[^\n]*", "", f.read_text(encoding="utf-8", errors="replace"))
        for t in re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)", sql, re.I):
            tables[t.split(".")[-1].lower()] = f.name
        for t in re.findall(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.]+)", sql, re.I):
            tables.pop(t.split(".")[-1].lower(), None)
    return {"latest": files[-1].name if files else None,
            "tables": [{"table": t, "created_in": v} for t, v in sorted(tables.items())]}


def type_names(svc: Path, pattern: str, suffix: str = "") -> list[str]:
    names = set()
    for p in svc.glob(pattern):
        if p.suffix == ".java" and (not suffix or p.stem.endswith(suffix)):
            names.add(p.stem)
    return sorted(names)


def extract_service(svc: Path, root: Path) -> dict:
    main = svc / "src/main/java"
    rest, listeners, published = [], [], []
    for java in sorted(main.rglob("*.java")):
        src = java.read_text(encoding="utf-8", errors="replace")
        code, comments = strip_comments(src)
        rest += extract_rest(java, root, code)
        listeners += extract_listeners(java, root, code, comments)
        published += extract_published(java, root, code)
    rest.sort(key=lambda r: (r["visibility"], r["path"], r["method"]))
    listeners.sort(key=lambda l: (l["transport"], not l["active"], l["class"]))
    pub = {}
    for p in published:
        pub.setdefault(p["event"], []).append(p["file"])
    return {
        "branch": git_branch(svc),
        "rest": rest,
        "listeners": listeners,
        "published_events": [{"event": e, "files": sorted(set(f))} for e, f in sorted(pub.items())],
        "migrations": extract_migrations(svc),
        "aggregates": type_names(svc, "src/main/java/**/domain/model/*.java"),
        "use_cases": type_names(svc, "src/main/java/**/application/usecase/**/*.java", "UseCase"),
        "outbound_clients": type_names(svc, "src/main/java/**/application/client/**/*.java", "Client"),
    }


def git_branch(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def render_md(name: str, f: dict) -> str:
    L = [f"# {name} — extracted facts", "",
         f"> Generated by `scripts/extract_facts.py` from branch `{f['branch']}`. Do not edit by hand.", ""]
    L += ["## REST endpoints", "", "| Visibility | Method | Path | Handler |", "|---|---|---|---|"]
    L += [f"| {r['visibility']}{' (hidden)' if r['hidden'] else ''} | {r['method']} | `{r['path']}` | `{r['handler']}` |" for r in f["rest"]] or ["| – | – | – | – |"]
    L += ["", "## Consumed (listeners)", "", "| Transport | Topic / queue | Group | Class | Active |", "|---|---|---|---|---|"]
    L += [f"| {l['transport']} | {', '.join('`'+t+'`' for t in l['topics'])} | {l['group'] or '–'} | `{l['class']}` | {'yes' if l['active'] else 'no (commented out)'} |" for l in f["listeners"]] or ["| – | – | – | – | – |"]
    L += ["", "## Published events (outbox `eventType`)", ""]
    L += [f"- `{p['event']}` — {', '.join(p['files'])}" for p in f["published_events"]] or ["- none"]
    m = f["migrations"]
    L += ["", f"## Database tables (latest migration: `{m['latest']}`)", ""]
    L += [f"- `{t['table']}` (created in {t['created_in']})" for t in m["tables"]] or ["- none"]
    for title, key in (("Aggregates / domain models", "aggregates"), ("Use cases (inbound ports)", "use_cases"),
                       ("Outbound clients (ports to other services)", "outbound_clients")):
        L += ["", f"## {title}", ""]
        L += [f"- `{x}`" for x in f[key]] or ["- none"]
    return "\n".join(L) + "\n"


def is_service(path: Path) -> bool:
    main = path / "src/main/java"
    return main.is_dir() and any("@SpringBootApplication" in p.read_text(errors="replace") for p in main.rglob("*Application.java"))


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--repos", default=str(root / "repos"))
    ap.add_argument("--out", default=str(root / "architecture/generated"))
    a = ap.parse_args()
    repos, out = Path(a.repos), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    facts = {}
    for svc in sorted(p for p in repos.iterdir() if p.is_dir() and is_service(p)):
        facts[svc.name] = extract_service(svc, repos)
        (out / f"{svc.name}.md").write_text(render_md(svc.name, facts[svc.name]), encoding="utf-8")
    (out / "facts.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Extracted facts for: {', '.join(facts) or 'no services found'} → {out}")


if __name__ == "__main__":
    main()
