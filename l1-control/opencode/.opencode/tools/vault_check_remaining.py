import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'
EXPORTS = [r'D:\AI OS\l2-memory\export\豆包', r'D:\AI OS\l2-memory\export\元宝', r'D:\AI OS\l2-memory\export\DeepSeek']

done = set()
for root, dirs, files in os.walk(VAULT):
    for fn in files:
        if not fn.endswith('.md') or fn == '00-骨架.md':
            continue
        txt = open(os.path.join(root, fn), encoding='utf-8').read()
        for m in re.finditer(r'^conversation_id:\s*(\S+)', txt, re.M):
            done.add(m.group(1))

rem_files = []
for d in EXPORTS:
    plat = os.path.basename(d)
    for fn in os.listdir(d):
        if not fn.endswith('.md'):
            continue
        p = os.path.join(d, fn)
        raw = open(p, encoding='utf-8', errors='replace').read()
        m = re.search(r'^conversation_id:\s*(\S+)', raw, re.M)
        cid = m.group(1).strip() if m else fn
        if cid in done:
            continue
        title = ''
        mt = re.search(r'^title:\s*(.*)$', raw, re.M)
        if mt:
            title = mt.group(1).strip()
        if not title:
            title = fn[:50]
        body = re.sub(r'^---\n.*?\n---\n*', '', raw, flags=re.S)
        has_content = len(body.strip()) > 100 and '\u5df2\u89e3\u7b54' not in body[:50]
        damaged = '\ufffd' in raw[:500]
        rem_files.append((plat, title[:40], len(raw)//1024, has_content, damaged, fn[:30]))

empty = [x for x in rem_files if not x[3]]
damaged = [x for x in rem_files if x[4]]
valid = [x for x in rem_files if x[3] and not x[4]]

print('total remaining:', len(rem_files))
print('  empty (photo qa etc):', len(empty))
print('  encoding damaged:', len(damaged))
print('  has content:', len(valid))

if valid:
    print('\nvaluable files (%d):' % len(valid))
    for plat, title, sz, _, _, fn in valid[:25]:
        print('  [%s] %s (%dKB) %s' % (plat, title, sz, fn))
    if len(valid) > 25:
        print('  ... and %d more' % (len(valid) - 25))

print('\ntotal vault pages:', len(done))
print('coverage: %d / 583 = %.0f%%' % (len(done), 100*len(done)/583))