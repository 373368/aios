import os, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')
BASE = r'D:\ObsidianVault\05-知识\知识库'

CROSS = [
    ('AI与机器学习', '物理', ['五维超光速量子', '非保守场']),
    ('AI与机器学习', '编程开发', ['AscendC_BF16', 'Keras模型可视化', 'TensorFlow时序']),
    ('物理', 'AI与机器学习', ['数学主义智能']),
    ('编程开发', 'AI与机器学习', ['ARC任务数据处理', 'ARC数据集加载']),
]

for src_cat, dst_cat, kws in CROSS:
    other_dir = os.path.join(BASE, src_cat, '其他')
    if not os.path.isdir(other_dir):
        continue
    for fn in list(os.listdir(other_dir)):
        if not fn.endswith('.md'):
            continue
        name = fn[:-3]
        for kw in kws:
            if kw.lower() in name.lower():
                src = os.path.join(other_dir, fn)
                dst = os.path.join(BASE, dst_cat, fn)
                if os.path.exists(src) and not os.path.exists(dst):
                    os.makedirs(os.path.join(BASE, dst_cat), exist_ok=True)
                    shutil.move(src, dst)
                    print(f'cross: {src_cat}/其他/{fn} -> {dst_cat}/')
                break

TARGET = {
    'AI与机器学习': [
        ('评估与指标', ['ARC-AGI-2', '测试', '评估']),
        ('模型架构', ['ARC抽象', 'ARC变换', 'ARC图对', 'ARC不变量', 'ARC任务', '神经网络动态', '神经网络门控', '深度学习模型结构', 'Koopman']),
        ('AI应用', ['ARC', 'CCGbank', '组合范畴语法', 'Google生成式', 'Kaggle', '低维语义', '模型规模', '长序列', '大模型与编程', '计算智能', '超图与DGL', 'AI工具对比', 'Lorenz系统', 'VitalyVanchurin', '数智论', '高维表征', '量子递归', '统一前向', '深度学习模型']),
        ('训练与优化', ['一维线性判别', '局部一致性', '局部学习', '掩码传播']),
    ],
    '编程开发': [
        ('框架与库使用', ['AscendC', 'KaggleNotebook', 'OpenEuler', 'AI编码Agent', 'NLP文本']),
        ('代码片段与算法实现', ['复合变换', '图像分类不平衡']),
        ('软件工程', ['测试计划', '等价类划分', '软件测试', '软件项目', '黑盒白盒']),
        ('硬件与嵌入式', ['IoT', 'WeMos', 'MQTT']),
    ],
    '计算机基础': [
        ('硬件与嵌入式', ['位运算']),
        ('软件工程', ['AI聊天数据']),
    ],
}

for cat, sub_targets in TARGET.items():
    other_dir = os.path.join(BASE, cat, '其他')
    if not os.path.isdir(other_dir):
        continue
    for fn in list(os.listdir(other_dir)):
        if not fn.endswith('.md'):
            continue
        name = fn[:-3]
        for sub_name, kws in sub_targets:
            for kw in kws:
                if kw.lower() in name.lower():
                    target_dir = os.path.join(BASE, cat, sub_name)
                    os.makedirs(target_dir, exist_ok=True)
                    src = os.path.join(other_dir, fn)
                    dst = os.path.join(target_dir, fn)
                    if os.path.exists(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        print(f'{cat}/其他/{fn} -> {sub_name}/')
                    break
            else:
                continue
            break

print('\nDone. Checking remaining "其他" directories:')
for cat in ['AI与机器学习', '编程开发', '数学', '计算机基础', '物理']:
    d = os.path.join(BASE, cat, '其他')
    if os.path.isdir(d):
        n = len([f for f in os.listdir(d) if f.endswith('.md')])
        print(f'  {cat}/其他: {n}')
