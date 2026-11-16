"""农业专业工具集。

包含农事日历、症状初诊、施肥量估算、农药稀释配比四类计算/查询工具。
所有输出都标注了「参考值，需结合实地情况确认」，避免模型把估算当成定论。
"""
from __future__ import annotations

from datetime import date

from app.agent.tools.base import tool

# ============================================================
# 一、农事日历
# ============================================================

# 节气与大致日期（用于给用户一个时间锚点）
SOLAR_TERMS = [
    ("小寒", (1, 5)), ("大寒", (1, 20)), ("立春", (2, 4)), ("雨水", (2, 19)),
    ("惊蛰", (3, 5)), ("春分", (3, 20)), ("清明", (4, 5)), ("谷雨", (4, 20)),
    ("立夏", (5, 5)), ("小满", (5, 21)), ("芒种", (6, 5)), ("夏至", (6, 21)),
    ("小暑", (7, 7)), ("大暑", (7, 23)), ("立秋", (8, 7)), ("处暑", (8, 23)),
    ("白露", (9, 7)), ("秋分", (9, 23)), ("寒露", (10, 8)), ("霜降", (10, 23)),
    ("立冬", (11, 7)), ("小雪", (11, 22)), ("大雪", (12, 7)), ("冬至", (12, 22)),
]

# 作物 -> 月份 -> 主要农事
CROP_CALENDAR: dict[str, dict[int, list[str]]] = {
    "小麦": {
        9: ["北方冬麦区进入适播期，注意适期适量播种", "施足底肥，氮磷钾配比约 1:0.5:0.5", "播种深度 3~5 厘米，播后镇压"],
        10: ["抢墒播种，防止晚播造成冬前积温不足", "查苗补种，确保基本苗", "播后芽前封闭除草"],
        11: ["冬前化学除草，日均温 10℃ 以上效果较好", "旺长麦田镇压或化控", "防治地下害虫"],
        12: ["浇越冬水，日均温 3~5℃ 时进行，夜冻昼消为宜", "墒情好的田块可不浇，避免大水漫灌"],
        1: ["越冬期注意防冻，雪后及时清除田间积水"],
        2: ["返青前镇压保墒，弥合土壤裂缝"],
        3: ["返青拔节期追肥，占总施氮量 40% 左右", "防治纹枯病、麦蜘蛛", "杂草补除"],
        4: ["拔节孕穗期保证水分供应", "预防倒春寒，关注天气预报", "防治小麦吸浆虫"],
        5: ["抽穗扬花期是赤霉病防治关键期，见花打药", "一喷三防：防病、防虫、防早衰", "注意白粉病、锈病"],
        6: ["蜡熟末期及时收获，防止烂场雨", "收获后及时晾晒，含水量降至 13% 以下贮藏"],
    },
    "玉米": {
        4: ["春玉米区整地施底肥，4 月下旬至 5 月初播种"],
        5: ["春玉米播种出苗，注意防治地下害虫", "夏玉米区准备麦收后贴茬播种"],
        6: ["夏玉米抢时早播，力争 6 月 20 日前完成", "播后芽前封闭除草", "出苗后查苗补苗"],
        7: ["拔节期追施氮肥，占总氮量 50%~60%", "防治玉米螟，可用辛硫磷颗粒剂丢心", "中耕培土防倒伏"],
        8: ["抽雄吐丝期需水临界期，遇旱及时灌溉", "防治穗期病虫害（大小斑病、玉米螟）", "人工辅助授粉可提高结实率"],
        9: ["乳线消失、黑层出现时适期晚收，增产明显", "收获后秸秆还田或青贮"],
    },
    "水稻": {
        3: ["南方早稻播种育秧，注意保温防烂秧"],
        4: ["秧田管理，控水炼苗", "一季稻区准备育秧"],
        5: ["移栽适期，秧龄 30~35 天", "移栽后浅水返青"],
        6: ["分蘖期浅水勤灌，够苗后晒田", "防治二化螟、稻飞虱", "追施分蘖肥"],
        7: ["晒田控蘖，减少无效分蘖", "防治纹枯病、稻纵卷叶螟", "早稻成熟收获"],
        8: ["孕穗抽穗期保持浅水层", "破口期预防稻瘟病、稻曲病", "防高温热害，可灌深水调温"],
        9: ["灌浆期干湿交替，成熟前 7 天断水", "防治稻飞虱", "适时收获"],
    },
    "大豆": {
        5: ["春大豆播种，播深 3~4 厘米", "接种根瘤菌可减少氮肥用量"],
        6: ["夏大豆麦后抢播", "苗期除草，注意防蚜虫"],
        7: ["开花期追肥，避免大水漫灌", "防治大豆食心虫、蚜虫"],
        8: ["结荚鼓粒期保证水分", "叶面喷施磷酸二氢钾防早衰"],
        9: ["叶片脱落、籽粒变硬后收获"],
    },
    "马铃薯": {
        3: ["南方冬作区收获", "北方准备种薯切块催芽"],
        4: ["春薯播种，地温稳定 7℃ 以上", "施足有机肥和钾肥"],
        5: ["出苗后中耕培土", "防治晚疫病，雨后及时喷药"],
        6: ["块茎膨大期保证水分均匀", "培土防止薯块见光变绿"],
        7: ["防治晚疫病关键期", "控氮防徒长"],
        8: ["茎叶枯黄后收获，收前 7~10 天杀秧"],
    },
    "番茄": {
        1: ["温室越冬茬处于结果盛期，注意保温与补光"],
        2: ["温室茬口加强水肥，预防灰霉病"],
        3: ["春大棚番茄定植，注意缓苗期保温"],
        4: ["开花期蘸花保果，控制棚内湿度"],
        5: ["整枝打杈，疏花疏果", "防治早疫病、白粉虱"],
        6: ["盛果期水肥充足，追施钾肥", "防治裂果，避免忽干忽湿"],
        7: ["露地番茄收获盛期", "高温期注意遮阳降温"],
        8: ["秋延后茬育苗定植"],
        9: ["秋茬番茄结果期，夜间注意保温"],
    },
    "生猪": {
        1: ["冬季注意猪舍保温，防止贼风", "加强通风与保温的平衡，控制氨气浓度"],
        2: ["春节前后出栏集中，注意疫病防控"],
        3: ["春季驱虫，全场消毒", "口蹄疫、猪瘟免疫补针"],
        4: ["仔猪补栏旺季，做好引种隔离"],
        5: ["气温回升，注意饲料防霉"],
        6: ["高温来临前检修降温设备", "调整饲喂时间，避开中午高温"],
        7: ["防暑降温，饮水量要充足", "降低饲养密度"],
        8: ["持续防暑，饲料中添加抗应激添加剂"],
        9: ["秋季驱虫，准备秋防"],
        10: ["秋防集中免疫", "注意昼夜温差，防呼吸道病"],
        11: ["做好越冬准备，检修保温设施"],
        12: ["冬季饲养管理，注意通风换气"],
    },
}


def _current_term(d: date) -> str:
    """按日期推算当前所处节气（近似）。"""
    cur = "小寒"
    for name, (m, day) in SOLAR_TERMS:
        if (d.month, d.day) >= (m, day):
            cur = name
        else:
            break
    return cur


@tool(
    name="crop_calendar",
    label="农事日历",
    description=(
        "查询指定作物在某个月份的主要农事活动与关键管理节点。"
        "当用户问「现在该干什么」「什么时候播种/施肥/收获」这类时间相关问题时使用。"
        "支持小麦、玉米、水稻、大豆、马铃薯、番茄、生猪。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "crop": {
                "type": "string",
                "description": "作物或养殖对象，如「小麦」「玉米」「水稻」「番茄」「生猪」",
            },
            "month": {
                "type": "integer",
                "description": "月份 1~12。不填则使用当前月份",
                "minimum": 1,
                "maximum": 12,
            },
        },
        "required": ["crop"],
    },
    tags=["农事", "时间"],
)
def crop_calendar(args: dict) -> dict:
    crop = (args.get("crop") or "").strip()
    month = args.get("month")
    today = date.today()
    month = int(month) if month else today.month

    # 模糊匹配作物名
    matched = None
    for key in CROP_CALENDAR:
        if key in crop or crop in key:
            matched = key
            break

    if not matched:
        return {
            "ok": False,
            "error": f"暂未收录「{crop}」的农事日历",
            "supported": list(CROP_CALENDAR.keys()),
            "suggestion": "可改用 search_knowledge 检索该作物的农事资料",
        }

    tasks = CROP_CALENDAR[matched].get(month, [])
    term = _current_term(today) if month == today.month else ""

    return {
        "crop": matched,
        "month": month,
        "solar_term": term,
        "tasks": tasks,
        "summary": (
            f"{matched} {month} 月主要农事：" + "；".join(tasks)
            if tasks
            else f"该月无特别关键农事，按常规田间管理执行"
        ),
        "disclaimer": "以上为通用农事参考，具体时间需按当地气候、品种熟期和土壤墒情调整。",
    }


# ============================================================
# 二、症状初诊
# ============================================================

# 症状关键词 -> (可能原因, 类别, 建议)
SYMPTOM_RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("叶片发黄", "叶黄", "黄化", "褪绿"), "缺氮或根系吸收受阻、病毒病早期、涝害", "生理性/病害",
     "先看是老叶先黄还是新叶先黄：老叶先黄多为缺氮，新叶先黄多为缺铁锌；同时检查根系是否发黑腐烂、土壤是否积水。"),
    (("叶缘焦枯", "叶尖干枯", "烧边"), "缺钾、盐害、肥害或干旱", "生理性",
     "检查近期是否大量施肥（肥害）或土壤 EC 值偏高；缺钾时老叶叶缘先焦枯，可补施硫酸钾。"),
    (("卷叶", "卷曲", "皱缩"), "蚜虫/粉虱危害、病毒病、高温干旱", "虫害/病害",
     "翻开叶背查看是否有虫；病毒病常伴随植株矮化，需拔除病株并防治传毒媒介（蚜虫、粉虱）。"),
    (("斑点", "病斑", "褐斑", "黑斑"), "真菌性叶斑病（早疫、褐斑、叶霉等）", "病害",
     "观察病斑是否有轮纹、霉层、晕圈；真菌性病害可用苯醚甲环唑、代森锰锌等，注意轮换用药。"),
    (("霉层", "白粉", "灰霉", "长毛"), "白粉病、灰霉病、霜霉病", "病害",
     "降低棚内湿度、加强通风是关键；灰霉病可用腐霉利、嘧霉胺，白粉病可用醚菌酯。"),
    (("萎蔫", "打蔫", "中午蔫"), "根腐病、青枯病、枯萎病、缺水或沤根", "病害/生理性",
     "区分：早晚能恢复多为缺水或高温；持续萎蔫且维管束变褐多为枯萎病/青枯病，需拔除并土壤消毒。"),
    (("烂根", "根腐", "根系发黑"), "根腐病、沤根、线虫危害", "病害",
     "控制浇水、改善透气；可用恶霉灵、甲霜灵灌根；线虫需用阿维菌素或噻唑膦。"),
    (("虫", "咬孔", "蛀", "虫粪"), "咀嚼式口器害虫（菜青虫、玉米螟、地老虎等）", "虫害",
     "确认虫体位置（叶背/心叶/根部）；低龄幼虫期用药效果最好，可用氯虫苯甲酰胺、甲维盐。"),
    (("腻", "黏", "蜜露", "煤污"), "蚜虫、粉虱、蚧壳虫分泌蜜露引发煤污病", "虫害",
     "先治虫再治煤污；可用吡虫啉、噻虫嗪，注意叶背和内膛喷透。"),
    (("畸形", "僵苗", "不长"), "病毒病、药害、缺素或土壤板结", "综合",
     "回想近期是否用过除草剂（药害常致畸形）；排除药害后考虑病毒病与根系问题。"),
    (("死苗", "猝倒", "立枯"), "苗期猝倒病、立枯病", "病害",
     "苗床湿度大易发；可用恶霉灵、甲霜灵拌土或灌根，及时通风降湿。"),
    (("拉稀", "腹泻"), "仔猪黄白痢、饲料突变、受凉", "养殖",
     "检查母猪奶水与仔猪保温；细菌性腹泻可用恩诺沙星，注意补液防脱水。"),
    (("不吃", "减食", "采食下降"), "发热性疾病、饲料霉变、环境应激", "养殖",
     "先测体温；排查饲料是否霉变、圈舍温度与通风；持续减食需请兽医现场诊断。"),
]


@tool(
    name="diagnose_symptom",
    label="病虫害症状初诊",
    description=(
        "根据用户描述的症状（叶片发黄、卷曲、斑点、萎蔫、烂根、虫害等）给出可能原因与排查方向。"
        "这是启发式初诊，不是确诊。当用户描述「叶子怎么了」「为什么不长」这类症状问题时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "symptoms": {
                "type": "string",
                "description": "用户描述的症状原文，尽量完整保留，例如「番茄下部叶片发黄，叶背有白色小虫」",
            },
            "crop": {
                "type": "string",
                "description": "作物或养殖对象名称，可为空",
            },
        },
        "required": ["symptoms"],
    },
    tags=["诊断", "病虫害"],
)
def diagnose_symptom(args: dict) -> dict:
    symptoms = (args.get("symptoms") or "").strip()
    crop = (args.get("crop") or "").strip()

    if not symptoms:
        return {"ok": False, "error": "请描述具体症状"}

    hits = []
    for keywords, cause, kind, advice in SYMPTOM_RULES:
        matched = [k for k in keywords if k in symptoms]
        if matched:
            hits.append(
                {
                    "matched_keywords": matched,
                    "possible_cause": cause,
                    "type": kind,
                    "advice": advice,
                }
            )

    if not hits:
        return {
            "ok": True,
            "crop": crop,
            "matched": 0,
            "results": [],
            "summary": "症状描述未能匹配到常见模式，建议补充：发病部位（老叶/新叶/根/果）、病斑形态、是否有虫、发生时间与蔓延速度。",
        }

    return {
        "ok": True,
        "crop": crop,
        "matched": len(hits),
        "results": hits[:4],
        "summary": "；".join(f"{h['possible_cause']}（{h['type']}）" for h in hits[:3]),
        "disclaimer": "以上为基于关键词的初判，不能替代实地诊断。建议结合田间观察或请当地农技员确认后再用药。",
    }


# ============================================================
# 三、施肥量估算
# ============================================================

# 每 100 公斤经济产量所需养分（公斤）：(N, P2O5, K2O)
NUTRIENT_PER_100KG = {
    "小麦": (3.0, 1.2, 2.5),
    "玉米": (2.6, 1.0, 2.2),
    "水稻": (2.2, 0.9, 2.6),
    "大豆": (1.8, 1.2, 1.5),  # 大豆固氮，氮需求按实际施氮考虑
    "马铃薯": (0.5, 0.2, 1.1),
    "番茄": (0.35, 0.12, 0.55),
    "油菜": (5.8, 2.0, 4.3),
}

# 土壤肥力等级 -> 养分供应系数（占作物需求的比例）
SOIL_SUPPLY = {
    "低": 0.35,
    "中": 0.55,
    "高": 0.70,
}

# 肥料利用率（当季）
FERTILIZER_EFFICIENCY = {"氮": 0.35, "磷": 0.20, "钾": 0.45}


@tool(
    name="calc_fertilizer",
    label="施肥量估算",
    description=(
        "按目标产量和土壤肥力等级，估算氮磷钾纯养分需求量与对应化肥实物量。"
        "当用户问「施多少肥」「一亩要多少尿素」这类定量问题时使用。"
        "结果为估算值，必须提示用户结合测土配方结果调整。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "crop": {"type": "string", "description": "作物名称，如小麦、玉米、水稻、马铃薯、番茄、油菜、大豆"},
            "target_yield": {
                "type": "number",
                "description": "目标亩产，单位公斤/亩。例如小麦 500、玉米 600",
            },
            "soil_level": {
                "type": "string",
                "enum": ["低", "中", "高"],
                "description": "土壤肥力等级，默认「中」",
            },
        },
        "required": ["crop", "target_yield"],
    },
    tags=["施肥", "计算"],
)
def calc_fertilizer(args: dict) -> dict:
    crop = (args.get("crop") or "").strip()
    try:
        target = float(args.get("target_yield") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "目标产量必须为数字"}

    if target <= 0:
        return {"ok": False, "error": "目标产量需大于 0"}

    matched = next((k for k in NUTRIENT_PER_100KG if k in crop or crop in k), None)
    if not matched:
        return {
            "ok": False,
            "error": f"暂未收录「{crop}」的养分需求参数",
            "supported": list(NUTRIENT_PER_100KG.keys()),
        }

    soil = args.get("soil_level") or "中"
    supply = SOIL_SUPPLY.get(soil, 0.55)
    n_per, p_per, k_per = NUTRIENT_PER_100KG[matched]
    unit = target / 100.0

    # 作物总需求
    need_n = n_per * unit
    need_p = p_per * unit
    need_k = k_per * unit

    # 扣除土壤供应后，需要肥料补充的量
    apply_n = need_n * (1 - supply) / FERTILIZER_EFFICIENCY["氮"]
    apply_p = need_p * (1 - supply) / FERTILIZER_EFFICIENCY["磷"]
    apply_k = need_k * (1 - supply) / FERTILIZER_EFFICIENCY["钾"]

    # 折算实物量
    urea = apply_n / 0.46            # 尿素含氮 46%
    dap = apply_p / 0.46             # 磷酸二铵含 P2O5 46%
    kcl = apply_k / 0.60             # 氯化钾含 K2O 60%

    return {
        "crop": matched,
        "target_yield_kg": target,
        "soil_level": soil,
        "nutrient_need_kg": {
            "N": round(need_n, 1),
            "P2O5": round(need_p, 1),
            "K2O": round(need_k, 1),
        },
        "fertilizer_to_apply_kg": {
            "纯N": round(apply_n, 1),
            "纯P2O5": round(apply_p, 1),
            "纯K2O": round(apply_k, 1),
        },
        "product_equivalent_kg": {
            "尿素(46%N)": round(urea, 1),
            "磷酸二铵(46%P2O5)": round(dap, 1),
            "氯化钾(60%K2O)": round(kcl, 1),
        },
        "summary": (
            f"亩产 {target:g} 公斤的{matched}（土壤肥力{soil}）约需："
            f"尿素 {urea:.1f} 公斤、磷酸二铵 {dap:.1f} 公斤、氯化钾 {kcl:.1f} 公斤"
        ),
        "disclaimer": (
            "本结果为养分平衡法估算，未考虑秸秆还田、有机肥带入与前茬残留。"
            "实际施肥量请以测土配方施肥建议卡为准，并分期施用（氮肥分基肥与追肥）。"
        ),
    }


# ============================================================
# 四、农药稀释配比
# ============================================================


@tool(
    name="calc_dilution",
    label="农药稀释计算",
    description=(
        "计算农药稀释所需用药量。支持两种方式：按稀释倍数，或按有效成分浓度（ppm/毫克每千克）。"
        "当用户问「一桶水兑多少药」「稀释 1000 倍怎么配」这类问题时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "water_liters": {
                "type": "number",
                "description": "用水量，单位升。一标准喷雾器通常 15 升",
            },
            "dilution_ratio": {
                "type": "number",
                "description": "稀释倍数，例如 1000 表示稀释 1000 倍。与 target_ppm 二选一",
            },
            "target_ppm": {
                "type": "number",
                "description": "目标有效成分浓度（毫克/千克）。与 dilution_ratio 二选一",
            },
            "product_percent": {
                "type": "number",
                "description": "药剂有效成分含量百分比，例如 10% 制剂填 10。按 ppm 计算时必填",
            },
        },
        "required": ["water_liters"],
    },
    tags=["农药", "计算"],
)
def calc_dilution(args: dict) -> dict:
    try:
        water = float(args.get("water_liters") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "用水量必须为数字"}

    if water <= 0:
        return {"ok": False, "error": "用水量需大于 0"}

    ratio = args.get("dilution_ratio")
    ppm = args.get("target_ppm")
    percent = args.get("product_percent")

    if ratio:
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            return {"ok": False, "error": "稀释倍数必须为数字"}
        if ratio <= 0:
            return {"ok": False, "error": "稀释倍数需大于 0"}

        # 用水量(ml) / 稀释倍数 = 用药量(ml 或 g)
        dose_ml = water * 1000 / ratio
        return {
            "method": "稀释倍数法",
            "water_liters": water,
            "dilution_ratio": ratio,
            "dose_ml_or_g": round(dose_ml, 2),
            "dose_ml_or_g_rounded": round(dose_ml, 1),
            "summary": f"{water:g} 升水，按 {ratio:g} 倍稀释，需取药 {dose_ml:.1f} 毫升（克）",
            "disclaimer": "请严格按农药标签登记剂量使用，注意安全间隔期与轮换用药。",
        }

    if ppm:
        if not percent:
            return {"ok": False, "error": "按浓度计算时必须提供药剂有效成分含量（%）"}
        try:
            ppm = float(ppm)
            percent = float(percent)
        except (TypeError, ValueError):
            return {"ok": False, "error": "浓度与含量必须为数字"}
        if ppm <= 0 or percent <= 0:
            return {"ok": False, "error": "浓度与含量需大于 0"}

        # 用药量(g) = 水量(kg) × 目标浓度(mg/kg) / (制剂含量% × 10)
        dose_g = water * ppm / (percent * 10)
        return {
            "method": "有效成分浓度法",
            "water_liters": water,
            "target_ppm": ppm,
            "product_percent": percent,
            "dose_ml_or_g": round(dose_g, 2),
            "summary": (
                f"{water:g} 升水配 {ppm:g} ppm，用 {percent:g}% 制剂需取药 {dose_g:.1f} 克（毫升）"
            ),
            "disclaimer": "请严格按农药标签登记剂量使用，注意安全间隔期与轮换用药。",
        }

    return {"ok": False, "error": "请提供 dilution_ratio（稀释倍数）或 target_ppm（目标浓度）之一"}
