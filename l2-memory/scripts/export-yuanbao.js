const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const PROFILE = "D:\\AI OS\\l3-tools\\pw-profile";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT_DIR = "D:\\AI OS\\l2-memory\\export\\元宝";
const AGENT_ID = "naQivTmsDa";
const CONCURRENCY = 5;

function sanitize(s) {
  return String(s || '').replace(/[\\/:*?"<>|\r\n]+/g, '_').replace(/\s+/g, ' ').trim().slice(0, 80) || '(无标题)';
}

async function collectAllSessions(page) {
  await page.goto('https://yuanbao.tencent.com/chat', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('.yb-recent-conv-list__item', { timeout: 20000 });
  await page.waitForTimeout(2000);
  return await page.evaluate(async () => {
    const nav = document.querySelector('.yb-nav__content');
    if (nav) {
      let before = nav.scrollHeight, stuck = 0;
      for (let i = 0; i < 120; i++) {
        nav.scrollTop = nav.scrollHeight;
        await new Promise(r => setTimeout(r, 250));
        const now = nav.scrollHeight;
        if (now === before) stuck++; else stuck = 0;
        before = now;
        if (stuck >= 6) break;
      }
    }
    const items = document.querySelectorAll('.yb-recent-conv-list__item');
    const seen = new Map();
    for (const it of items) {
      const key = Object.keys(it).find(k => k.startsWith('__reactFiber'));
      if (!key) continue;
      let f = it[key];
      for (let i = 0; i < 15 && f; i++) {
        const p = f.memoizedProps;
        if (p && p.item && typeof p.item === 'object' && p.item.id) {
          seen.set(p.item.id, { id: p.item.id, title: p.item.title || (it.innerText||'').trim() });
          break;
        }
        f = f.return;
      }
    }
    return [...seen.values()];
  });
}

async function extract(page, s) {
  const url = `https://yuanbao.tencent.com/chat/${AGENT_ID}/${s.id}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('.agent-chat__list', { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(2500);
  // scroll chat container to top repeatedly to load older messages (virtual list)
  for (let i = 0; i < 30; i++) {
    await page.evaluate(() => {
      const el = document.querySelector('.agent-chat__list__content-wrapper') || document.querySelector('[class*="agent-chat__list"]');
      if (el) el.scrollTop = 0;
    });
    await page.waitForTimeout(400);
  }
  await page.waitForTimeout(1500);
  const data = await page.evaluate(() => {
    const items = document.querySelectorAll('.agent-chat__list__item');
    const msgs = [];
    for (const it of items) {
      const cls = (it.className||'').toString();
      const txt = (it.innerText || '').trim();
      if (!txt) continue;
      const isHuman = cls.includes('--human');
      msgs.push({ role: isHuman ? 'user' : 'assistant', text: txt });
    }
    return { msgs };
  });
  const md = [
    '---',
    `title: ${s.title}`,
    `source: yuanbao`,
    `conversation_id: ${s.id}`,
    `exported_at: ${new Date().toISOString()}`,
    '---',
    ''
  ];
  for (const m of data.msgs) {
    md.push(m.role === 'user' ? '## 👤 User' : '## 🤖 Assistant');
    md.push('');
    md.push(m.text);
    md.push('');
  }
  const file = path.join(OUT_DIR, `${s.id}-${sanitize(s.title)}.md`);
  fs.writeFileSync(file, md.join('\n'), 'utf8');
  return { id: s.id, title: s.title, msgs: data.msgs.length, ok: true };
}

async function runPool(pages, tasks, results) {
  let next = 0;
  async function worker(pg) {
    while (true) {
      const idx = next++;
      if (idx >= tasks.length) return;
      const s = tasks[idx];
      try {
        const r = await extract(pg, s);
        results.push(r);
        console.log(`OK ${s.title} (${r.msgs} msgs)`);
      } catch (e) {
        results.push({ id: s.id, title: s.title, ok: false, error: e.message });
        console.log(`FAIL ${s.title}: ${e.message}`);
      }
    }
  }
  await Promise.all(pages.map(worker));
}

(async () => {
  const browser = await chromium.launchPersistentContext(PROFILE, {
    executablePath: EDGE, headless: false, viewport: { width: 1400, height: 900 }
  });
  const page0 = browser.pages()[0] || await browser.newPage();
  fs.mkdirSync(OUT_DIR, { recursive: true });

  console.log('collecting all sessions...');
  const sessions = await collectAllSessions(page0);
  console.log(`found ${sessions.length} sessions`);

  const existing = new Set();
  if (fs.existsSync(OUT_DIR)) {
    for (const f of fs.readdirSync(OUT_DIR)) {
      try {
        const head = fs.readFileSync(path.join(OUT_DIR, f), 'utf8').slice(0, 300);
        const m = head.match(/conversation_id:\s*(\S+)/);
        if (m) existing.add(m[1].trim());
      } catch (_) {}
    }
  }
  const todo = sessions.filter(s => !existing.has(s.id));
  console.log(`already exported: ${existing.size}, to do: ${todo.length}, concurrency: ${CONCURRENCY}`);

  const pages = [page0];
  for (let i = 1; i < CONCURRENCY; i++) {
    const p = await browser.newPage();
    await p.goto('about:blank');
    pages.push(p);
  }

  const results = [];
  const t0 = Date.now();
  await runPool(pages, todo, results);
  const secs = Math.round((Date.now() - t0) / 1000);
  await browser.close();

  const ok = results.filter(r => r.ok).length;
  const totalFiles = fs.readdirSync(OUT_DIR).length;
  console.log(`\nDONE: ${ok}/${results.length} in ${secs}s. Total files: ${totalFiles}`);
  const fails = results.filter(r => !r.ok);
  if (fails.length) {
    console.log('Failures:');
    for (const f of fails.slice(0, 20)) console.log(`  ✗ ${f.title}: ${f.error}`);
  }
})().catch(e => { console.error('FATAL:', e); process.exit(1); });