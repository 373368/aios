import os, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')
BASE = r'D:\ObsidianVault\05-知识\知识库'

# Additional keywords for "其他" files only
EXTRA = {
    'AI与机器学习': {
        '模型架构': ['GARS', 'Q-NSLA', 'QNSLA', 'RBF网络', 'PIN神经', 'TCN', 'Conv2D', 'MLP', 'LVM', 'DLGDL', 'CUV', 'Transformer', '编码器', '解码器'],
        '训练与优化': ['FocalLoss', '训练损失', '损失函数', '损失卡高', '损失序列化', '多损失', '损失', 'MAML', '元学习', '梯度累积', '优化', '正则化', '归一化'],
        '深度学习理论': ['等变神经网络', '对偶性', '流形', '纤维丛', '认知边界', '量子认知', '智能本质', '纠缠', '变分原理', '神经ODE', '表示论', '拓扑', '代数', '几何'],
        '数据集与预处理': ['数据集', '预处理', 'TFRecord', '特征提取', '数据增强', '采样', '管道', 'HuggingFace', '加载'],
        '评估与指标': ['基准', '测试', '评估', 'AUC', 'GLUE', '指标', 'Benchmark', '输出维度', '显存估算'],
        'AI应用': ['LLM', 'NLP', '音频', '视觉', '多模态', '消防隐患', '推荐', 'Agent', '认知', '思维链', 'CoT', '对比学习', '群体智能', '分类', '预测', '识别', '检测', '朴素贝叶斯', '模式识别'],
    },
    '编程开发': {
        '框架与库使用': ['TFRecord', 'TF数据', 'TF分布式', 'TF数值', 'TF动态', 'tf.gather', '分布式训练', 'Faiss', 'HuggingFace', 'SHAP', 'SSM', 'MultiLabel', 'OmniRoute', 'Ubuntu'],
        '调试与错误排查': ['NaN', 'Inf', '调试', '排查', '卡死', '崩溃', '错误', '修复', '解决'],
        '构建与部署': ['部署', '构建', 'Docker', 'pip', '打包', '配置', '环境', 'CI', 'PR'],
        '代码片段与算法实现': ['算法', '实现', 'Haversine', '多表合并', '预测', '蒙特卡洛', 'SHAP', '批量处理'],
        '语言与语法': ['Python', 'Java', 'C++', '汇编', 'Vue', 'JS'],
    },
    '数学': {
        '群论与几何': ['Banach', 'Iwasawa', 'p-adic', '克利福德', '嘉当', '扭李超', '李括号', '李雅普诺夫', '非交换几何', '超图代数', '规范场', '哥德尔', '无限生成元'],
        '基础数学': ['命题逻辑', '数学与其他学科', '数学描述', '频率', '周期'],
        '高等数学': ['波函数五维', '离散网格规范场', '规范场公式'],
        '数论与猜想': ['p-adic', '数论'],
        '概率统计': ['概率', '统计', '分布'],
    },
    '计算机基础': {
        '网络': ['CIDR', '子网掩码', '半双工', '全双工', 'GLUE指标'],
        '操作系统': ['MSI', 'WPS', '模4补码', '溢出', '浮点数规格化', 'IEEE754', '计算机存储'],
        '硬件与嵌入式': ['并行计算', '缓存', '体系结构', '无显示器'],
        '软件工程': ['编排系统', 'AI监控', '图的直径', '竞态条件'],
        '数据库': ['SQL', '查询', '数据库'],
    },
    '物理': {
        '量子力学': ['ER=EPR', '复数时间', 'Wick旋转', '维克转动', '虚数时间', '威克转动'],
        '相对论与引力': ['裸奇点', '曲率', '物理统一'],
        '规范场与场论': ['非保守场', '螺旋', '离散数据场'],
        '经典物理': ['原子物理'],
    },
}

# Collect all needed subdirs and create them
all_subdirs = set()
for cat, sub_map in EXTRA.items():
    for sub_name in sub_map:
        all_subdirs.add(os.path.join(BASE, cat, sub_name))
for d in all_subdirs:
    os.makedirs(d, exist_ok=True)

count = 0
for cat, sub_map in EXTRA.items():
    other_dir = os.path.join(BASE, cat, '其他')
    if not os.path.isdir(other_dir):
        continue
    files = [f for f in os.listdir(other_dir) if f.endswith('.md')]
    for fn in sorted(files):
        name = fn[:-3]
        matched = False
        for sub_name, kws in sub_map.items():
            for kw in kws:
                if kw.lower() in name.lower():
                    src = os.path.join(other_dir, fn)
                    dst = os.path.join(BASE, cat, sub_name, fn)
                    if os.path.exists(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        count += 1
                        print(f'{cat}/其他/{fn} → {sub_name}/')
                    matched = True
                    break
            if matched:
                break

print(f'\n总共二次分类: {count} 文件')
print('剩余未分类仍在各"其他/"目录中')