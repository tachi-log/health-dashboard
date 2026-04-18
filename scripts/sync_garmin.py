#!/usr/bin/env python3
"""
Garmin Connect → data.json 同期スクリプト
取得できる健康・フィットネスデータを全て保存する
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

EMAIL     = os.environ["GARMIN_EMAIL"]
PASSWORD  = os.environ["GARMIN_PASSWORD"]
DATA_FILE = Path(__file__).parent.parent / "data.json"

target_date = date.today() - timedelta(days=1)
if len(sys.argv) > 1:
    target_date = date.fromisoformat(sys.argv[1])

date_str  = target_date.isoformat()
date_next = (target_date + timedelta(days=1)).isoformat()
print(f"[sync_garmin] 対象日: {date_str}")

try:
    client = Garmin(EMAIL, PASSWORD)
    client.login()
    print("[sync_garmin] ログイン成功")
except Exception as e:
    print(f"[sync_garmin] ログインエラー: {e}")
    sys.exit(1)

def safe(fn, default=None):
    try:
        result = fn()
        return result
    except Exception as e:
        print(f"  WARN: {e}")
        return default

# ===== 1日サマリー =====
summary = safe(lambda: client.get_daily_summary(date_str), {}) or {}
active_cal   = summary.get("activeKilocalories", 0) or 0
total_cal    = summary.get("totalKilocalories", 0) or 0
bmr_cal      = summary.get("bmrKilocalories", 0) or 0
resting_hr   = summary.get("restingHeartRate", 0) or 0
min_hr       = summary.get("minHeartRate", 0) or 0
avg_hr       = summary.get("averageHeartRate", 0) or 0
max_hr       = summary.get("maxHeartRate", 0) or 0
steps        = summary.get("totalSteps", 0) or 0
distance_m   = summary.get("totalDistanceMeters", 0) or 0
distance_km  = round(distance_m / 1000, 2) if distance_m else 0
floors_up    = summary.get("floorsAscended", 0) or 0
floors_down  = summary.get("floorsDescended", 0) or 0
mod_minutes  = summary.get("moderateIntensityMinutes", 0) or 0
vig_minutes  = summary.get("vigorousIntensityMinutes", 0) or 0

# 歩数補完
steps_data = safe(lambda: client.get_steps_data(date_str), []) or []
if not steps and steps_data:
    try:
        steps = sum(d.get("steps", 0) for d in steps_data if d.get("steps"))
    except Exception:
        pass

# ===== Body Battery =====
bb_data = safe(lambda: client.get_body_battery(date_str, date_next), []) or []
bb_morning, bb_evening, bb_min, bb_max = None, None, None, None
if bb_data:
    try:
        values = [d[1] for d in bb_data if d[1] is not None]
        if values:
            bb_morning = values[0]
            bb_evening = values[-1]
            bb_min     = min(values)
            bb_max     = max(values)
    except Exception:
        pass

# ===== 睡眠 =====
sleep_data  = safe(lambda: client.get_sleep_data(date_str), {}) or {}
sleep_score = 0
sleep_hours = 0
deep_sleep  = 0
light_sleep = 0
rem_sleep   = 0
awake_mins  = 0
sleep_start = None
sleep_end   = None
if sleep_data:
    dto = sleep_data.get("dailySleepDTO", {}) or {}
    sleep_score  = dto.get("sleepScores", {}).get("overall", {}).get("value", 0) or dto.get("sleepScore", 0) or 0
    total_sec    = dto.get("sleepTimeSeconds", 0) or 0
    sleep_hours  = round(total_sec / 3600, 1) if total_sec else 0
    deep_sleep   = round((dto.get("deepSleepSeconds", 0) or 0) / 3600, 1)
    light_sleep  = round((dto.get("lightSleepSeconds", 0) or 0) / 3600, 1)
    rem_sleep    = round((dto.get("remSleepSeconds", 0) or 0) / 3600, 1)
    awake_mins   = round((dto.get("awakeSleepSeconds", 0) or 0) / 60, 0)
    sleep_start  = dto.get("sleepStartTimestampLocal")
    sleep_end    = dto.get("sleepEndTimestampLocal")

# ===== ストレス =====
stress_data  = safe(lambda: client.get_stress_data(date_str), {}) or {}
stress_level = "不明"
stress_avg   = 0
stress_max   = 0
stress_rest  = 0
if stress_data:
    stress_avg  = stress_data.get("avgStressLevel", 0) or 0
    stress_max  = stress_data.get("maxStressLevel", 0) or 0
    stress_rest = stress_data.get("restStressDuration", 0) or 0
    if   stress_avg < 26: stress_level = "低"
    elif stress_avg < 51: stress_level = "やや低"
    elif stress_avg < 76: stress_level = "中"
    elif stress_avg < 86: stress_level = "やや高"
    else:                 stress_level = "高"

# ===== SpO2 =====
spo2_data = safe(lambda: client.get_spo2_data(date_str), {}) or {}
spo2_avg, spo2_min = 0, 0
if spo2_data:
    readings = spo2_data.get("spO2HourlyAverages", []) or []
    vals = [r.get("value") for r in readings if r.get("value")]
    if vals:
        spo2_avg = round(sum(vals) / len(vals), 1)
        spo2_min = min(vals)

# ===== 呼吸数 =====
resp_data = safe(lambda: client.get_respiration_data(date_str), {}) or {}
resp_avg, resp_min, resp_max = 0, 0, 0
if resp_data:
    resp_avg = resp_data.get("avgWakingRespirationValue", 0) or resp_data.get("lowestRespirationValue", 0) or 0
    resp_min = resp_data.get("lowestRespirationValue", 0) or 0
    resp_max = resp_data.get("highestRespirationValue", 0) or 0

# ===== HRV =====
hrv_data = safe(lambda: client.get_hrv_data(date_str), {}) or {}
hrv_weekly_avg, hrv_last_night, hrv_status = 0, 0, None
if hrv_data:
    s = hrv_data.get("hrvSummary", {}) or {}
    hrv_weekly_avg = s.get("weeklyAvg", 0) or 0
    hrv_last_night = s.get("lastNight", 0) or 0
    hrv_status     = s.get("status")

# ===== VO2 Max & フィットネス年齢 =====
max_metrics = safe(lambda: client.get_max_metrics(date_str), {}) or {}
vo2_max      = 0
fitness_age  = 0
if max_metrics:
    generic = max_metrics.get("generic", {}) or {}
    vo2_max    = generic.get("vo2MaxPreciseValue", 0) or generic.get("vo2MaxValue", 0) or 0
    fitness_age = generic.get("fitnessAge", 0) or 0

# ===== トレーニングステータス =====
train_status = safe(lambda: client.get_training_status(date_str), {}) or {}
training_status_val   = None
training_load         = 0
training_load_7d      = 0
if train_status:
    ts = train_status.get("trainingStatusDTO", {}) or train_status
    training_status_val = ts.get("trainingStatus") or ts.get("latestTrainingStatus")
    training_load       = ts.get("trainingLoad", 0) or 0
    training_load_7d    = ts.get("7DayTrainingLoad", 0) or ts.get("sevenDayTrainingLoad", 0) or 0

# ===== トレーニング準備度 =====
readiness = safe(lambda: client.get_training_readiness(date_str), {}) or {}
readiness_score    = 0
readiness_category = None
if readiness:
    readiness_score    = readiness.get("score", 0) or readiness.get("trainingReadinessScore", 0) or 0
    readiness_category = readiness.get("trainingReadinessCategory") or readiness.get("category")

# ===== 体組成 =====
body_comp = safe(lambda: client.get_body_composition(date_str, date_next), {}) or {}
weight_kg    = 0
bmi          = 0
body_fat_pct = 0
muscle_mass  = 0
bone_mass    = 0
body_water   = 0
visceral_fat = 0
metabolic_age = 0
if body_comp:
    entries = body_comp.get("totalAverage", {}) or {}
    if not entries:
        all_entries = body_comp.get("dateWeightList", []) or []
        entries = all_entries[0] if all_entries else {}
    weight_kg    = entries.get("weight", 0) or 0
    if weight_kg: weight_kg = round(weight_kg / 1000, 1)  # g→kg
    bmi          = entries.get("bmi", 0) or 0
    body_fat_pct = entries.get("bodyFat", 0) or 0
    muscle_mass  = entries.get("muscleMass", 0) or 0
    bone_mass    = entries.get("boneMass", 0) or 0
    body_water   = entries.get("bodyWater", 0) or 0
    visceral_fat = entries.get("visceralFat", 0) or 0
    metabolic_age = entries.get("metabolicAge", 0) or 0

# ===== 水分補給 =====
hydration = safe(lambda: client.get_hydration_data(date_str), {}) or {}
water_intake_ml = 0
water_goal_ml   = 0
if hydration:
    water_intake_ml = hydration.get("totalIntakeInML", 0) or hydration.get("valueInML", 0) or 0
    water_goal_ml   = hydration.get("goalInML", 0) or 0

# ===== 血圧 =====
bp_data = safe(lambda: client.get_blood_pressure(date_str, date_next), {}) or {}
bp_systolic  = 0
bp_diastolic = 0
if bp_data:
    meas = bp_data.get("measurementSummaries", []) or []
    if meas:
        latest = meas[0]
        bp_systolic  = latest.get("systolic", 0) or 0
        bp_diastolic = latest.get("diastolic", 0) or 0

# ===== 持久力スコア =====
endurance = safe(lambda: client.get_endurance_score(date_str, date_next), {}) or {}
endurance_score = 0
if endurance:
    items = endurance.get("enduranceScoreDTO", []) or endurance.get("items", []) or []
    if items:
        endurance_score = items[0].get("enduranceScore", 0) or 0

# ===== ログ出力 =====
print(f"\n--- 活動 ---")
print(f"  歩数: {steps}  距離: {distance_km}km  階数↑{floors_up}/↓{floors_down}")
print(f"  消費(active/total/BMR): {active_cal}/{total_cal}/{bmr_cal} kcal")
print(f"  強度分数(中/高): {mod_minutes}/{vig_minutes}分")
print(f"\n--- 心拍 ---")
print(f"  安静時: {resting_hr}  最低: {min_hr}  平均: {avg_hr}  最大: {max_hr} bpm")
print(f"  HRV: 週平均{hrv_weekly_avg} / 昨夜{hrv_last_night} ms  状態:{hrv_status}")
print(f"\n--- Body Battery ---")
print(f"  朝{bb_morning} → 夜{bb_evening}  最低{bb_min} / 最高{bb_max}")
print(f"\n--- 睡眠 ---")
print(f"  スコア:{sleep_score}  時間:{sleep_hours}h  深:{deep_sleep}h 浅:{light_sleep}h REM:{rem_sleep}h 覚醒:{awake_mins}分")
print(f"\n--- ストレス ---")
print(f"  レベル:{stress_level}  平均:{stress_avg}  最大:{stress_max}")
print(f"\n--- 健康指標 ---")
print(f"  SpO2: 平均{spo2_avg}% / 最低{spo2_min}%")
print(f"  呼吸数: 平均{resp_avg} / 最低{resp_min} / 最高{resp_max} 回/分")
print(f"\n--- フィットネス ---")
print(f"  VO2 Max: {vo2_max}  フィットネス年齢: {fitness_age}")
print(f"  トレーニング状態: {training_status_val}  負荷: {training_load} / 7日:{training_load_7d}")
print(f"  準備度: {readiness_score} ({readiness_category})")
print(f"  持久力スコア: {endurance_score}")
print(f"\n--- 体組成 ---")
print(f"  体重:{weight_kg}kg  BMI:{bmi}  体脂肪:{body_fat_pct}%  筋肉:{muscle_mass}g  骨:{bone_mass}g")
print(f"  体水分:{body_water}%  内臓脂肪:{visceral_fat}  代謝年齢:{metabolic_age}")
print(f"\n--- その他 ---")
print(f"  水分摂取: {water_intake_ml}ml / 目標{water_goal_ml}ml")
print(f"  血圧: {bp_systolic}/{bp_diastolic} mmHg")

# ===== data.json 保存 =====
if DATA_FILE.exists():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        store = json.load(f)
else:
    store = {}

if date_str not in store:
    store[date_str] = {}

e = store[date_str]

# 活動
if steps:           e["steps"]        = steps
if distance_km:     e["distanceKm"]   = distance_km
if active_cal:      e["activeCal"]    = active_cal
if total_cal:       e["totalCal"]     = total_cal
if bmr_cal:         e["bmrCal"]       = bmr_cal
if floors_up:       e["floors"]       = floors_up
if floors_down:     e["floorsDown"]   = floors_down
if mod_minutes:     e["modMinutes"]   = mod_minutes
if vig_minutes:     e["vigMinutes"]   = vig_minutes

# 心拍
if resting_hr:      e["restingHr"]    = resting_hr
if min_hr:          e["minHr"]        = min_hr
if avg_hr:          e["avgHr"]        = avg_hr
if max_hr:          e["maxHr"]        = max_hr

# HRV
if hrv_weekly_avg:  e["hrv"]          = hrv_weekly_avg
if hrv_last_night:  e["hrvLastNight"] = hrv_last_night
if hrv_status:      e["hrvStatus"]    = hrv_status

# Body Battery
if bb_morning is not None: e["bbMorning"] = bb_morning
if bb_evening is not None: e["bbEvening"] = bb_evening
if bb_min is not None:     e["bbMin"]     = bb_min
if bb_max is not None:     e["bbMax"]     = bb_max

# 睡眠
if sleep_score:     e["sleepScore"]   = sleep_score
if sleep_hours:     e["sleepHours"]   = sleep_hours
if deep_sleep:      e["deepSleep"]    = deep_sleep
if light_sleep:     e["lightSleep"]   = light_sleep
if rem_sleep:       e["remSleep"]     = rem_sleep
if awake_mins:      e["awakeMins"]    = awake_mins

# ストレス
e["stress"]         = stress_level
if stress_avg:      e["stressAvg"]    = stress_avg
if stress_max:      e["stressMax"]    = stress_max

# SpO2 / 呼吸
if spo2_avg:        e["spo2"]         = spo2_avg
if spo2_min:        e["spo2Min"]      = spo2_min
if resp_avg:        e["respiration"]  = resp_avg
if resp_min:        e["respirationMin"] = resp_min
if resp_max:        e["respirationMax"] = resp_max

# フィットネス
if vo2_max:         e["vo2Max"]       = vo2_max
if fitness_age:     e["fitnessAge"]   = fitness_age
if training_status_val: e["trainingStatus"] = training_status_val
if training_load:   e["trainingLoad"] = training_load
if training_load_7d: e["trainingLoad7d"] = training_load_7d
if readiness_score: e["readiness"]    = readiness_score
if readiness_category: e["readinessCategory"] = readiness_category
if endurance_score: e["enduranceScore"] = endurance_score

# 体組成
if weight_kg:       e["weightKg"]     = weight_kg
if bmi:             e["bmi"]          = bmi
if body_fat_pct:    e["bodyFat"]      = body_fat_pct
if muscle_mass:     e["muscleMass"]   = muscle_mass
if bone_mass:       e["boneMass"]     = bone_mass
if body_water:      e["bodyWater"]    = body_water
if visceral_fat:    e["visceralFat"]  = visceral_fat
if metabolic_age:   e["metabolicAge"] = metabolic_age

# 水分・血圧
if water_intake_ml: e["waterMl"]      = water_intake_ml
if water_goal_ml:   e["waterGoalMl"]  = water_goal_ml
if bp_systolic:     e["bpSystolic"]   = bp_systolic
if bp_diastolic:    e["bpDiastolic"]  = bp_diastolic

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(store, f, ensure_ascii=False, indent=2)

print(f"\n[sync_garmin] 保存完了 → {date_str}")
