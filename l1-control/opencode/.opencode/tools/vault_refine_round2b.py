"""第二轮骨架细分（剩余 4 个骨架）：医疗健康 / 学习考试 / 生活常识 / 娱乐与文化"""
import os, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = r'D:\ObsidianVault\05-知识\知识库'
CATS = ['医疗健康', '学习考试', '生活常识', '娱乐与文化']

SUBDIRS = {
    '医疗健康': ['中医辨证与调理', '两性与生殖', '药物与营养', '神经与生理', '法医学'],
    '学习考试': ['考研', '论文及相关写作', '政治与哲学', '体育与体测', '学术规范与伦理', '教育制度与政策'],
    '生活常识': ['法律与社会', '财务与税务', '车辆与驾驶', '交通与快递', '自然与气象', '数据与换算', '数字与隐私'],
    '娱乐与文化': ['游戏与电竞', '足球规则', '历史与人物', '占卜与玄学', '语言与语义', '平台与媒体', '社会与科普'],
}

KW_MAP = {
    '医疗健康': {
        '中医辨证与调理': ['中医', '辨证', '养生', '打鼾', '多梦', '梦呓', '口苦', '口臭', '腹胀', '血瘀', '高血压', '腰部', '酸痛', '肾', '脾', '胃'],
        '两性与生殖': ['早泄', '龟头', '包皮', '射精'],
        '药物与营养': ['烟酰胺', '维生素', '药理', '副作用', '安全服用'],
        '神经与生理': ['心动过速', '心律失常', '心率', '血压', '生物神经网络', 'DLPFC', '神经', '中枢', '外周'],
        '法医学': ['法医', '尸检', '抽血'],
    },
    '学习考试': {
        '考研': ['考研', '推免', '保研', '国科大'],
        '论文及相关写作': ['论文', '写作', '引言', '摘要', '期刊', '文献'],
        '政治与哲学': ['历史唯物主义', '哲学', '物质', '唯物', '辩证', '文化遗产'],
        '体育与体测': ['跑步', '体测', '免测', '10000米', '万米', '体育'],
        '学术规范与伦理': ['AI辅助', '创新归属', '学术', '伦理', '署名'],
        '教育制度与政策': ['院士', '制度', '行政级别', '评选'],
    },
    '生活常识': {
        '法律与社会': ['三方协议', '协议', '违法', '犯罪', '轻罚', '封存', '法律'],
        '财务与税务': ['存款', '财务', '税务', '奖金', '工资'],
        '车辆与驾驶': ['远光灯', '近光灯', '驾驶', '安全距离', 'Rimac', '汽车'],
        '交通与快递': ['高铁', '携带', '快递'],
        '自然与气象': ['燕子', '低飞', '下雨'],
        '数据与换算': ['人口', '计量', '换算', '尺寸'],
        '数字与隐私': ['AI对话', '隐私', '版权', '生成内容'],
    },
    '娱乐与文化': {
        '游戏与电竞': ['Minecraft', '模组', '文明6', '腓尼基', '看眼猜球星', '游戏'],
        '足球规则': ['足球', '手球', '门球'],
        '历史与人物': ['二战', '坦克', '空战', '王牌', '卫子夫', '历史'],
        '占卜与玄学': ['卡巴拉', '生命树', '生日', '起名', '星座', 'INTP', '属鸡', '狮子座'],
        '语言与语义': ['同义词', '语法', '蒙塔古', '语义'],
        '平台与媒体': ['Pinterest', '社交', '平台'],
        '社会与科普': ['科学成就', '社会地位', '文化遗产', '活化'],
    },
}

total_moved = 0
for cat in CATS:
    cat_dir = os.path.join(BASE, cat)
    if not os.path.isdir(cat_dir):
        continue
    for sd in SUBDIRS.get(cat, []):
        os.makedirs(os.path.join(cat_dir, sd), exist_ok=True)

    files = [f for f in os.listdir(cat_dir)
             if os.path.isfile(os.path.join(cat_dir, f))
             and f.endswith('.md') and f != '00-骨架.md']

    for fn in sorted(files):
        name = fn[:-3]
        matched = False
        for sub_name, kws in KW_MAP.get(cat, {}).items():
            for kw in kws:
                if kw.lower() in name.lower():
                    src = os.path.join(cat_dir, fn)
                    dst = os.path.join(cat_dir, sub_name, fn)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        total_moved += 1
                    print(f'{cat}/{fn} -> {sub_name}/')
                    matched = True
                    break
            if matched:
                break
        if not matched:
            other_dir = os.path.join(cat_dir, '其他')
            os.makedirs(other_dir, exist_ok=True)
            src = os.path.join(cat_dir, fn)
            dst = os.path.join(other_dir, fn)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                total_moved += 1
            print(f'{cat}/{fn} -> 其他/')

print(f'\n总计移动: {total_moved} 文件')
print('Done.')
