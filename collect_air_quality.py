import os
import sys
from datetime import datetime, timezone, timedelta

import requests
import urllib3
from supabase import create_client

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role key (เก็บเป็น secret เท่านั้น)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TH_TZ = timezone(timedelta(hours=7))
AIR4THAI_URL = "http://air4thai.pcd.go.th/services/getNewAQI_JSON.php"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def to_float(v):
    """แปลงค่า เช่น '-1', '', None ให้เป็น None"""
    try:
        f = float(v)
        return None if f < 0 else f
    except (TypeError, ValueError):
        return None


def to_int(v):
    f = to_float(v)
    return None if f is None else int(f)


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    now = datetime.now(TH_TZ).replace(minute=0, second=0, microsecond=0)
    print(f"⏳ เริ่มดึงข้อมูล รอบเวลา {now.isoformat()}")

    # 1) ดึงข้อมูลฝุ่น
    res = requests.get(AIR4THAI_URL, timeout=60, verify=False)
    res.raise_for_status()
    stations = res.json()["stations"]

    dim_rows, air_rows, coords = [], [], {}

    for st in stations:
        try:
            sid = st["stationID"]
            lat, lon = float(st["lat"]), float(st["long"])
        except (KeyError, TypeError, ValueError):
            continue

        dim_rows.append({
            "station_id": sid,
            "source": "Air4Thai",
            "name_th": st.get("nameTH"),
            "latitude": lat,
            "longitude": lon,
        })
        coords[sid] = (lat, lon)

        last = st.get("AQILast") or {}
        pm25 = to_float((last.get("PM25") or {}).get("value"))
        aqi = to_int((last.get("AQI") or {}).get("aqi"))
        if pm25 is None and aqi is None:
            continue

        # ใช้เวลาจากสถานีถ้ามี ไม่งั้นใช้เวลารอบปัจจุบัน
        ts = now
        try:
            ts = datetime.strptime(f"{last['date']} {last['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TH_TZ)
        except (KeyError, ValueError, TypeError):
            pass

        air_rows.append({
            "station_id": sid,
            "timestamp": ts.isoformat(),
            "pm25": pm25,
            "aqi": aqi,
        })

    # 2) บันทึกสถานี + ฝุ่น (upsert กันข้อมูลซ้ำ)
    for chunk in batches(dim_rows, 200):
        supabase.table("dim_stations").upsert(chunk, on_conflict="station_id").execute()
    for chunk in batches(air_rows, 200):
        supabase.table("fact_air_quality").upsert(chunk, on_conflict="station_id,timestamp").execute()
    print(f"✅ สถานี {len(dim_rows)} แห่ง, ข้อมูลฝุ่น {len(air_rows)} แถว")

    # 3) ดึงสภาพอากาศแบบ batch (Open-Meteo รับหลายพิกัดในคำขอเดียว)
    weather_rows = []
    ids = list(coords.keys())
    for chunk_ids in batches(ids, 50):
        lats = ",".join(str(coords[i][0]) for i in chunk_ids)
        lons = ",".join(str(coords[i][1]) for i in chunk_ids)
        r = requests.get(OPEN_METEO_URL, params={
            "latitude": lats,
            "longitude": lons,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
            "timezone": "Asia/Bangkok",
        }, timeout=60)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):  # กรณีมีพิกัดเดียว API จะคืน dict
            data = [data]

        for sid, w in zip(chunk_ids, data):
            cur = w.get("current") or {}
            weather_rows.append({
                "station_id": sid,
                "timestamp": now.isoformat(),
                "temp": cur.get("temperature_2m"),
                "humidity": cur.get("relative_humidity_2m"),
                "wind_speed": cur.get("wind_speed_10m"),
                "wind_direction": cur.get("wind_direction_10m"),
            })

    for chunk in batches(weather_rows, 200):
        supabase.table("fact_weather").upsert(chunk, on_conflict="station_id,timestamp").execute()
    print(f"🌤️ สภาพอากาศ {len(weather_rows)} แถว")
    print("🎉 เสร็จเรียบร้อย")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ ผิดพลาด: {e}")
        sys.exit(1)
