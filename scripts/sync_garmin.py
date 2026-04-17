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
EMAIL    = os.environ["GARMIN_EMAIL"]
PASSWORD = os.environ["GARMIN_PASSWORD"]
DATA_FILE = Path(__file__).parent.parent / "data.json"

# 取得対象日（デフォルト: 昨日）
target_date = date.today() - timedelta(days=1)
if len(sys.argv) > 1:
    target_date = date.fromisoformat(sys.argv[1])

date_str = target_date.isoformat()
print(f"[sync_garmin] 取得対象日: {date_str}")

# ===== Garmin 接続 =====
try:
    client = Garmin(EMAIL, PASSWORD)
    client.login()
    print("[sync_garmin] Garmin Connect ログイン成功")
except Exception as e:
    print(f"[sync_garmin] ログインエラー: {e}")
    sys.exit(1)

# ===== データ取得 =====
def safe_get(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"  WARN: {e}")
        return default

# 歩数・消費カロリー
steps_data = safe_get(lambda: client.get_steps_data(date_str), [])
total_steps = 0
if steps_data:
    try:
        total_steps = sum(d.get("steps", 0) for d in steps_data if d.get("steps"))
    except Exception:
        total_steps = 0

# 1日サマリー（消費カロリー・安静時心拍）
daily_summary = safe_get(lambda: client.get_daily_summary(date_str), {})
active_calories = daily_summary.get("activeKilocalories", 0) if daily_summary else 0
resting_hr      = daily_summary.get("restingHeartRate",   0) if daily_summary else 0
total_steps = total_steps or (daily_summary.get("totalSteps", 0) if daily_summary else 0)

# 睡眠スコア
sleep_data  = safe_get(lambda: client.get_sleep_data(date_str), {})
sleep_score = 0
if sleep_data:
    try:
        sleep_score = sleep_data.get("dailySleepDTO", {}).get("sleepScores", {}).get("overall", {}).get("value", 0)
        if not sleep_score:
            sleep_score = sleep_data.get("dailySleepDTO", {}).get("sleepScore", 0)
    except Exception:
        sleep_score = 0

# Body Battery
bb_data = safe_get(lambda: client.get_body_battery(date_str), [])
bb_morning, bb_evening = None, None
if bb_data:
    try:
        values = [d[1] for d in bb_data if d[1] is not None]
        if values:
            bb_morning = values[0]
            bb_evening = values[-1]
    except Exception:
        pass

# ストレス
stress_data  = safe_get(lambda: client.get_stress_data(date_str), {})
stress_level = "不明"
if stress_data:
    try:
        avg = stress_data.get("avgStressLevel", 0) or 0
        if   avg < 26: stress_level = "低"
        elif avg < 51: stress_level = "やや低"
        elif avg < 76: stress_level = "中"
        elif avg < 86: stress_level = "やや高"
        else:          stress_level = "高"
    except Exception:
        stress_level = "不明"

print(f"  歩数:         {total_steps}")
print(f"  消費kcal:     {active_calories}")
print(f"  BB朝/夜:      {bb_morning} / {bb_evening}")
print(f"  睡眠スコア:   {sleep_score}")
print(f"  安静時心拍:   {resting_hr}")
print(f"  ストレス:     {stress_level}")

# ===== data.json 読み込み・更新 =====
if DATA_FILE.exists():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        store = json.load(f)
else:
    store = {}

if date_str not in store:
    store[date_str] = {}

entry = store[date_str]
if total_steps:    entry["steps"]       = total_steps
if active_calories: entry["activeCal"]  = active_calories
if bb_morning is not None: entry["bbMorning"] = bb_morning
if bb_evening is not None: entry["bbEvening"] = bb_evening
if sleep_score:    entry["sleepScore"]  = sleep_score
if resting_hr:     entry["restingHr"]   = resting_hr
entry["stress"] = stress_level

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(store, f, ensure_ascii=False, indent=2)

print(f"[sync_garmin] data.json に保存完了 → {date_str}")
