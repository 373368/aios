import sys, os, re, shutil, json
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'
EXPORTS = [r'D:\AI OS\l2-memory\export\豆包', r'D:\AI OS\l2-memory\export\元宝', r'D:\AI OS\l2-memory\export\DeepSeek']
TEMP = r'C:\Users\asus\AppData\Local\Temp\opencode\remaining_clean'

# Already covered IDs
done = set()
for root, dirs, files in os.walk(VAULT):
    for fn in files:
        if not fn.endswith('.md') or fn == '00-骨架.md':
            continue
        txt = open(os.path.join(root, fn), encoding='utf-8').read()
        for m in re.finditer(r'^conversation_id:\s*(\S+)', txt, re.M):
            done.add(m.group(1))

# Collect remaining files with content
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
        body = re.sub(r'^---\n.*?\n---\n*', '', raw, flags=re.S)
        if len(body.strip()) < 100 or '已解答' in body[:50]:
            continue
        # Check for encoding damage
        if '\ufffd' in raw[:500]:
            continue
        rem_files.append((plat, fn, cid, p, os.path.getsize(p)))

# Clean and copy
if os.path.exists(TEMP):
    shutil.rmtree(TEMP)
os.makedirs(TEMP)

manifest = []
for plat, fn, cid, src, sz in rem_files:
    safe_name = cid + '.md'
    dest = os.path.join(TEMP, safe_name)
    shutil.copy2(src, dest)
    manifest.append({'platform': plat, 'cid': cid, 'path': dest, 'size': sz, 'title': fn[:60]})

# Split into batches for agents
manifest.sort(key=lambda x: x['size'])
N = 4  # 4 agents
groups = [[] for _ in range(N)]
sizes = [0] * N
for r in manifest:
    i = sizes.index(min(sizes))
    groups[i].append(r)
    sizes[i] += r['size']

for i, g in enumerate(groups):
    print(f'agent_{i}: {len(g)} files, {sum(x["size"] for x in g)//1024} KB')
    for x in g[:2]:
        print(f'  {x["platform"]} {x["title"][:40]} ({x["size"]//1024}KB)')

# Save manifest
m = {}
for i, g in enumerate(groups):
    m[f'agent_{i}'] = [{'path': x['path'], 'platform': x['platform'], 'cid': x['cid'], 'title': x['title']} for x in g]

with open(r'C:\Users\asus\AppData\Local\Temp\opencode\remaining_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(m, f, ensure_ascii=False)

print(f'\ncopied {len(manifest)} files to {TEMP}')
print(f'skipped (empty/damaged): {139 - len(manifest)}')