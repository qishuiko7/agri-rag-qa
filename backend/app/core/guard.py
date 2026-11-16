"""领域拦截器。

对应文档「领域拦截判断」：通过简易关键词匹配识别非农业类问题，
拒绝作答并输出标准化引导语句。刻意保持轻量，不引入分类模型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------- 农业领域词表 ----------
AGRI_WORDS = {
    # 作物
    "水稻", "小麦", "玉米", "大豆", "高粱", "谷子", "大麦", "燕麦", "荞麦",
    "马铃薯", "红薯", "甘薯", "棉花", "油菜", "花生", "芝麻", "向日葵", "甘蔗", "甜菜",
    "蔬菜", "白菜", "萝卜", "番茄", "西红柿", "黄瓜", "辣椒", "茄子", "豆角", "豇豆",
    "土豆", "洋葱", "大蒜", "生姜", "大葱", "韭菜", "菠菜", "生菜", "芹菜", "甘蓝",
    "果树", "苹果", "梨", "桃", "葡萄", "柑橘", "香蕉", "荔枝", "龙眼", "猕猴桃",
    "草莓", "西瓜", "甜瓜", "核桃", "板栗", "枣", "柿", "樱桃",
    "茶", "茶园", "烟草", "中药材", "食用菌", "蘑菇", "木耳",
    # 农事
    "种植", "栽培", "播种", "育苗", "移栽", "定植", "间苗", "整枝", "打杈",
    "施肥", "追肥", "底肥", "基肥", "有机肥", "化肥", "氮肥", "磷肥", "钾肥",
    "复合肥", "水溶肥", "叶面肥", "微肥", "测土配方",
    "灌溉", "浇水", "滴灌", "喷灌", "漫灌", "节水", "保墒", "墒情", "排涝",
    "土壤", "土质", "酸碱度", "盐碱地", "板结", "连作", "轮作", "间作", "套种",
    "田间管理", "中耕", "除草", "覆膜", "地膜", "大棚", "温室", "拱棚", "设施农业",
    " harvest", "收获", "收割", "采收", "贮藏", "储藏", "保鲜", "晾晒", "烘干",
    "品种", "良种", "种子", "包衣", "拌种", "浸种", "催芽", "出苗", "分蘖",
    "抽穗", "灌浆", "成熟", "生育期", "积温", "光周期", "春化",
    # 病虫害
    "病虫害", "病害", "虫害", "防治", "防控", "农药", "杀虫剂", "杀菌剂",
    "除草剂", "生物防治", "绿色防控", "统防统治", "抗药性", "安全间隔期",
    "稻瘟病", "纹枯病", "赤霉病", "锈病", "白粉病", "霜霉病", "枯萎病", "青枯病",
    "根腐病", "疫病", "病毒病", "蚜虫", "红蜘蛛", "蓟马", "粉虱", "螟虫",
    "二化螟", "稻飞虱", "玉米螟", "棉铃虫", "地老虎", "蛴螬", "蝼蛄", "线虫",
    # 养殖
    "养殖", "饲养", "畜禽", "生猪", "养猪", "母猪", "仔猪", "育肥猪",
    "肉牛", "奶牛", "犊牛", "羊", "肉羊", "奶羊", "山羊", "绵羊",
    "蛋鸡", "肉鸡", "鸡舍", "孵化", "育雏", "鸭", "鹅", "兔", "鸽",
    "水产", "鱼塘", "池塘", "养鱼", "草鱼", "鲤鱼", "鲫鱼", "罗非鱼",
    "虾", "对虾", "小龙虾", "螃蟹", "河蟹", "贝类", "海参",
    "饲料", "饲草", "青贮", "配合饲料", "添加剂", "兽药", "疫苗",
    "防疫", "免疫", "消毒", "疫病", "非洲猪瘟", "口蹄疫", "禽流感", "布病",
    "蜂", "养蜂", "蚕", "养蚕", "桑园",
    # 农业经济与政策
    "农技", "农业", "农村", "农民", "农户", "合作社", "家庭农场",
    "惠农", "补贴", "农机", "机械作业", "农业保险", "土地流转", "高标准农田",
    "农产品", "价格", "收购", "销售", "电商", "品牌", "认证", "绿色食品",
    "有机", "无公害", "地理标志", "溯源",
    # 农业气象
    "农事", "节气", "霜冻", "寒潮", "干旱", "洪涝", "冰雹", "倒春寒",
    "梅雨", "台风", "气象", "防灾", "减灾", "抗灾",
}

# ---------- 英文农业词（留学生、外文资料检索场景；不做词形还原，命中即放行）----------
AGRI_WORDS_EN = {
    "wheat", "rice", "corn", "maize", "soybean", "potato", "tomato", "cucumber",
    "pepper", "cotton", "rapeseed", "peanut", "sorghum", "barley", "oat",
    "sugarcane", "fruit", "vegetable", "tea", "tobacco", "mushroom",
    "crop", "plant", "planting", "sowing", "seed", "seedling", "transplant",
    "fertilizer", "fertilization", "manure", "nitrogen", "phosphorus", "potassium",
    "irrigation", "drought", "soil", "tillage", "mulch", "greenhouse",
    "pest", "disease", "insect", "aphid", "borer", "blight", "rust", "mildew",
    "pesticide", "herbicide", "fungicide", "insecticide", "spray",
    "harvest", "yield", "storage", "postharvest", "orchard", "pruning",
    "livestock", "poultry", "pig", "swine", "cattle", "sheep", "goat",
    "chicken", "duck", "aquaculture", "fish", "shrimp", "feed", "fodder",
    "veterinary", "vaccine", "biosecurity", "antibiotic",
    "agriculture", "agricultural", "agronomy", "farm", "farmer", "cropland",
}

# ---------- 明显非农词表（命中且无农业词时拦截）----------
NON_AGRI_WORDS = {
    # 编程技术
    "编程", "代码", "python", "java", "javascript", "算法", "数据库", "服务器",
    "前端", "后端", "接口", "函数", "报错", "bug", "编译",
    # 金融
    "股票", "基金", "期货", "理财", "比特币", "加密货币", "汇率", "炒股",
    # 娱乐
    "电影", "电视剧", "明星", "综艺", "音乐", "游戏", "小说", "动漫",
    "笑话", "段子", "演唱会", "剧本杀", "密室",
    # 体育
    "篮球", "足球", "世界杯", "奥运", "球员",
    # 出行
    "旅游", "景点", "酒店", "机票", "签证", "高铁", "火车", "地铁",
    "公交", "打车", "驾照", "航班", "爬山", "露营",
    # 数码
    "手机", "电脑", "显卡", "相机", "耳机", "买车", "汽车",
    # 生活
    "减肥", "健身", "美容", "化妆", "穿搭", "租房", "买房", "装修",
    "快递", "外卖", "简历", "面试", "求职",
    # 情感
    "恋爱", "情感", "婚姻", "星座", "算命",
    # 人文社科
    "历史", "朝代", "皇帝", "战争", "军事",
    # 学业
    "化学式", "物理题", "数学题", "作文", "翻译", "英语", "考研", "四六级", "论文",
    # 人体医疗（与兽医区分）
    "看病", "医院", "感冒", "发烧", "血压", "体检",
}

# 寒暄与元问题：直接放行，由模型自然应答
# 中文用子串匹配（中文没有词边界）；英文必须整词匹配，
# 否则 "hi" 会命中 "aphid"（蚜虫）、"this" 等，把农技问题误判成寒暄
GREETINGS_ZH = {
    "你好", "您好", "在吗", "在不在", "你是谁", "你叫什么",
    "你能做什么", "怎么用", "帮助", "谢谢", "感谢",
}
GREETINGS_EN = {"hi", "hello", "hey", "thanks", "thank"}

_WORD_RE = re.compile(r"[a-z]+")

_CJK = re.compile(r"[\u4e00-\u9fa5]")


@dataclass
class GuardResult:
    """拦截判定结果。"""

    allowed: bool
    reason: str = ""
    hit_words: tuple[str, ...] = ()


def _hits(text: str, words: set[str]) -> tuple[str, ...]:
    lower = text.lower()
    return tuple(w for w in words if w in lower)


def _is_greeting(q: str) -> bool:
    """判断是否寒暄。英文按整词匹配，避免子串误伤。"""
    lower = q.lower()
    if any(g in lower for g in GREETINGS_ZH):
        return True
    return any(w in GREETINGS_EN for w in _WORD_RE.findall(lower))


def check_question(question: str) -> GuardResult:
    """判断问题是否属于农业领域。

    判定优先级：
    1. 空 / 过短 -> 拦截（由接口层另行提示）
    2. 命中寒暄词 -> 放行
    3. 命中农业词 -> 放行
    4. 仅命中非农词 -> 拦截
    5. 均未命中 -> 放行（宁可放过，由 Prompt 约束模型，避免误杀）
    """
    q = (question or "").strip()
    if not q:
        return GuardResult(False, "问题为空")
    if len(q) < 2:
        return GuardResult(False, "问题过短")

    if _is_greeting(q):
        return GuardResult(True, "寒暄")

    agri = _hits(q, AGRI_WORDS)
    if agri:
        return GuardResult(True, "命中农业词", agri)

    # 英文农业提问（如 "how to control wheat aphid"）不应被后面的
    # 「非中文且无农业特征」规则误杀
    agri_en = tuple(w for w in AGRI_WORDS_EN if w in q.lower())
    if agri_en:
        return GuardResult(True, "命中英文农业词", agri_en)

    non_agri = _hits(q, NON_AGRI_WORDS)
    if non_agri:
        return GuardResult(False, "命中非农词", non_agri)

    # 纯英文且无农业词，多为技术/通用提问
    if not _CJK.search(q) and len(q) > 6:
        return GuardResult(False, "非中文且无农业特征")

    return GuardResult(True, "未命中非农词，放行")
