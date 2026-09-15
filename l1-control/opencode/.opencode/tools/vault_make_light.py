import os, re, sys, shutil, json
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'
EXPORTS = [r'D:\AI OS\l2-memory\export\豆包', r'D:\AI OS\l2-memory\export\元宝', r'D:\AI OS\l2-memory\export\DeepSeek']
LIGHT = r'D:\AI OS\l2-memory\light'

# collect conversation_ids already distilled into vault pages
done_ids = set()
for root, dirs, files in os.walk(VAULT):
    for f in files:
        if not f.endswith('.md') or f == '00-骨架.md':
            continue
        txt = open(os.path.join(root, f), encoding='utf-8').read()
        for m in re.finditer(r'^conversation_id:\s*(\S+)', txt, re.M):
            done_ids.add(m.group(1).strip())

# find remaining export files
remaining = []  # {path, platform, cid, size}
for d in EXPORTS:
    platform = os.path.basename(d)
    for f in os.listdir(d):
        if not f.endswith('.md'):
            continue
        p = os.path.join(d, f)
        raw = open(p, encoding='utf-8').read()
        m = re.search(r'^conversation_id:\s*(\S+)', raw, re.M)
        cid = m.group(1).strip() if m else f
        if cid in done_ids:
            continue
        remaining.append({'platform': platform, 'cid': cid, 'path': p, 'size': os.path.getsize(p), 'title': (re.search(r'^title:\s*(.*)$', raw, re.M) or [None, os.path.basename(p)[:60]])[1].strip()})

print(f'done ids in vault: {len(done_ids)}')
print(f'remaining export files: {len(remaining)}  total {round(sum(r["size"] for r in remaining)/1024/1024,1)} MB')

# build light copies: strip thinking blocks, truncate assistant answers to 1500 chars
def strip_and_trim(raw, max_ans=1500):
    # split into sections by ## 👤 User / ## 🤖 Assistant
    parts = re.split(r'(?m)^## (?=[^#])', raw)
    out = []
    for seg in parts:
        seg = seg.strip()
        if not seg:
            continue
        if seg.startswith('👤'):
            out.append('## ' + seg)
            continue
        if seg.startswith('🤖'):
            # strip 思考 block: DeepSeek format '> 💭 思考过程' ... blockquote; 元宝 '已深度思考(...)'
            body = seg
            body = re.sub(r'> 💭 思考过程.*?(?=\n## |\Z)', '> [思考已省略]\n', body, flags=re.S)
            body = re.sub(r'已深度思考\(用时.*?\)\n+', '[思考已省略]\n', body)
            body = re.sub(r'>\s*.*?(?:\n>\s*)*\n+(?=\S)', '', body, flags=re.S)  # drop blockquote leftovers
            body = body[:max_ans]
            out.append('## ' + body)
            continue
        # header sections (frontmatter etc.)
        if seg.startswith('---'):
            out.append(seg)
        else:
            out.append(seg)
    return '\n\n'.join(out)

light_count = 0
for r in remaining:
    raw = open(r['path'], encoding='utf-8').read()
    light = strip_and_trim(raw)
    pdir = os.path.join(LIGHT, r['platform'])
    os.makedirs(pdir, exist_ok=True)
    fn = os.path.join(pdir, os.path.basename(r['path']))
    with open(fn, 'w', encoding='utf-8') as f:
        f.write(light)
    light_count += 1

print(f'light copies written: {light_count}')

# write remaining manifest
with open(r'C:\Users\asus\AppData\Local\Temp\opencode\remaining.json', 'w', encoding='utf-8') as f:
    json.dump(remaining, f, ensure_ascii=False)
print('saved remaining.json')