"""Facts for the repos that are not Spring services: oms-web, oms-core and development.

Called by extract_facts.py. Standard library only.

- oms-web: the backend calls its HTTP adapters make (method + path) and its ports. The calls are compared with the
  services' endpoints, so a call to an endpoint that does not exist shows up here.
- oms-core: the released version and the public types per package.
- development: a plain list of what the local stack defines (compose services, topics, connectors, LocalStack
  resources). It is a local setup: nothing in it is checked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------- oms-web

CONST_RE = re.compile(r"\bconst\s+(\w+)\s*=\s*'([^']*)'\s*;")
HELPER_RE = re.compile(r"\bconst\s+(\w+)\s*=\s*\([^)]*\)\s*=>\s*`([^`]*)`\s*;")
HTTP_CALL_RE = re.compile(r"\bhttp\.(get|post|put|delete|patch)\b")
PORT_RE = re.compile(r"\bexport\s+interface\s+(\w+Port)\b")
PARAM_RE = re.compile(r"\{[^{}]*\}")


def _balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Index just after the bracket that closes the one at `start`; -1 when it never closes."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _resolve_expr(expr: str, consts: dict[str, str], helpers: dict[str, str], depth: int) -> str:
    expr = expr.strip()
    if expr in consts:
        return consts[expr]
    call = re.match(r"(\w+)\s*\((.*)\)\s*$", expr, re.S)
    if call and call.group(1) in helpers and depth < 5:
        return _resolve_template(helpers[call.group(1)], consts, helpers, depth + 1)
    if call and call.group(1) == "encodeURIComponent":
        expr = call.group(2).strip()
    name = re.sub(r"\W+", "", expr.split(".")[-1]) or "value"
    return "{" + name + "}"


def _resolve_template(template: str, consts: dict[str, str], helpers: dict[str, str], depth: int = 0) -> str:
    out, i = [], 0
    while i < len(template):
        if template.startswith("${", i):
            end = _balanced(template, i + 1, "{", "}")
            if end == -1:
                break
            out.append(_resolve_expr(template[i + 2:end - 1], consts, helpers, depth))
            i = end
        else:
            out.append(template[i])
            i += 1
    return "".join(out)


def _first_argument(text: str, pos: int) -> str | None:
    """The first argument of the call whose name ends at `pos`, skipping an optional `<Type>`."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos < len(text) and text[pos] == "<":
        pos = _balanced(text, pos, "<", ">")
        if pos == -1:
            return None
    if pos >= len(text) or text[pos] != "(":
        return None
    pos += 1
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return None
    if text[pos] == "`":
        end = text.find("`", pos + 1)
        return text[pos:end + 1] if end != -1 else None
    if text[pos] in "'\"":
        end = text.find(text[pos], pos + 1)
        return text[pos:end + 1] if end != -1 else None
    m = re.match(r"\w+", text[pos:])
    if not m:
        return None
    after = pos + m.end()
    if after < len(text) and text[after] == "(":
        end = _balanced(text, after, "(", ")")
        return text[pos:end] if end != -1 else None
    return m.group(0)


def web_calls(source: str) -> list[dict]:
    """Backend calls in one adapter file: [{method, path}], path with {name} placeholders."""
    consts = dict(CONST_RE.findall(source))
    helpers = dict(HELPER_RE.findall(source))
    calls = []
    for m in HTTP_CALL_RE.finditer(source):
        arg = _first_argument(source, m.end())
        if arg is None:
            continue
        if arg[0] == "`":
            path = _resolve_template(arg[1:-1], consts, helpers)
        elif arg[0] in "'\"":
            path = arg[1:-1]
        else:
            path = _resolve_expr(arg, consts, helpers, 0)
        calls.append({"method": m.group(1).upper(), "path": path})
    return calls


def shape(path: str) -> str:
    """A path with its parameter names removed, so `/a/{id}` and `/a/{productId}` compare equal."""
    return PARAM_RE.sub("{}", path)


def extract_web(repo: Path, service_facts: dict[str, dict]) -> dict:
    known = {(r["method"], shape(r["path"])): (name, r) for name, f in service_facts.items() for r in f.get("rest", [])}
    calls, seen = [], set()
    http_dir = repo / "src/adapters/http"
    for ts in sorted(http_dir.rglob("*.ts")) if http_dir.is_dir() else []:
        if ts.name.endswith(".test.ts"):
            continue
        for c in web_calls(ts.read_text(encoding="utf-8", errors="replace")):
            key = (c["method"], c["path"])
            if key in seen:
                continue
            seen.add(key)
            hit = known.get((c["method"], shape(c["path"])))
            calls.append({**c, "file": str(ts.relative_to(repo.parent)),
                          "service": hit[0] if hit else None,
                          "handler": hit[1]["handler"] if hit else None,
                          "visibility": hit[1]["visibility"] if hit else None})
    calls.sort(key=lambda c: (c["path"], c["method"]))
    ports_file = repo / "src/ports/index.ts"
    ports = sorted(set(PORT_RE.findall(ports_file.read_text(encoding="utf-8", errors="replace")))) if ports_file.is_file() else []
    return {"kind": "web", "calls": calls, "ports": ports,
            "calls_without_endpoint": [f"{c['method']} {c['path']}" for c in calls if c["service"] is None]}


def render_web(name: str, f: dict, branch: str) -> str:
    L = [f"# {name} — extracted facts", "",
         f"> Generated by `scripts/extract_facts.py` from branch `{branch}`. Do not edit by hand.", "",
         "## Backend calls (`src/adapters/http`)", "",
         "| Method | Path | Service | Handler | File |", "|---|---|---|---|---|"]
    L += [f"| {c['method']} | `{c['path']}` | {c['service'] or '**not found**'} | "
          f"{'`' + c['handler'] + '`' if c['handler'] else '–'} | {c['file']} |" for c in f["calls"]] or ["| – | – | – | – | – |"]
    if f["calls_without_endpoint"]:
        L += ["", "> **Endpoint check failed.** " + ", ".join(f"`{c}`" for c in f["calls_without_endpoint"])
              + " matches no endpoint in the services' facts. Either the endpoint is gone or renamed, or "
              "`scripts/extract_other.py` does not read how the path is built."]
    elif f["calls"]:
        L += ["", f"Endpoint check: all {len(f['calls'])} calls match an endpoint of a service (method and path shape)."]
    L += ["", "## Ports (`src/ports/index.ts`)", ""]
    L += [f"- `{p}`" for p in f["ports"]] or ["- none"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- oms-core

def extract_core(repo: Path) -> dict:
    version = None
    props = repo / "gradle.properties"
    if props.is_file():
        m = re.search(r"^version\s*=\s*(\S+)", props.read_text(encoding="utf-8"), re.M)
        version = m.group(1) if m else None
    base = repo / "src/main/java/com/dotran/oms/core"
    packages: dict[str, list[str]] = {}
    for java in sorted(base.rglob("*.java")) if base.is_dir() else []:
        src = java.read_text(encoding="utf-8", errors="replace")
        if not re.search(rf"\bpublic\s+(?:abstract\s+|final\s+|sealed\s+)*(?:class|interface|enum|record|@interface)\s+{re.escape(java.stem)}\b", src):
            continue
        pkg = ".".join(java.parent.relative_to(base).parts) or "(root)"
        packages.setdefault(pkg, []).append(java.stem)
    return {"kind": "library", "version": version, "packages": {k: sorted(v) for k, v in sorted(packages.items())}}


def render_core(name: str, f: dict, branch: str) -> str:
    L = [f"# {name} — extracted facts", "",
         f"> Generated by `scripts/extract_facts.py` from branch `{branch}`. Do not edit by hand.", "",
         f"Version on this branch (`gradle.properties`): `{f['version']}`", "",
         "## Public types (`com.dotran.oms.core`)", "", "| Package | Types |", "|---|---|"]
    L += [f"| `{p}` | {', '.join('`' + t + '`' for t in types)} |" for p, types in f["packages"].items()] or ["| – | – |"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- development (local setup, listed only)

def compose_services(text: str) -> list[dict]:
    services, section, current = [], None, None
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = re.match(r"^([A-Za-z_-]+):", line)
        if top:
            section, current = top.group(1), None
            continue
        if section != "services":
            continue
        svc = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if svc:
            current = {"name": svc.group(1), "image": None, "ports": []}
            services.append(current)
            continue
        if current is None:
            continue
        image = re.match(r"^    image:\s*(\S+)", line)
        if image:
            current["image"] = image.group(1)
        port = re.match(r"^      - [\"']?(\d+(?:-\d+)?):\d+(?:-\d+)?[\"']?\s*$", line)
        if port:
            current["ports"].append(port.group(1))
    return services


def extract_development(repo: Path) -> dict:
    compose = repo / "docker/docker-compose.yml"
    services = compose_services(compose.read_text(encoding="utf-8")) if compose.is_file() else []
    topics: list[str] = []
    script = repo / "docker/kafka/create-topics.sh"
    if script.is_file():
        m = re.search(r"^TOPICS=\((.*?)^\)", script.read_text(encoding="utf-8"), re.S | re.M)
        if m:
            for line in m.group(1).split("\n"):
                topics += line.split("#")[0].split()
    connectors = []
    cdir = repo / "docker/kafka-connect/connectors"
    for j in sorted(cdir.glob("*.json")) if cdir.is_dir() else []:
        try:
            cfg = json.loads(j.read_text(encoding="utf-8"))
        except ValueError:
            cfg = {}
        connectors.append({"name": j.stem, "database": cfg.get("database.dbname"), "slot": cfg.get("slot.name"),
                           "publication": cfg.get("publication.name")})
    resources = []
    tdir = repo / "docker/infra/local"
    for tf in sorted(tdir.glob("*.tf")) if tdir.is_dir() else []:
        resources += [{"type": t, "name": n} for t, n in re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"', tf.read_text(encoding="utf-8"), re.M)]
    return {"kind": "local-infra", "compose_services": services, "topics": sorted(topics), "connectors": connectors,
            "localstack_resources": sorted(resources, key=lambda r: (r["type"], r["name"]))}


def render_development(name: str, f: dict, branch: str) -> str:
    L = [f"# {name} — extracted facts", "",
         f"> Generated by `scripts/extract_facts.py` from branch `{branch}`. Do not edit by hand.", "",
         "Local setup only: this lists what the stack defines so it can be found. Nothing here is checked against a rule.", "",
         "## Compose services (`docker/docker-compose.yml`)", "", "| Service | Image | Host ports |", "|---|---|---|"]
    L += [f"| `{s['name']}` | {s['image'] or 'built locally'} | {', '.join(s['ports']) or '–'} |" for s in f["compose_services"]] or ["| – | – | – |"]
    L += ["", "## Topics created by `docker/kafka/create-topics.sh`", ""]
    L += [f"- `{t}`" for t in f["topics"]] or ["- none"]
    L += ["", "## Connectors (`docker/kafka-connect/connectors`)", "", "| Connector | Database | Slot | Publication |", "|---|---|---|---|"]
    L += [f"| `{c['name']}` | {c['database'] or '–'} | {c['slot'] or '–'} | {c['publication'] or '–'} |" for c in f["connectors"]] or ["| – | – | – | – |"]
    L += ["", "## LocalStack resources (`docker/infra/local`)", ""]
    L += [f"- `{r['type']}` `{r['name']}`" for r in f["localstack_resources"]] or ["- none"]
    return "\n".join(L) + "\n"
