import sqlite3
import requests
import time
from datetime import datetime

# 1. สร้าง/เชื่อมต่อฐานข้อมูล
conn = sqlite3.connect('air_quality_db.sqlite')
cursor = conn.cursor()

# 2. สร้างตาราง 3 ตาราง
cursor.execute('''CREATE TABLE IF NOT EXISTS dim_stations (station_id TEXT PRIMARY KEY, source TEXT, name_th TEXT, latitude REAL, longitude REAL)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS fact_air_quality (id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT, timestamp DATETIME, pm25 REAL, aqi INTEGER, FOREIGN KEY(station_id) REFERENCES dim_stations(station_id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS fact_weather (id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT, timestamp DATETIME, temp REAL, humidity REAL, wind_speed REAL, wind_direction REAL, FOREIGN KEY(station_id) REFERENCES dim_stations(station_id))''')
conn.commit()
print("✅ เตรียมฐานข้อมูลสำเร็จ!")

# 3. ดึงข้อมูลฝุ่นจาก Air4Thai
current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
print("⏳ กำลังดึงข้อมูล...")
air_data = requests.get("http://air4thai.pcd.go.th/services/getNewAQI_JSON.php", verify=False).json()

# ดึงแค่ 5 สถานีแรกมาทดสอบ (ถ้าอยากได้หมดให้ลบ [:5] ออก)
for station in air_data['stations'][:]:
    station_id = station['stationID']
    name_th = station['nameTH']
    lat = float(station['lat'])
    lon = float(station['long'])
    
    # บันทึกสถานี
    cursor.execute('''INSERT OR IGNORE INTO dim_stations (station_id, source, name_th, latitude, longitude) VALUES (?, ?, ?, ?, ?)''', (station_id, 'Air4Thai', name_th, lat, lon))
    
    try:
        # บันทึกฝุ่น
        pm25 = station['AQILast']['PM25']['value']
        aqi = station['AQILast']['AQI']['aqi']
        cursor.execute('''INSERT INTO fact_air_quality (station_id, timestamp, pm25, aqi) VALUES (?, ?, ?, ?)''', (station_id, current_time, pm25, aqi))
        print(f"📍 บันทึก: {name_th} (PM2.5: {pm25})")
        
        # 4. ดึงสภาพอากาศจาก Open-Meteo ตามพิกัดสถานี
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"
        w_data = requests.get(weather_url).json()
        
        temp = w_data['current']['temperature_2m']
        humidity = w_data['current']['relative_humidity_2m']
        wind_speed = w_data['current']['wind_speed_10m']
        wind_direction = w_data['current']['wind_direction_10m']
        
        # บันทึกสภาพอากาศ
        cursor.execute('''INSERT INTO fact_weather (station_id, timestamp, temp, humidity, wind_speed, wind_direction) VALUES (?, ?, ?, ?, ?, ?)''', (station_id, current_time, temp, humidity, wind_speed, wind_direction))
        print(f"   🌤️ อากาศ: {temp}°C, ความชื้น {humidity}%")
        
    except Exception as e:
        print(f"⚠️ ข้ามสถานี {name_th} เนื่องจากข้อมูลไม่ครบ")
    
    time.sleep(0.5) # พักเซิร์ฟเวอร์แปปนึง

conn.commit()
conn.close()
print("🎉 เสร็จเรียบร้อย! ข้อมูลอยู่ในไฟล์ air_quality_db.sqlite")
