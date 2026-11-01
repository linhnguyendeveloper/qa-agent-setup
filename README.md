# QA Agent: setup guide (10 minutes)

You install **one skill**. It builds a QA agent that tests your tasks for you.

Watch video:

![QA agent setup guide](qa-agent-setup-guide.gif)

[Full-quality video (mp4)](https://github.com/linhnguyendeveloper/qa-agent-setup/blob/main/qa-agent-setup-guide.mp4)

```
 YOU                       qa-agent-setup                      YOUR PROJECT
┌──────────┐  "set up    ┌───────────────────┐  creates   ┌──────────────────────────┐
│ install  │──the QA────▶│ asks questions    │──────────▶ │ .claude/skills/qa-agent-x│ ← your QA agent
│ 1 skill  │  agent"     │ scans your code   │            │ .qa/qa.config.yaml       │ ← its settings
└──────────┘             │ checks it works   │            │ .qa/project-context.md   │ ← what it knows
                         └───────────────────┘            └──────────────────────────┘
                                                                      │
 LATER, every task:   /qa-agent-x 12345  ────────────────────────────┘ → test report
```

---

## 0. Before you start (tick all)

**Not sure you have these? Skip the list.** When setup starts it asks:
`All OK` or `Not sure / missing: check and install for me`. Pick the second: it checks your machine,
shows what is missing, asks once, then installs what it safely can (PyYAML, Playwright). For the rest
(Python, Node, browser) it gives you the exact command. Check by hand any time:
`python3 ~/.claude/skills/qa-agent-setup/scripts/check_prereqs.py` (add `--install` to fix).

```
[ ] Claude Code installed, your project folder opens in it
[ ] python3 + PyYAML     →  pip install pyyaml
[ ] Node + Playwright    →  npm install -g playwright      (only to test screens)
[ ] A browser you log in with (Edge or Chrome)
[ ] The app can run (locally, or a dev/stage URL you can open)
[ ] VPN connected, if your company needs it
```

---

## 1. Install the skill (1 minute)

Unzip `qa-agent-setup.zip` so you get this folder:

```
~/.claude/skills/qa-agent-setup/      ← must be exactly here
    SKILL.md
    scripts/  runner/  ...
```

Mac/Linux terminal:
```
unzip qa-agent-setup.zip -d ~/.claude/skills/
```
`.claude` is hidden in Finder: press `Cmd + Shift + .` to see it.

---

## 2. Start setup (1 minute)

Open your **project** in Claude Code, then type:

```
set up the QA agent
```
(or `/qa-agent-setup`)

---

## 3. Describe how to test (optional, but the best thing you can do)

Setup prints a tip, then asks you to write **in your own words, as long as you like**:

```
 TIP: the more detail you give, the better your QA agent.
   - what the app does and who uses it
   - HOW YOU TEST IT: main flows, which test account/data, what "correct" looks like
   - things that often break (slow data, popups, flags)
   Paste long notes or a .md file path. No need to be neat. Type "skip" to do it later.
```
Example:
```
Shop app. To test checkout: log in as qa-buyer, add any item to the cart, pay with the test card.
Order must show in "My orders" within 5 seconds. Coupon SAVE10 gives 10% off, never stack two.
Prices on the dev site reset every night. The cookie popup blocks clicks: close it first.
```
It is saved to `.qa/how-to-test.md` and used by the agent on every run. You can also paste extra notes
together with a task: `/qa-agent-<project> 12345  (notes: test with a EUR account)`.

## 4. Answer the questions (5 minutes)

It asks in this order. Short answers are fine. "You decide" is allowed.

```
 ① BRIEF  (one free-text question)
    Tell it: what the app is, tech stack, how to run it, where tasks live, how you log in.
    Got a spec or docs? Give the file path (.md is best). It reads them once.
        │
        ▼
 ② IT SCANS YOUR CODE, then shows what it understood (≤10 lines)
    → Just correct what is wrong.
        │
        ▼
 ③ ONLY THE GAPS, with a recommended answer marked "(Recommended)"
```

| It asks | Pick this if unsure |
|---|---|
| Where do tasks live? | Azure DevOps / Jira / ClickUp / GitHub, or **"I paste the text"** (easiest) |
| Which environments? | local + dev. Prod = **never** write |
| Default environment? | `local` if you run the app, else `dev` |
| VPN needed? | Yes only if you can't open the app without it |
| How to log in? | **Copy my browser profile** (no passwords typed anywhere) |
| **API token needed?** | See the box below |
| Which browser? | The one you are logged in with |
| Which AI agent? | Claude Code |
| **Name for the QA agent?** | Accept the default: `qa-agent-<your-project>` (e.g. project `shop-web` → `/qa-agent-shop-web`) |

### API token: which answer?

```
 Do you need to test the backend/API directly (curl, Swagger)?
        │
   NO ──┴── YES
    │         │
 "Optional"  "Required"  → it shows you how to get the token (below)
 Tests the screen only.
 API checks = NOT COVERED.
 You can add a token later.
```

Get a token (if required):
```
 1. Your system's settings → "Personal access token" / "API token"   (best)
 2. or: log in to the app → DevTools (F12) → Network → click any API call
        → Request Headers → Authorization → copy the part after "Bearer "
        (this one expires, you will refresh it)
 3. or: ask the backend team for a dev token
```
Save it **without showing it** (run in your terminal, never paste it in the chat):
```
read -rs T && printf 'API_TOKEN=%s\n' "$T" >> .env.local && unset T
git check-ignore .env.local        ← must print ".env.local" (= it is NOT committed)
```

---

## 5. It checks itself (automatic)

```
 verify ──▶ something missing? ──▶ it fixes it, or asks you ONE question,
   ▲                                or tells you the exact step (e.g. "connect VPN")
   └────────────── repeats until READY (max 4 rounds)
```

You will see:
```
 PASS  config ok
 PASS  tools ok
 WARN  API_TOKEN not set (optional)        ← fine, not blocking
 FAIL  VPN unreachable  → connect VPN, say "done"
 ...
 READY ✔
```
Then it opens the browser once to check you are logged in. **Log in if the window asks**, then say "done".

---

## 6. Save it for your team (1 minute)

Say **"commit"** when asked, or run:
```
git add .claude/skills/qa-agent-<project> .qa
git commit -m "chore: add QA agent"
```
Teammates pull the repo and can run QA right away. **They do not need the setup skill.**

---

## 7. Use it (every task)

```
/qa-agent-<project> 12345
```
```
 reads the task ─▶ shows a test plan (table) ─▶ you say "yes" ─▶ runs tests ─▶ report
                  (nothing runs before yes)                                   │
                                                                               ▼
                                              OVERALL: PASS / FAIL / PENDING
                                              AC1: PASS   AC2: FAIL   AC3: PENDING ...
```

| Report word | Meaning |
|---|---|
| PASS | Checked, matches, evidence shown |
| FAIL | Checked, does not match, evidence shown |
| PENDING | Needs **your** eyes (visual) or a decision |
| NOT COVERED | Could not test (no data, no token, backend not ready) |

Not `OVERALL: PASS` yet? Loop until it is:
```
 fix what FAILED (the report shows the request and what it saw; ask Claude to fix it)
        │
        ▼
 run the same command again ──▶ still FAIL? repeat ──▶ OVERALL: PASS ✔
```
PENDING is not a failure: it needs your decision or a visual check.

No acceptance criteria? Bug report only? It still works: it writes its own test scenarios first and shows them.

### Several tasks at once (git worktrees)

Runs in different projects or worktrees keep their own browser, port and network log, and stopping
one never stops another. For a worktree, test **its** code on **its** own dev server:
```
cp -R ../main/.qa . && mkdir -p .claude/skills \
  && cp -R ../main/.claude/skills/qa-agent-<project> .claude/skills/   # only if these are not committed
pnpm dev --port 8091                         # this worktree's dev server
printf 'environments:\n  list:\n    local:\n      frontend_url: "http://localhost:8091"\n' > .qa/qa.config.local.yaml
echo '.qa/qa.config.local.yaml' >> .gitignore   # per checkout, never committed
```
Without the local file, every worktree tests the URL in `qa.config.yaml`, which is the main
checkout's server. Parallel runs share the backend and its database: give each task its own test
data (accounts, records) so one run does not change what another one checks.

---

## 8. Something wrong?

| You see | Do this |
|---|---|
| `qa.config.yaml not found` | Run "set up the QA agent" in the project folder |
| App unreachable | Start the app (`environments.local.start`) or connect VPN |
| Not logged in / SSO expired | Log in in the browser window it opens, say "done" |
| `API_TOKEN is not set` | Optional? Ignore. Required? Section 4, token box |
| `playwright` missing | `npm install -g playwright` |
| Changed login/URL/tracker later | Run "set up the QA agent" again; it asks only what changed |
| Want a different agent name | Run setup again, answer the name question, delete the old folder |

Rules it always follows: never prints a token, never writes to your task tracker, never edits data on an environment you marked "never".
