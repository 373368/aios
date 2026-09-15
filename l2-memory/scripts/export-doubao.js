const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const PROFILE = "D:\\AI OS\\l3-tools\\pw-profile";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT_DIR = "D:\\AI OS\\l2-memory\\export\\豆包";
const CONCURRENCY = 5;

function sanitize(s) {
  return String(s || '').replace(/[\\/:*?"<>|\r\n]+/g, '_').replace(/\s+/g, ' ').trim().slice(0, 80) || '(无标题)';
}

async function collectAllSessions(page) {
  await page.goto('https://www.doubao.com/chat/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('nav a[href*="/chat/"]', { timeout: 20000 });
  await page.waitForTimeout(1500);
  return await page.evaluate(async () => {
    const findScroller = () => {
      const nav = document.querySelector('nav');
      if (!nav) return null;
      const all = nav.querySelectorAll('*');
      for (const el of all) {
        const st = getComputedStyle(el);
        if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight) return el;
      }
      return null;
    };
    const scroller = findScroller();
    if (!scroller) return [];
    let before = scroller.scrollHeight;
    let stuck = 0;
    for (let i = 0; i < 80; i++) {
      scroller.scrollTop = scroller.scrollHeight;
      await new Promise(r => setTimeout(r, 400));
      const now = scroller.scrollHeight;
      if (now === before) stuck++;
      else stuck = 0;
      before = now;
      if (stuck >= 5) break;
    }
    const seen = new Map();
    const links = document.querySelectorAll('nav a[href*="/chat/"]');
    for (const a of links) {
      const href = a.getAttribute('href') || '';
      const id = href.replace('/chat/', '').trim();
      const title = (a.innerText || '').trim().split('\n')[0];
      if (/^\d+$/.test(id) && title && title !== '豆包' && title !== '新对话') {
        if (!seen.has(id)) seen.set(id, { id, title });
      }
    }
    return [...seen.values()];
  });
}

async function extract(page, s) {
  await page.goto('https://www.doubao.com/chat/' + s.id, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('[class*="message-list"]', { timeout: 20000 }).catch(() => {});
  for (let i = 0; i < 20; i++) {
    await page.evaluate(() => {
      const el = document.querySelector('[class*="scroller"]') || document.querySelector('[class*="message-list"]');
      if (el) el.scrollTop = el.scrollHeight;
    });
    await page.waitForTimeout(250);
  }
  await page.waitForTimeout(1200);
  const data = await page.evaluate(() => {
    const list = document.querySelector('[class*="message-list"]');
    if (!list) return { msgs: [], error: 'no message-list' };
    const rows = list.querySelectorAll('.v_list_row');
    const msgs = [];
    for (const r of rows) {
      const txt = (r.innerText || '').trim();
      if (!txt) continue;
      if (txt === '聊聊新话题') continue;
      if (txt.startsWith('资讯：') && txt.length < 150) continue;
      const isUser = !!r.querySelector('[class*="bg-g-send-msg-bubble-bg"]');
      msgs.push({ role: isUser ? 'user' : 'assistant', text: txt });
    }
    return { msgs };
  });
  const md = [
    '---',
    `title: ${s.title}`,
    `source: doubao`,
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
  return { id: s.id, title: s.title, msgs: data.msgs.length, file, ok: true, error: data.error || null };
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
    executablePath: EDGE,
    headless: false,
    viewport: { width: 1400, height: 900 }
  });
  const page0 = browser.pages()[0] || await browser.newPage();
  fs.mkdirSync(OUT_DIR, { recursive: true });

  console.log('collecting all sessions...');
  const sessions = await collectAllSessions(page0);
  console.log(`found ${sessions.length} sessions total`);

  const existing = new Set();
  for (const f of fs.readdirSync(OUT_DIR)) {
    const m = f.match(/^(\d+)-/);
    if (m) existing.add(m[1]);
  }
  const todo = sessions.filter(s => !existing.has(s.id));
  console.log(`already exported: ${existing.size}, to do: ${todo.length}, concurrency: ${CONCURRENCY}`);

  // open additional tabs
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
  console.log(`\nDONE: ${ok}/${results.length} new in ${secs}s. Total files: ${totalFiles}`);
  const fails = results.filter(r => !r.ok);
  if (fails.length) {
    console.log('Failures:');
    for (const f of fails) console.log(`  ✗ ${f.title}: ${f.error}`);
  }
})().catch(e => { console.error('FATAL:', e); process.exit(1); });