import sys, json
sys.stdout.reconfigure(encoding='utf-8')

remaining = json.load(open(r'C:\Users\asus\AppData\Local\Temp\opencode\remaining.json', encoding='utf-8'))
# sort ascending so biggest file gets paired with others
remaining.sort(key=lambda x: x['size'])

N = 24
groups = [[] for _ in range(N)]
sizes = [0] * N
for r in remaining:
    i = sizes.index(min(sizes))
    groups[i].append(r)
    sizes[i] += r['size']

for i, g in enumerate(groups):
    print(f'agent {i}: {len(g)} files, {sum(x["size"] for x in g)//1024} KB')
    for x in g[:1]:
        print(f'  首: {x["platform"]} {x["title"][:50]} ({x["size"]//1024}KB)')

manifest = {f'agent_{i}': [x['path'] for x in g] for i, g in enumerate(groups)}
with open(r'C:\Users\asus\AppData\Local\Temp\opencode\batch_24.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False)
print('\nsaved batch_24.json')