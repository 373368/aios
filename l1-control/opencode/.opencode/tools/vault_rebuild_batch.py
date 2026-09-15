import os, re, json, sys
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'
EXPORTS = [r'D:\AI OS\l2-memory\export\豆包', r'D:\AI OS\l2-memory\export\元宝', r'D:\AI OS\l2-memory\export\DeepSeek']

# Already covered IDs
done = set()
for root, dirs, files in os.walk(VAULT):
    for fn in files:
        if not fn.endswith('.md') or fn == '00-骨架.md': continue
        txt = open(os.path.join(root, fn), encoding='utf-8').read()
        for m in re.finditer(r'^conversation_id:\s*(\S+)', txt, re.M):
            done.add(m.group(1))

# Remaining files
rem = []
for d in EXPORTS:
    plat = os.path.basename(d)
    for fn in os.listdir(d):
        if not fn.endswith('.md'): continue
        p = os.path.join(d, fn)
        raw = open(p, encoding='utf-8').read()
        m = re.search(r'^conversation_id:\s*(\S+)', raw, re.M)
        cid = m.group(1).strip() if m else fn
        if cid in done: continue
        title = (re.search(r'^title:\s*(.*)$', raw, re.M) or [None, fn[:50]])[1].strip()
        rem.append({'platform': plat, 'cid': cid, 'path': p, 'size': os.path.getsize(p), 'title': title})

rem.sort(key=lambda x: x['size'])
N = 20  # remaining agents 4-23
groups = [[] for _ in range(N)]
sizes = [0]*N
for r in rem:
    i = sizes.index(min(sizes))
    groups[i].append(r)
    sizes[i] += r['size']

print(f'vault pages: {len(done)} done ids')
print(f'remaining files: {len(rem)}  total {sum(r["size"] for r in rem)//1024} KB')
for i, g in enumerate(groups):
    print(f'  agent {4+i}: {len(g)} files, {sum(x["size"] for x in g)//1024} KB')

manifest = {}
for i, g in enumerate(groups):
    manifest[f'agent_{4+i}'] = [x['path'] for x in g]
with open(r'C:\Users\asus\AppData\Local\Temp\opencode\batch_next.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False)
print('saved batch_next.json')