"""第二轮骨架细分：根据标题关键词分类移动文件"""

import os, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = r'D:\ObsidianVault\05-知识\知识库'
CATS = ['AI与机器学习', '编程开发', '数学', '计算机基础', '物理']

# 子目录 = 骨架二级分类
SUBDIRS = {
    'AI与机器学习': ['模型架构', '训练与优化', '深度学习理论', '数据集与预处理', '评估与指标'],
    '编程开发': ['语言与语法', '框架与库使用', '调试与错误排查', '构建与部署', '代码片段与算法实现'],
    '数学': ['基础数学', '高等数学', '群论与几何', '数论与猜想', '概率统计'],
    '计算机基础': ['操作系统', '网络', '数据库', '硬件与嵌入式', '软件工程'],
    '物理': ['量子力学', '相对论与引力', '规范场与场论', '经典物理'],
}

# 关键词 → 子目录映射（每个大类的映射）
KW_MAP = {
    'AI与机器学习': {
        '模型架构': ['Transformer', 'CVAE', 'VAE', 'CNN', 'GNN', 'RNN', 'LSTM', 'GRU', '编码器', '解码器', '注意力', 'Attention', '双曲', 'HNN', '流模型', '扩散模型', '神经架构', '网络结构'],
        '训练与优化': ['损失函数', '过拟合', '梯度', '优化', '学习率', '正则化', '归一化', 'MAML', '元学习', '微调', '迁移学习', 'SGLD', '动量', 'BatchNorm', '标签', '不平衡'],
        '深度学习理论': ['变分', '神经ODE', '表示论', '对偶性', '流形', '纤维丛', '规范场', '群论', '几何', '拓扑', '代数', '对称性', '李群', '李代数', '表示', '对偶', '理论'],
        '数据集与预处理': ['数据集', '数据增强', '预处理', 'TFRecord', '特征', '采样', 'HuggingFace', '加载', '数据', '管道'],
        '评估与指标': ['AUC', '准确率', '评估', 'GLUE', '基准', '测试', '指标', 'Benchmark'],
    },
    '编程开发': {
        '语言与语法': ['Python', 'Java', 'C++', 'JavaScript', 'TypeScript', 'Vue', '汇编', '8086', 'JS', 'TS', 'Go', 'Rust'],
        '框架与库使用': ['TensorFlow', 'Keras', 'PyTorch', 'Spring', 'React', 'Django', 'Flask', 'Maven', 'WPF', 'DevExpress', 'Pandas', 'Matplotlib', 'MPI', 'Pthreads', 'OpenMP', 'CUDA', 'Ascend', 'PlantUML', 'Vue Router', 'WSL'],
        '调试与错误排查': ['错误', '调试', '排查', '卡死', '崩溃', '异常', '修复', '解决', '报错', '警告', 'Bug', 'Issue', '问题', '排查', '故障', '蓝屏'],
        '构建与部署': ['部署', '构建', 'Docker', 'pip', 'npm', '打包', 'RPM', '镜像', '安装', '配置', '环境', '容器', '镜像'],
        '代码片段与算法实现': ['算法', '实现', '代码', '排序', '搜索', '数据结构', '并行', '矩阵', '向量', '函数', '递归', '循环'],
    },
    '数学': {
        '基础数学': ['绝对值', '不等式', '极限', '无穷小', '行列式', '方程', '函数叠加', 'HL判定', '归结原则', '矩阵', '线性'],
        '高等数学': ['积分', '级数', '微分', '导数', '泰勒', '傅里叶', '数值积分'],
        '群论与几何': ['群', '李群', '李代数', '纤维丛', '流形', '对称性', '拓扑', '半群', '变换群', '群轨道', '表示论', '群结构', '群作用', '离散骨架', '双曲空间'],
        '数论与猜想': ['素数', '黎曼', '猜想', '数论', '模'],
        '概率统计': ['概率', '统计', '分布', '贝叶斯', '方差', 'KL散度', '期望', '蒙特卡洛'],
    },
    '计算机基础': {
        '操作系统': ['Windows', 'Linux', 'WSL', 'Ubuntu', '文件系统', '进程', '内存', '线程', 'LVM', 'OpenEuler'],
        '网络': ['Ping', 'TCP', 'IP', '网桥', 'VPN', '协议', '网络', '路由', '交换机', 'nmcli', 'ARP', 'GBN', '滑动窗口', '中继器'],
        '数据库': ['SQL', 'MySQL', 'OpenGauss', '查询', '事务', '授权', '数据库', '关系', 'SPJ', '主键'],
        '硬件与嵌入式': ['8086', 'ARM', 'WeMos', '串口', '嵌入式', '开发板', '硬件', 'HDMI', '驱动', '传感器'],
        '软件工程': ['测试', 'UML', '用例图', '类图', '需求', '项目管理', '文档', '计划', '实验报告'],
    },
    '物理': {
        '量子力学': ['量子', '波函数', '纠缠', '观测', '测量', '薛定谔', '量子干涉'],
        '相对论与引力': ['相对论', '引力', '时空', '超光速', '因果', '全息', '维度', '高维'],
        '规范场与场论': ['规范场', '场论', '对称性破缺', '量子场', '规范群', '规范对称', '规范', '生成元'],
        '经典物理': ['光学', '电磁', '力学', '能量', '热力学', '贝肯斯坦'],
    },
}

# 跨大类移动规则: 只移标题明显错类的文件
CROSS_MOVE = [
    # AI中的纯开发/部署内容 → 编程开发
    ('AI与机器学习', '编程开发', ['MPI并行', 'Pthreads', 'pip安装', '部署', 'Docker', 'WSL安装']),
    # 数学中的纯AI内容 → AI与机器学习
    ('数学', 'AI与机器学习', ['神经网络', '深度学习', '机器学习', 'ARC-AGI']),
    # 物理中的纯数学 → 数学 (暂无规则)
    # 编程开发中的纯数学 → 数学 (暂无规则)
]

total_moved = 0

# Step 1: Cross-category moves first
for src_cat, dst_cat, kws in CROSS_MOVE:
    src_dir = os.path.join(BASE, src_cat)
    if not os.path.isdir(src_dir):
        continue
    dst_dir = os.path.join(BASE, dst_cat)
    os.makedirs(dst_dir, exist_ok=True)
    
    files = [f for f in os.listdir(src_dir) 
             if os.path.isfile(os.path.join(src_dir, f)) 
             and f.endswith('.md') and f != '00-骨架.md']
    
    for fn in files:
        name = fn[:-3]
        for kw in kws:
            if kw.lower() in name.lower():
                src = os.path.join(src_dir, fn)
                dst = os.path.join(dst_dir, fn)
                if not os.path.exists(dst):
                    shutil.move(src, dst)
                    total_moved += 1
                    print(f'跨类: {src_cat}/{fn} → {dst_cat}/')
                else:
                    print(f'跨类: {src_cat}/{fn} → {dst_cat}/ (已存在,跳过)')
                break

# Step 2: Subcategory moves within each category
for cat in CATS:
    cat_dir = os.path.join(BASE, cat)
    if not os.path.isdir(cat_dir):
        continue
    
    sub_dirs = SUBDIRS.get(cat, [])
    kw_map = KW_MAP.get(cat, {})
    
    # Create subdirs
    for sd in sub_dirs:
        os.makedirs(os.path.join(cat_dir, sd), exist_ok=True)
    
    # Get top-level files only
    files = [f for f in os.listdir(cat_dir) 
             if os.path.isfile(os.path.join(cat_dir, f)) 
             and f.endswith('.md') and f != '00-骨架.md']
    
    for fn in sorted(files):
        name = fn[:-3]
        matched = False
        
        for sub_name, kws in kw_map.items():
            for kw in kws:
                if kw.lower() in name.lower():
                    src = os.path.join(cat_dir, fn)
                    dst = os.path.join(cat_dir, sub_name, fn)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        total_moved += 1
                    matched = True
                    break
            if matched:
                break
        
        if not matched:
            # Move to catch-all subdir
            other_dir = os.path.join(cat_dir, '其他')
            os.makedirs(other_dir, exist_ok=True)
            src = os.path.join(cat_dir, fn)
            dst = os.path.join(other_dir, fn)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                total_moved += 1

print(f'\n总计移动: {total_moved} 文件')
print('Done.')