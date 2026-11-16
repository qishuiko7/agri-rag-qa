"""农事气象工具。

数据源：Open-Meteo 免费公开接口（无需密钥）。
- 地理编码：https://geocoding-api.open-meteo.com/v1/search
- 天气预报：https://api.open-meteo.com/v1/forecast

输出会附带农业影响提示（低温、高温、降雨、大风），便于模型给出针对性建议。
"""
from __future__ import annotations

import logging

import requests

from app.agent.tools.base import tool

logger = logging.getLogger(__name__)

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO 天气代码 -> 中文
WEATHER_CODES = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "霜雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴伴冰雹",
}

# 常见城市经纬度兜底（地理编码失败时使用）
CITY_FALLBACK = {
    "长春": (43.88, 125.32),
    "北京": (39.90, 116.41),
    "郑州": (34.75, 113.63),
    "新乡": (35.30, 113.93),
    "济南": (36.65, 117.12),
    "哈尔滨": (45.80, 126.53),
    "沈阳": (41.81, 123.43),
    "西安": (34.34, 108.94),
    "成都": (30.57, 104.07),
    "武汉": (30.59, 114.31),
    "南京": (32.06, 118.80),
    "杭州": (30.27, 120.16),
    "广州": (23.13, 113.26),
    "长沙": (28.23, 112.94),
    "合肥": (31.82, 117.23),
    "石家庄": (38.04, 114.51),
    "太原": (37.87, 112.55),
    "兰州": (36.06, 103.83),
    "乌鲁木齐": (43.83, 87.62),
}


def _geocode(city: str) -> tuple[float, float, str]:
    """城市名 -> (纬度, 经度, 标准名)。"""
    try:
        r = requests.get(
            GEO_URL,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=8,
        )
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        if results:
            item = results[0]
            return item["latitude"], item["longitude"], item.get("name", city)
    except Exception as exc:  # noqa: BLE001
        logger.warning("地理编码失败 %s：%s", city, exc)

    if city in CITY_FALLBACK:
        lat, lon = CITY_FALLBACK[city]
        return lat, lon, city

    raise RuntimeError(f"无法定位城市「{city}」，请换一个更常见的地名")


def _agri_advice(days: list[dict]) -> list[str]:
    """从预报中提炼农业影响提示。"""
    tips: list[str] = []
    if not days:
        return tips

    t_min = min(d.get("tmin", 99) for d in days)
    t_max = max(d.get("tmax", -99) for d in days)
    rain_sum = sum(d.get("rain", 0) for d in days)
    wind_max = max(d.get("wind", 0) for d in days)

    if t_min <= 0:
        tips.append(f"未来几天最低气温 {t_min:g}℃，需防霜冻：可提前灌水、覆盖地膜或熏烟增温。")
    elif t_min <= 5:
        tips.append(f"最低气温 {t_min:g}℃，设施蔬菜注意夜间保温，露地作物关注低温冷害。")
    if t_max >= 35:
        tips.append(f"最高气温 {t_max:g}℃，注意高温热害：可灌深水调温、叶面喷施磷酸二氢钾增强抗逆性。")
    if rain_sum >= 50:
        tips.append(f"累计降雨约 {rain_sum:g} 毫米，注意田间排水防涝，雨前抢收成熟作物。")
    elif rain_sum >= 10:
        tips.append(f"累计降雨约 {rain_sum:g} 毫米，利于增墒；雨前不宜喷施农药（易被冲刷）。")
    elif rain_sum < 2:
        tips.append("降水偏少，注意保墒；干旱地块可采取滴灌、覆盖秸秆减少蒸发。")
    if wind_max >= 6:
        tips.append(f"最大风速约 {wind_max:g} 米/秒，大风天气不宜喷药、不宜揭膜，注意加固棚架。")

    return tips


@tool(
    name="get_weather",
    label="农事气象查询",
    description=(
        "查询指定城市未来几天的天气与农事影响提示（低温、高温、降雨、大风）。"
        "当用户问「最近天气怎么样」「能不能打药」「会不会冻害」这类与气象相关的问题时使用。"
        "如果用户没有说明地点，可以不传 city，系统默认长春。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名，例如「长春」「郑州」「新乡」。不填默认长春",
            },
            "days": {
                "type": "integer",
                "description": "预报天数，1~7，默认 3",
                "minimum": 1,
                "maximum": 7,
            },
        },
        "required": [],
    },
    tags=["气象", "农事"],
)
def get_weather(args: dict) -> dict:
    city = (args.get("city") or "长春").strip()
    days = min(max(int(args.get("days") or 3), 1), 7)

    lat, lon, name = _geocode(city)

    r = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "wind_speed_10m_max",
            "timezone": "Asia/Shanghai",
            "forecast_days": days,
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    cur = data.get("current") or {}
    daily = data.get("daily") or {}

    forecast = []
    for i, d in enumerate(daily.get("time") or []):
        forecast.append(
            {
                "date": d,
                "weather": WEATHER_CODES.get(daily["weather_code"][i], "未知"),
                "tmax": daily["temperature_2m_max"][i],
                "tmin": daily["temperature_2m_min"][i],
                "rain": daily.get("precipitation_sum", [0] * days)[i],
                "wind": daily.get("wind_speed_10m_max", [0] * days)[i],
            }
        )

    tips = _agri_advice(forecast)

    lines = [
        f"{f['date']} {f['weather']} {f['tmin']:g}~{f['tmax']:g}℃ "
        f"降水{f['rain']:g}mm 风速{f['wind']:g}m/s"
        for f in forecast
    ]

    return {
        "city": name,
        "current": {
            "temp": cur.get("temperature_2m"),
            "humidity": cur.get("relative_humidity_2m"),
            "weather": WEATHER_CODES.get(cur.get("weather_code"), "未知"),
            "wind": cur.get("wind_speed_10m"),
        },
        "forecast": forecast,
        "agri_tips": tips,
        "summary": f"{name}当前 {cur.get('temperature_2m')}℃ {WEATHER_CODES.get(cur.get('weather_code'), '')}；"
                   + "；".join(lines),
        "source": "Open-Meteo 公开气象接口",
    }
