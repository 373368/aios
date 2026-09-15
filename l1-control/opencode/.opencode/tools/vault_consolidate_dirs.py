"""Consolidate pages written to wrong directories into canonical dirs."""
import os, re, shutil, json
import sys
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'
CANONICAL = ['编程开发','AI与机器学习','数学','计算机基础','物理','医疗健康','生活常识','学习考试','娱乐与文化']

# Map wrong dir prefixes to canonical
PREFIX_MAP = {
    '01-': '编程开发',
    '02-': 'AI与机器学习', 
    '03-': '数学',
    '04-': '计算机基础',
    '05-': '物理',
    '06-': '医疗健康',
    '07-': '生活常识',
    '08-': '学习考试',
    '09-': '娱乐与文化',
    '1-': '编程开发',
    '2-': 'AI与机器学习',
    '3-': '数学',
    '4-': '计算机基础',
    '5-': '物理',
    '6-': '医疗健康',
    '7-': '生活常识',
    '8-': '学习考试',
    '9-': '娱乐与文化',
}

# Collect pages in wrong dirs
wrong_pages = []
for item in os.listdir(VAULT):
    item_path = os.path.join(VAULT, item)
    if not os.path.isdir(item_path):
        continue
    if item in CANONICAL:
        continue
    # This is a wrong dir (has number prefix or subdir)
    # Determine target
    target = None
    for prefix, canon in PREFIX_MAP.items():
        if item.startswith(prefix) or item == prefix.rstrip('-'):
            target = canon
            break
    
    if not target:
        # Check if it's a subdir like "01-编程开发/框架与库使用"
        print(f'UNKNOWN wrong dir: {item}')
        continue
    
    # Scan files in this wrong dir (and any subdirs)
    for root, dirs, files in os.walk(item_path):
        for fn in files:
            if not fn.endswith('.md') or fn == '00-骨架.md':
                continue
            src = os.path.join(root, fn)
            dest = os.path.join(VAULT, target, fn)
            wrong_pages.append((src, dest, target, fn))
            print(f'  {src[len(VAULT)+1:]} -> {target}/{fn}')

# Move files, merge if exists
moved = 0
merged = 0
for src, dest, target, fn in sorted(wrong_pages):
    if os.path.exists(dest):
        # Merge: append content from src into dest
        with open(src, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(dest, 'r', encoding='utf-8') as f:
            existing = f.read()
        # Strip frontmatter from src
        body = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.S)
        # Add as merge section
        with open(dest, 'a', encoding='utf-8') as f:
            f.write(f'\n\n## 合并补充\n{body}\n')
        merged += 1
        print(f'  MERGED {fn} into existing')
    else:
        shutil.move(src, dest)
        moved += 1

# Clean up empty wrong dirs
for item in os.listdir(VAULT):
    item_path = os.path.join(VAULT, item)
    if not os.path.isdir(item_path) or item in CANONICAL:
        continue
    # Remove empty directories (including subdirs)
    for root, dirs, files in os.walk(item_path, topdown=False):
        if not files and not dirs:
            os.rmdir(root)
            print(f'  REMOVED empty dir: {root[len(VAULT)+1:]}')
    # Remove top-level wrong dir if empty
    if os.path.exists(item_path) and not os.listdir(item_path):
        os.rmdir(item_path)
        print(f'  REMOVED empty dir: {item}')

print(f'\nDone: {moved} moved, {merged} merged')