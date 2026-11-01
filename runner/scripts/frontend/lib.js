// Attach to the manually logged-in browser over CDP (see references/frontend.md step 3).
// Run with NODE_PATH="$(npm root -g)" so the global playwright install resolves.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

// CDP_PORT wins; else the port browser.sh wrote to $QA_SCRATCH/cdp.port (it may have moved off the
// requested port because another run already used it); else 9222.
function cdpPort() {
  if (process.env.CDP_PORT) return process.env.CDP_PORT;
  const scratch = process.env.QA_SCRATCH;
  if (scratch) {
    try {
      return fs.readFileSync(path.join(scratch, 'cdp.port'), 'utf8').trim();
    } catch {
      throw new Error(`no cdp.port in ${scratch}: start the browser with browser.sh first`);
    }
  }
  return 9222;
}

const PORT = cdpPort();
const HOST = process.env.APP_HOST;
if (!HOST) throw new Error('APP_HOST is not set (host of the chosen environment)');

async function attach() {
  const browser = await chromium.connectOverCDP(`http://localhost:${PORT}`, { timeout: 15000 });
  const page = browser.contexts()[0].pages().find((p) => p.url().includes(HOST));
  if (!page) throw new Error(`no tab open on ${HOST}`);
  return { browser, page };
}

// Never call browser.close() on a CDP connection: it can close the user's window.
function run(fn) {
  (async () => {
    const { page } = await attach();
    await fn(page);
    process.exit(0);
  })().catch((e) => {
    console.log('ERR', e.message.split('\n').slice(0, 12).join(' | '));
    process.exit(1);
  });
}

module.exports = { attach, run };
