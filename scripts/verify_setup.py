"""Self-check for .qa/qa.config.yaml: finds what is missing or broken and says how to fix each item.

Every check has an id, a status (PASS/WARN/FAIL), whether it blocks a QA run, and a fix descriptor:
  auto   -> safe change this script can apply with --fix (mkdir, .gitignore lines, context stub)
  config -> a config value is missing: the agent asks the user, then runs qa_config_set.py
  user   -> something only the user can do (connect VPN, `az login`, export a token), with exact steps
Secrets are never printed.

Usage: python verify_setup.py [--fix] [--quick] [--live] [--task <id|file>] [--json] [--write]
  --fix    apply the safe automatic fixes, then re-check
  --quick  config + tools + secrets only (no network); what the QA run uses as its preflight
  --live   also start the configured browser, probe for a logged-in session, then stop it
  --task   also fetch this task through the configured adapter
  --json   machine-readable result (for the agent to act on)
  --write  save the result to <scratch>/setup-status.json
Exit code: 1 when something blocking fails.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
# generated agent: runner scripts sit next to this file; setup skill: they live in ../runner/scripts
QA_SCRIPTS = HERE if (HERE / "qa_config.py").exists() else HERE.parent / "runner" / "scripts"
sys.path.insert(0, str(QA_SCRIPTS))
import qa_config  # noqa: E402

MISSING = ("", None, "TODO")
checks: list[dict] = []


def add(cid: str, status: str, msg: str = "", blocking: bool = False, fix: dict | None = None) -> None:
    checks.append({"id": cid, "status": status, "message": msg, "blocking": blocking and status != "PASS", "fix": fix})


def get(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def reachable(url: str, timeout: int = 6) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "qa-setup-check"})
        return True, str(urllib.request.urlopen(req, timeout=timeout).status)
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code}"  # the host answered
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return False, str(getattr(e, "reason", e))


# ------------------------------------------------------------------ config completeness

def required_values(cfg: dict) -> list[tuple[str, str, str]]:
    """(dotted path, why it is needed, question to ask) for everything a QA run depends on."""
    kinds = get(cfg, "project.kinds") or []
    default = get(cfg, "environments.default")
    need = [
        ("task_source.type", "to read tasks", "Where do your tasks live (Azure DevOps, Jira, ClickUp, GitHub, Linear, or pasted text)?"),
        ("environments.default", "to know where to test", "Which environment should QA use when you name none?"),
        ("agent.runtime", "to ask questions the right way", "Which AI agent runs QA (claude, codex, gemini, cursor, other)?"),
    ]
    if "frontend" in kinds or "mobile" in kinds:
        need += [
            (f"environments.list.{default}.frontend_url", "frontend base URL for the default environment", f"What is the frontend URL for '{default}'?"),
            ("frontend.browser", "browser to drive", "Which browser (edge or chrome)?"),
            ("frontend.login.mode", "how QA gets a logged-in browser", "How should QA log in (copy my browser profile, I log in by hand, stored state)?"),
        ]
    if "backend" in kinds:
        backend_env = get(cfg, f"environments.list.{default}.backend_env") or default
        for svc, spec in (get(cfg, "backend.services") or {}).items():
            spec = spec or {}
            for version in spec.get("versions") or [None]:
                path = f"backend.services.{svc}.base_url." + (f"{version}." if version else "") + backend_env
                label = f"'{svc}'" + (f" {version}" if version else "")
                need.append((path, f"API base URL of {label}", f"What is the base URL of the {label} API in '{backend_env}'?"))
        if get(cfg, "backend.auth.type") not in ("none", "optional"):
            need.append(("backend.auth.env_var", "to read the API token", "What is the NAME of the env var that holds the API token?"))
    if get(cfg, "task_source.auth.method") == "env-token":
        need.append(("task_source.auth.env_var", "to read the tracker token", "What is the NAME of the env var that holds the tracker token?"))
    return need


def check_config(cfg: dict) -> None:
    for key in ("project", "task_source", "environments", "workstreams", "agent", "report"):
        add(f"config.{key}", "PASS" if key in cfg else "FAIL", "" if key in cfg else f"section '{key}' is missing", True,
            None if key in cfg else {"kind": "ask", "question": f"Re-run the setup section for '{key}'."})
    envs = get(cfg, "environments.list") or {}
    default = get(cfg, "environments.default")
    ok = default in envs
    add("config.default-env", "PASS" if ok else "FAIL", "" if ok else f"default '{default}' is not in environments.list ({', '.join(envs) or 'empty'})", True,
        None if ok else {"kind": "config", "set": "environments.default", "ask": "Which environment should be the default?"})
    for path, why, question in required_values(cfg):
        value = get(cfg, path)
        missing = value in MISSING
        add(f"value.{path}", "FAIL" if missing else "PASS", f"missing: needed {why}" if missing else "", True,
            {"kind": "config", "set": path, "ask": question} if missing else None)


# ------------------------------------------------------------------ files, git hygiene

def is_ignored(root: pathlib.Path, entry: str) -> bool:
    """Ask git, which understands globs (.env*.local), negation (!x), comments, nested and global
    ignore files. Outside a git repo, fall back to finding the entry in .gitignore as text."""
    proc = subprocess.run(["git", "check-ignore", "-q", entry], cwd=root, capture_output=True)
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").is_file() else ""
    return entry.rstrip("/") in gitignore.splitlines() or entry in gitignore.splitlines()


def check_files(cfg: dict, root: pathlib.Path) -> None:
    scratch = root / (get(cfg, "project.scratch_dir") or ".qa/runs")
    add("fs.scratch", "PASS" if scratch.is_dir() else "WARN", "" if scratch.is_dir() else f"{scratch.relative_to(root)} does not exist", False,
        None if scratch.is_dir() else {"kind": "auto", "action": "mkdir", "path": str(scratch)})
    wanted = [str(scratch.relative_to(root)) + "/"]
    env_file = get(cfg, "backend.auth.env_file") or get(cfg, "task_source.auth.env_file")
    if env_file:
        wanted.append(env_file)
    if (root / ".qa" / qa_config.LOCAL_NAME).is_file():
        wanted.append(f".qa/{qa_config.LOCAL_NAME}")
    for entry in wanted:
        ignored = is_ignored(root, entry)
        add(f"git.ignore.{entry}", "PASS" if ignored else "WARN", "" if ignored else f"'{entry}' is not git-ignored", False,
            None if ignored else {"kind": "auto", "action": "gitignore", "line": entry})
    context = root / (get(cfg, "project.context_file") or ".qa/project-context.md")
    add("fs.context", "PASS" if context.is_file() else "WARN", "" if context.is_file() else "project-context.md is missing", False,
        None if context.is_file() else {"kind": "auto", "action": "context-stub", "path": str(context)})
    htt = root / (get(cfg, "project.how_to_test") or ".qa/how-to-test.md")
    has = htt.is_file() and len(htt.read_text(encoding="utf-8").split()) >= 30
    add("fs.how-to-test", "PASS" if has else "WARN", "" if has else "tip: no testing notes yet. Describe how you test (flows, accounts, data, traps) in .qa/how-to-test.md: more detail = better QA", False,
        None if has else {"kind": "user", "steps": ["write a few lines (long is fine) in .qa/how-to-test.md, or tell setup to save them"]})
    if env_file and (root / env_file).exists():
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", env_file], cwd=root, capture_output=True).returncode == 0
        add("git.secret-not-tracked", "FAIL" if tracked else "PASS", f"{env_file} is tracked by git: it must never hold the secret" if tracked else "", True,
            {"kind": "user", "steps": [f"git rm --cached {env_file}", "move the token to a git-ignored file", "rotate the token if it was ever committed"]} if tracked else None)


def check_knowledge(cfg: dict, root: pathlib.Path) -> None:
    docs = get(cfg, "knowledge.docs") or []
    kdir = root / (get(cfg, "knowledge.dir") or ".qa/knowledge")
    if not docs and not get(cfg, "knowledge.code_map"):
        return
    chunks = kdir / "chunks.jsonl"
    if not chunks.is_file():
        return add("kb.ingested", "WARN", "knowledge configured but not ingested", False, {"kind": "auto", "action": "kb-ingest", "docs": docs, "code": bool(get(cfg, "knowledge.code_map"))})
    proc = subprocess.run([sys.executable, str(QA_SCRIPTS / "kb.py"), "status", "--out", str(kdir)], capture_output=True, text=True, cwd=root)
    stale = "stale: none" not in proc.stdout
    add("kb.fresh", "WARN" if stale else "PASS", "docs changed since the last ingest" if stale else "", False,
        {"kind": "auto", "action": "kb-ingest", "docs": docs, "code": bool(get(cfg, "knowledge.code_map"))} if stale else None)
    add("kb.overview", "PASS" if (kdir / "overview.md").is_file() else "WARN", "" if (kdir / "overview.md").is_file() else "overview.md not written yet", False,
        None if (kdir / "overview.md").is_file() else {"kind": "user", "steps": ["agent: read index.md + codebase-map.md and write .qa/knowledge/overview.md (<= 60 lines)"]})
    ignored = is_ignored(root, str(chunks.relative_to(root)))
    add("kb.chunks-ignored", "PASS" if ignored else "WARN", "" if ignored else "chunks.jsonl is derived and large: git-ignore it", False,
        None if ignored else {"kind": "auto", "action": "gitignore", "line": str(kdir.relative_to(root)) + "/chunks.jsonl"})


# ------------------------------------------------------------------ tools and secrets

def check_tools(cfg: dict) -> None:
    kinds = get(cfg, "project.kinds") or []
    if "frontend" in kinds:
        browser = get(cfg, "frontend.browser") or "edge"
        mac = {"edge": "/Applications/Microsoft Edge.app", "chrome": "/Applications/Google Chrome.app"}
        found = pathlib.Path(mac[browser]).exists() if sys.platform == "darwin" and browser in mac else bool(shutil.which({"edge": "microsoft-edge", "chrome": "google-chrome"}.get(browser, browser)))
        add("tool.browser", "PASS" if found else "FAIL", "" if found else f"browser '{browser}' not found", True,
            None if found else {"kind": "config", "set": "frontend.browser", "ask": f"'{browser}' is not installed: use another Chromium browser?"})
        pw = subprocess.run(["npx", "--no-install", "playwright", "--version"], capture_output=True, text=True, cwd="/tmp")
        add("tool.playwright", "PASS" if pw.returncode == 0 else "WARN", pw.stdout.strip() if pw.returncode == 0 else "Playwright is not installed globally", False,
            None if pw.returncode == 0 else {"kind": "user", "steps": ["npm install -g playwright   (global, persists; ask before running)"]})
        port = int(get(cfg, "frontend.debug_port") or 9222)
        with socket.socket() as s:
            busy = s.connect_ex(("127.0.0.1", port)) == 0
        # browser.sh moves to the next free port and records it in <scratch>/cdp.port, so a busy port
        # (another QA run, another worktree) is information, not a problem.
        add("tool.debug-port", "PASS", f"port {port} in use: the run will take the next free port" if busy else "")
    kind = get(cfg, "task_source.type")
    cli = {"azure-devops": "az", "github": "gh"}.get(kind)
    if cli and get(cfg, "task_source.auth.method") == "cli":
        have = bool(shutil.which(cli))
        add("tool.task-cli", "PASS" if have else "FAIL", "" if have else f"'{cli}' CLI not found", True,
            None if have else {"kind": "user", "steps": [f"install the {cli} CLI", "az login" if cli == "az" else "gh auth login"]})
        if have:
            probe = subprocess.run([cli, "account", "show"] if cli == "az" else [cli, "auth", "status"], capture_output=True, text=True)
            add("auth.task-cli", "PASS" if probe.returncode == 0 else "FAIL", "" if probe.returncode == 0 else f"'{cli}' is not logged in", True,
                None if probe.returncode == 0 else {"kind": "user", "steps": ["az login" if cli == "az" else "gh auth login", "re-run the check"]})


def check_secrets(cfg: dict, root: pathlib.Path) -> None:
    for label, auth in (("backend.auth", get(cfg, "backend.auth")), ("task_source.auth", get(cfg, "task_source.auth"))):
        if not auth or not auth.get("env_var") or auth.get("type") == "none":
            continue
        have = bool(qa_config.resolve_secret(auth, root))
        where = auth.get("env_file") or "your shell"
        if auth.get("type") == "optional":
            add(f"secret.{auth['env_var']}", "PASS" if have else "WARN",
                "" if have else f"{auth['env_var']} not set (optional): API checks will be NOT COVERED, screen testing still works", False,
                None if have else {"kind": "user", "steps": [f"only if you want API checks: follow the token guide (references/interview.md, 'API token'), then put {auth['env_var']} in {where}"]})
            continue
        add(f"secret.{auth['env_var']}", "PASS" if have else "FAIL", "" if have else f"{auth['env_var']} is not set", True,
            None if have else {"kind": "user", "steps": [f"put {auth['env_var']}=<value> in {where} (git-ignored) or export it in the shell", "never paste the value into the chat", "re-run the check"]})


# ------------------------------------------------------------------ network

def check_network(cfg: dict) -> None:
    net = cfg.get("network") or {}
    if net.get("vpn_required"):
        if net.get("vpn_check_url") in MISSING:
            add("net.vpn-probe", "WARN", "VPN is required but no vpn_check_url is set", False,
                {"kind": "config", "set": "network.vpn_check_url", "ask": "Which URL only answers on the VPN?"})
        else:
            ok, why = reachable(net["vpn_check_url"])
            add("net.vpn", "PASS" if ok else "FAIL", why if ok else "VPN probe unreachable", True,
                None if ok else {"kind": "user", "steps": ["connect the VPN", "re-run the check"]})
    for name, env in (get(cfg, "environments.list") or {}).items():
        url = env.get("frontend_url")
        if url in MISSING:
            continue
        ok, why = reachable(url)
        local = name == "local"
        add(f"net.{name}.frontend", "PASS" if ok else "WARN", why if ok else f"{url} unreachable", False,
            None if ok else {"kind": "user", "steps": [f"start the app: {env.get('start') or '<start command not configured>'}"] if local else ["check the VPN / the URL"]})
    for svc, spec in (get(cfg, "backend.services") or {}).items():
        for env_name, url in ((spec or {}).get("base_url") or {}).items():
            if isinstance(url, str) and url and env_name in (get(cfg, "environments.list") or {}):
                ok, why = reachable(url)
                add(f"net.backend.{svc}.{env_name}", "PASS" if ok else "WARN", why if ok else "unreachable", False,
                    None if ok else {"kind": "user", "steps": ["check the VPN / the base_url"]})


def check_task(ref: str) -> None:
    proc = subprocess.run([sys.executable, str(QA_SCRIPTS / "fetch_task.py"), ref], capture_output=True, text=True)
    head = " | ".join((proc.stdout.splitlines() or ["", ""])[:2])
    add("task.fetch", "PASS" if proc.returncode == 0 else "FAIL", head if proc.returncode == 0 else proc.stderr.strip()[-240:], True,
        None if proc.returncode == 0 else {"kind": "user", "steps": ["fix the tracker auth / task_source settings shown above", "re-run with --task"]})


def check_live(cfg: dict, root: pathlib.Path) -> None:
    """Start the browser the way a QA run would and look at what the user sees."""
    fe = cfg.get("frontend") or {}
    default = get(cfg, "environments.default")
    url = get(cfg, f"environments.list.{default}.frontend_url")
    if url in MISSING:
        return add("live.login", "FAIL", "no frontend_url for the default environment", True, {"kind": "config", "set": f"environments.list.{default}.frontend_url", "ask": "Frontend URL?"})
    scratch = root / (get(cfg, "project.scratch_dir") or ".qa/runs")
    scratch.mkdir(parents=True, exist_ok=True)
    sh = QA_SCRIPTS / "frontend" / "browser.sh"
    mode = (fe.get("login") or {}).get("mode", "manual")
    port = str(fe.get("debug_port", 9222))
    start = ["bash", str(sh), "start-profile", url, str(scratch), port, (fe.get("login") or {}).get("profile", "Default"), fe.get("browser", "edge")] if mode == "profile-copy" else ["bash", str(sh), "start", url, str(scratch), port]
    out = subprocess.run(start, capture_output=True, text=True)
    if out.returncode != 0:
        return add("live.browser", "FAIL", (out.stdout + out.stderr).strip()[-200:], True, {"kind": "user", "steps": ["check frontend.browser / frontend.login.profile (bash browser.sh profiles <browser>)"]})
    try:
        time.sleep(10)
        import os
        env = {**os.environ, "APP_HOST": url.split("//")[-1].split("/")[0], "QA_SCRATCH": str(scratch), "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}
        env.pop("CDP_PORT", None)  # attach to the port browser.sh recorded for this scratch dir
        probe = subprocess.run(["node", str(QA_SCRIPTS / "frontend" / "probe.js")], capture_output=True, text=True, env=env, timeout=60)
        try:
            data = json.loads(probe.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return add("live.attach", "FAIL", (probe.stdout + probe.stderr).strip()[-240:], True, {"kind": "user", "steps": ["make sure Playwright is installed globally", "check frontend.debug_port"]})
        if data.get("loginDetected"):
            add("live.login", "WARN", f"the browser shows a login page ({data.get('url')})", True,
                {"kind": "user", "steps": ["log in in the open browser window", "re-run with --live; for profile-copy mode check frontend.login.profile is the profile you are logged in with, or switch frontend.login.mode to manual"]})
        else:
            add("live.login", "PASS", f"app loaded and no login page: {data.get('title')!r} at {data.get('url')}", True)
    finally:
        subprocess.run(["bash", str(sh), "stop", str(scratch)], capture_output=True)


# ------------------------------------------------------------------ auto fixes

def apply_fixes(root: pathlib.Path) -> list[str]:
    done = []
    for c in checks:
        fix = c.get("fix") or {}
        if c["status"] == "PASS" or fix.get("kind") != "auto":
            continue
        if fix["action"] == "mkdir":
            pathlib.Path(fix["path"]).mkdir(parents=True, exist_ok=True)
            done.append(f"created {fix['path']}")
        elif fix["action"] == "gitignore":
            path = root / ".gitignore"
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            path.write_text(text + ("" if text.endswith("\n") or not text else "\n") + fix["line"] + "\n", encoding="utf-8")
            done.append(f"added '{fix['line']}' to .gitignore")
        elif fix["action"] == "kb-ingest":
            kb = str(QA_SCRIPTS / "kb.py")
            if fix.get("docs"):
                subprocess.run([sys.executable, kb, "ingest", *fix["docs"]], cwd=root, capture_output=True)
            if fix.get("code"):
                subprocess.run([sys.executable, kb, "code", "."], cwd=root, capture_output=True)
            done.append("ran kb.py ingest/code")
        elif fix["action"] == "context-stub":
            target = pathlib.Path(fix["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Project context for QA\n\nFacts only (verified by the user or observed). One bullet per fact.\n\n- (none recorded yet)\n", encoding="utf-8")
            done.append(f"created {fix['path']}")
    return done


def run_checks(args, cfg: dict, root: pathlib.Path) -> None:
    checks.clear()
    check_config(cfg)
    check_files(cfg, root)
    check_tools(cfg)
    check_secrets(cfg, root)
    check_knowledge(cfg, root)
    if not args.quick:
        check_network(cfg)
    if args.task:
        check_task(args.task)
    if args.live:
        check_live(cfg, root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    cfg, root = qa_config.load()
    run_checks(args, cfg, root)
    fixed: list[str] = []
    if args.fix:
        fixed = apply_fixes(root)
        if fixed:
            run_checks(args, cfg, root)

    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    open_items = sorted((c for c in checks if c["status"] != "PASS"), key=lambda c: (not c["blocking"], order[c["status"]]))
    blockers = [c for c in checks if c["blocking"]]
    result = {"ready": not blockers, "passed": sum(c["status"] == "PASS" for c in checks), "total": len(checks),
              "blocking": [c["id"] for c in blockers], "auto_fixed": fixed, "checks": checks}
    if args.write:
        scratch = root / (get(cfg, "project.scratch_dir") or ".qa/runs")
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "setup-status.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for c in checks:
            print(f"{c['status']:4} {c['id']}" + (f" - {c['message']}" if c["message"] else ""))
        for line in fixed:
            print(f"FIXED {line}")
        print(f"\n{result['passed']}/{result['total']} checks pass. " + ("READY: a QA run can start." if result["ready"] else f"NOT READY: {len(blockers)} blocking item(s)."))
        if open_items:
            print("\nNEXT ACTIONS (blocking first):")
            for i, c in enumerate(open_items[:6], 1):
                fix = c["fix"] or {}
                if fix.get("kind") == "config":
                    how = f"ask the user: {fix['ask']}  then: qa_config_set.py {fix['set']} <answer>"
                elif fix.get("kind") == "user":
                    how = "user steps: " + "; ".join(fix["steps"])
                elif fix.get("kind") == "auto":
                    how = "run again with --fix"
                else:
                    how = fix.get("question", "review")
                print(f"{i}. [{'BLOCKS' if c['blocking'] else 'optional'}] {c['id']}: {how}")
    sys.exit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
