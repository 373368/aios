"""Combine light batch files into single digest for agent consumption."""
import sys, json, re, os
sys.stdout.reconfigure(encoding='utf-8')

BATCH_IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 0

batches = json.load(open(r'C:\Users\asus\AppData\Local\Temp\opencode\light_batches.json', encoding='utf-8'))
batch = batches[BATCH_IDX]

out = [f'# Batch {BATCH_IDX} — {len(batch)} conversations\n']

for i, f in enumerate(batch):
    raw = open(f['path'], encoding='utf-8').read()
    # Extract just frontmatter keys we need
    fm = {}
    m = re.match(r'^---\n(.*?)\n---', raw, re.S)
    if m:
        for line in m.group(1).strip().split('\n'):
            kv = line.split(':', 1)
            if len(kv) == 2:
                fm[kv[0].strip()] = kv[1].strip()
    title = fm.get('title', os.path.basename(f['path']))[:80]
    cid = fm.get('conversation_id', '?')
    platform = fm.get('platform', '') or f['platform']
    
    # Strip frontmatter, keep body
    body = re.sub(r'^---\n.*?\n---\n*', '', raw, flags=re.S).strip()
    # Truncate to 800 chars max
    body = body[:800]
    
    out.append(f'## [{i:03d}] {title}')
    out.append(f'  platform={platform} cid={cid}')
    out.append(f'  {body}')
    out.append('')

digest_path = fr'C:\Users\asus\AppData\Local\Temp\opencode\batch_{BATCH_IDX}_digest.md'
with open(digest_path, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(out))

sz = os.path.getsize(digest_path)
print(f'wrote {digest_path} ({sz} bytes, {len(out)} lines)')
