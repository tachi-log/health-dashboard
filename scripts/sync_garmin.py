#!/usr/bin/env python3
"""
Garmin Connect → data.json 同期スクリプト
毎朝GitHub Actionsで実行し、昨日のデータをdata.jsonに追記する
"""

import os
import json
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    from garminconnect import Garmin
except ImportError:
    print("ERROR: garminconnect not installed. Run: pip install garminconnect")
    sys.exit(1)

# ===== 設定 =====
EMAIL     = os.environ["GARMIN_EMAIL"]
PASSWORD  = os.environ["GARMIN_PASSWORD"]
DATA_FILE = Path(__file__).parent.parent / "data.json"

target_date = date.today() - timedelta(days=1)
if len(sys.argv) > 1:
    target_date = date.fromisoformat(sys.argv[1])

date_str = target_date.isoformat()
print(f"[sync_garmin] 取得対象日: {date_str}")

# ===== Garmin 接続 =====
try:
    client = Garmin(EMAIL, PASSWORD)
    client.login()
    print("[sync_garmin] ログイン成功")
except Exception as e:
    print(f"[sync_garmin] ログインエラー: {e}")
    sys.exit(1)

def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"  WARN: {e}")
        return default

# ===== 1日サマリー =====
summary = safe(lambda: client.get_daily_summary(date_str), {}) or {}
active_cal   = summary.get("activeKilocalories", 0) or 0
total_cal    = summary.get("totalKilocalories", 0) or 0   # BMR含む総消費
resting_hr   = summary.get("restingHeartRate", 0) or 0
avg_hr       = summary.get("averageHeartRate", 0) or 0
max_hr       = summary.get("maxHeartRate", 0) or 0
steps        = summary.get("totalSteps", 0) or 0
distance_m   = summary.get("totalDistanceMeters", 0) or 0
distance_km  = round(distance_m / 1000, 2) if distance_m else 0
floors       = summary.get("floorsAscended", 0) or 0
mod_minutes  = summary.get("moderateIntensityMinutes", 0) or 0
vig_minutes  = summary.get("vigorousIntensityMinutes", 0) or 0

# ===== 歩数（サマリーで取れない場合の補完）=====
steps_data = safe(lambda: client.get_steps_data(date_str), []) or []
if not steps and steps_data:
    try:
        steps = sum(d.get("steps", 0) for d in steps_data if d.get("steps"))
    except Exception:
        pass

# ===== Body Battery =====
bb_data = safe(lambda: client.get_body_battery(date_str), []) or []
bb_morning, bb_evening = None, None
if bb_data:
    try:
        values = [d[1] for d in bb_data if d[1] is not None]
        if values:
            bb_morning = values[0]
            bb_evening = values[-1]
    except Exception:
        pass

# ===== 睡眠 =====
sleep_data  = safe(lambda: client.get_sleep_data(date_str), {}) or {}
sleep_score = 0
sleep_hours = 0
deep_sleep  = 0
light_sleep = 0
rem_sleep   = 0
awake_sleep = 0
if sleep_data:
    dto = sleep_data.get("dailySleepDTO", {}) or {}
    sleep_score = dto.get("sleepScores", {}).get("overall", {}).get("value", 0) or \
                  dto.get("sleepScore", 0) or 0
    total_sec = dto.get("sleepTimeSeconds", 0) or 0
    sleep_hours = round(total_sec / 3600, 1) if total_sec else 0
    deep_sleep  = round((dto.get("deepSleepSeconds", 0) or 0) / 3600, 1)
    light_sleep = round((dto.get("lightSleepSeconds", 0) or 0) / 3600, 1)
    rem_sleep   = round((dto.get("remSleepSeconds", 0) or 0) / 3600, 1)
    awake_sleep = round((dto.get("awakeSleepSeconds", 0) or 0) / 60, 0)  # 分

# ===== ストレス =====
stress_data  = safe(lambda: client.get_stress_data(date_str), {}) or {}
stress_level = "不明"
stress_avg   = 0
if stress_data:
    stress_avg = stress_data.get("avgStressLevel", 0) or 0
    if   stress_avg < 26: stress_level = "低"
    elif stress_avg < 51: stress_level = "やや低"
    elif stress_avg < 76: stress_level = "中"
    elif stress_avg < 86: stress_level = "やや高"
    else:                 stress_level = "高"

# ===== SpO2（血中酸素）=====
spo2_data = safe(lambda: client.get_spo2_data(date_str), {}) or {}
spo2_avg = 0
if spo2_data:
    readings = spo2_data.get("spO2HourlyAverages", []) or []
    vals = [r.get("value") for r in readings if r.get("value")]
    spo2_avg = round(sum(vals) / len(vals), 1) if vals else 0

# ===== 呼吸数 =====
resp_data = safe(lambda: client.get_respiration_data(date_str), {}) or {}
resp_avg = 0
if resp_data:
    resp_avg = resp_data.get("avgWakingRespirationValue", 0) or \
               resp_data.get("lowestRespirationValue", 0) or 0

# ===== HRV（心拍変動）=====
hrv_data = safe(lambda: client.get_hrv_data(date_str), {}) or {}
hrv_avg = 0
if hrv_data:
    summary_hrv = hrv_data.get("hrvSummary", {}) or {}
    hrv_avg = summary_hrv.get("weeklyAvg", 0) or summary_hrv.get("lastNight", 0) or 0

# ===== ログ出力 =====
print(f"  歩数:           {steps}")
print(f"  距離:           {distance_km} km")
print(f"  階数:           {floors}")
print(f"  消費(active):   {active_cal} kcal")
print(f"  消費(total):    {total_cal} kcal")
print(f"  強度分数:       中{mod_minutes}分 高{vig_minutes}分")
print(f"  BB朝/夜:        {bb_morning} / {bb_evening}")
print(f"  睡眠スコア:     {sleep_score}")
print(f"  睡眠時間:       {sleep_hours}h (深{deep_sleep} 浅{light_sleep} REM{rem_sleep})")
print(f"  安静時心拍:     {resting_hr} bpm")
print(f"  平均心拍:       {avg_hr} bpm")
print(f"  最大心拍:       {max_hr} bpm")
print(f"  ストレス:       {stress_level} (avg:{stress_avg})")
print(f"  SpO2:           {spo2_avg} %")
print(f"  呼吸数:         {resp_avg} 回/分")
print(f"  HRV:            {hrv_avg} ms")

# ===== data.json 保存 =====
if DATA_FILE.exists():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        store = json.load(f)
else:
    store = {}

if date_str not in store:
    store[date_str] = {}

e = store[date_str]
if steps:         e["steps"]       = steps
if active_cal:    e["activeCal"]   = active_cal
if total_cal:     e["totalCal"]    = total_cal
if distance_km:   e["distanceKm"]  = distance_km
if floors:        e["floors"]      = floors
if mod_minutes:   e["modMinutes"]  = mod_minutes
if vig_minutes:   e["vigMinutes"]  = vig_minutes
if bb_morning is not None: e["bbMorning"] = bb_morning
if bb_evening is not None: e["bbEvening"] = bb_evening
if sleep_score:   e["sleepScore"]  = sleep_score
if sleep_hours:   e["sleepHours"]  = sleep_hours
if deep_sleep:    e["deepSleep"]   = deep_sleep
if light_sleep:   e["lightSleep"]  = light_sleep
if rem_sleep:     e["remSleep"]    = rem_sleep
if awake_sleep:   e["awakeMins"]   = awake_sleep
if resting_hr:    e["restingHr"]   = resting_hr
if avg_hr:        e["avgHr"]       = avg_hr
if max_hr:        e["maxHr"]       = max_hr
if stress_avg:    e["stressAvg"]   = stress_avg
e["stress"] = stress_level
if spo2_avg:      e["spo2"]        = spo2_avg
if resp_avg:      e["respiration"] = resp_avg
if hrv_avg:       e["hrv"]         = hrv_avg

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(store, f, ensure_ascii=False, indent=2)

print(f"[sync_garmin] 保存完了 → {date_str}")
