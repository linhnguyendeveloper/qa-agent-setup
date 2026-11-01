# Frontend validation (Playwright over CDP)

Config used: `environments.*.frontend_url`, `frontend.*` (browser, debug_port, login, post_login_steps,
app_notes, feature_flags), `extensions`, `project.scratch_dir`.

## 0. Preflight

- `npx --no-install playwright --version` (run outside the project). If missing, tell the user it
  installs globally and persists (`npm install -g playwright`), then install. Never add Playwright
  as a dependency of the project under test. No browser download is needed: scenarios drive the
  user's installed Chromium browser (`frontend.browser`) over CDP.
- Write scenario scripts into the scratch dir. Run them with `NODE_PATH="$(npm root -g)"`.
- For `local`, `curl -sI <frontend_url>`; nothing answering -> tell the user `environments.local.start`.

## 1. Extract the screen and criteria

From the task: the screen/route/component named, an example or mock (strongest signal for expected
state), the acceptance criteria (each distinct testable statement = one criterion), edge cases.
Images attached to the task: read each and use as the visual source of truth for structure, copy,
states and colors. Route or element unnamed -> ask the user (menu path, which entity); never guess.

## 2. Black-box locators

Plan elements by what the task names (title, label, button text) and mark the locator "to confirm
on the live page". After login, inspect the rendered DOM (`locator.ariaSnapshot()`, screenshot) and
choose in order: role + accessible name, label, visible text (fragile, say so), a `data-testid`
only if it is visible in the DOM. Observing the app's own HTTP traffic (`page.on('request')`,
`waitForRequest/Response`) is allowed: use it when a criterion is about what the UI sends.
Read project-specific traps from `frontend.app_notes`.

## 3. Browser and login

`frontend.login.mode`:

- `profile-copy` (default when set): `bash scripts/frontend/browser.sh start-profile "<url>" "<scratch>" <port> "<profile>" <browser>`
  copies only the login files of the user's profile into `<scratch>/pw-profile`, runs the browser
  there with sync/extensions off, and `stop` deletes the copy. Tell the user which browser/profile
  is used. List profiles: `browser.sh profiles <browser>`. If the app still shows a login page,
  fall back to manual login in that window.
- `manual`: `browser.sh start "<url>" "<scratch>" <port>` (Windows: `browser.ps1`). Tell the user
  to log in in that window and reply when the home screen shows; wait for the reply, do not poll.
- `storage-state`: use the stored Playwright state path from the config; never read its content.

Never type credentials, never script a login form, never read/print/export cookies or tokens.
Run `frontend.post_login_steps` (for example click "I Agree") whenever the notice is visible, again
after every `page.reload()`. Scenarios `require` `scripts/frontend/lib.js` (`APP_HOST` = host:port,
`QA_SCRATCH` = the scratch dir); `run(fn)` attaches to the existing tab (session storage is per tab) and exits
without `browser.close()`. A scenario that lands on a login page -> stop and ask the user to log in
again. After the last scenario: `browser.sh stop "<scratch>"`.

Parallel runs (other projects, other git worktrees of this one) may be active. `<port>` is only the
first port tried: when it is taken, `browser.sh` uses the next free one and prints it and writes it
to `<scratch>/cdp.port`, which `lib.js` reads through `QA_SCRATCH`. Never pass a fixed `CDP_PORT`
and never kill browsers or node processes yourself: `browser.sh stop "<scratch>"` stops only this
run's browser and recorder.

## 4. Execution patterns

- **Network log across scripts:** start `scripts/frontend/recorder.js <scratch>/net.jsonl` in the
  background with `URL_FILTER=<api path fragment>` and `QA_SCRATCH=<scratch>` (Git Bash: prefix
  `MSYS_NO_PATHCONV=1` and pass a Windows-style log path). Keep the log inside the scratch dir: the
  recorder writes `recorder.pid` next to it, which is how `stop` finds it. Each scenario reads lines
  newer than its own start time.
- **Failure injection:** to test a failed request, `page.route(pattern, r => r.fulfill({status: 500, ...}))`
  then `page.unroute`. It affects that tab only and touches no backend or data. State it in the
  report. The same applies to mocking a missing endpoint: it checks the UI path only, the backend
  criterion stays NOT COVERED/PENDING.
- **Real call without a mock** when the backend exists: capture the actual status and body with
  `waitForRequest/Response`; that is the evidence.
- **Feature flag off:** follow `frontend.feature_flags.how_to_toggle`. Overrides are local to the
  test browser, are stated in the report, and are never committed.
- **Modal guard:** after each step, check the parent modal is still visible before asserting.
- **Extensions:** `extensions[]` lists project helper scripts (for example a column-filter driver):
  use them instead of rewriting the same driver.

Common pitfalls: Escape closes the top panel, a second Escape closes the parent modal (never loop
it); toasts/banners can cover controls (dismiss first); success/error messages may be blocking
dialogs with an OK button (the page is inert behind them); date pickers have hidden out-of-view
cells (target in-view ones); filter lists can repeat selected values (act on the full list); empty
states hide the table and its header controls; virtualized tables render only visible rows, so
count rows through the app's own counter or by scrolling.

## 5. Scenarios

Always design the set with `scenario-design.md` (no AC, bug reports, risk cap, test charter); the notes below add the frontend specifics.

One scenario per criterion and per edge case: label, steps (navigate, interact, assert), assertion
matching exactly what the criterion says. State/text/data -> deterministic assertion. Visual/layout
(spacing, alignment, "looks like the mock") -> also a screenshot and PENDING - visual review; measure
what you can (sizes, alignment) and report the numbers. Check no layout jump between states when
the task asks for it. Screenshots are named `NN-slug.png` (00 = before any action).

## 6. Writes need a persistence check

A scenario that submits, saves or deletes is not proven by a success toast or optimistic UI. Reload
or navigate to where the data shows and assert it; if the frontend cannot show it, ask the user
whether to cross-check through the backend (`references/backend.md`) or mark it NOT COVERED.
Respect `environments.<env>.mutation`.
