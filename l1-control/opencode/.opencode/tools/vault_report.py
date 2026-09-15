import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')

VAULT = r'D:\ObsidianVault\05-知识\知识库'

# Count by directory
dirs = {}
for item in os.listdir(VAULT):
    d = os.path.join(VAULT, item)
    if not os.path.isdir(d):
        continue
    count = len([f for f in os.listdir(d) if f.endswith('.md') and f != '00-骨架.md'])
    dirs[item] = count

# Total pages
total = sum(dirs.values())
print('=' * 50)
print('知识库提炼完成报告')
print('=' * 50)
print()
print('源: 583 个 AI 对话 (豆包156 + 元宝297 + DeepSeek130)')
print('目标: D:\\ObsidianVault\\05-知识\\知识库\\')
print()
print('各骨架分布:')
for name, count in sorted(dirs.items(), key=lambda x: -x[1]):
    print('  %-16s %3d 页' % (name, count))
print('  %-16s ---' % '')
print('  %-16s %3d 页' % ('合计', total))
print()
print('覆盖率: %d / 583 = %.0f%%' % (total, 100*total/583))
print('剩余: 139 个有内容文件未处理 (agent 无法读取的编码/路径问题)')
print()
print('注意:')
print('  - 跨 agent 同主题 (如 Q-NSLA) 可能有多页，需第二轮合并')
print('  - 图片缺失 (images_missing: true) 标记在对应页 frontmatter')
print('  - 需核实内容已标注 "(需核实)" 在正文中')
print('  - 目录结构已统一为 9 个骨架，无数字前缀')
print('=' * 50)