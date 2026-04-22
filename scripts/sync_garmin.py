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

EMAIL           = os.environ.get("GARMIN_EMAIL", "")
PASSWORD        = os.environ.get("GARMIN_PASSWORD", "")
GARMIN_TOKEN    = os.environ.get("GARMIN_TOKEN", "")
GARMIN_COOKIES  = os.environ.get("GARMIN_COOKIES", "")
DATA_FILE       = Path(__file__).parent.parent / "data.json"

# 引数があれば指定日のみ、なければ今日＋昨日を取得
if len(sys.argv) > 1:
    target_dates = [date.fromisoformat(sys.argv[1])]
else:
    target_dates = [date.today(), date.today() - timedelta(days=1)]

USE_GARTH   = False   # garthトークンが有効な場合にTrueになる
USE_COOKIES = False   # ブラウザクッキーが有効な場合にTrueになる
garth_email    = ""
cookie_session = None  # requests.Session（クッキー認証用）

def setup_garth_from_token(token_b64: str) -> bool:
    """garthトークンを復元してgarthで認証する"""
    import base64 as _b64, tempfile
    global garth_email
    try:
        import garth as _garth
    except ImportError:
        return False
    try:
        token_data = json.loads(_b64.b64decode(token_b64).decode())
        garth_email = token_data.get('_email', '')
        tmpdir = tempfile.mkdtemp()
        for filename, content in token_data.items():
            if filename.startswith('_'):
                continue
            with open(os.path.join(tmpdir, filename), "w", encoding="utf-8") as f:
                f.write(content)
        _garth.client.load(tmpdir)
        print("[sync_garmin] garthトークン復元成功")
        return True
    except Exception as e:
        print(f"[sync_garmin] garth復元失敗: {e}")
        return False


def setup_cookies_from_secret(cookies_b64: str) -> bool:
    """ブラウザクッキーを復元してrequests.Sessionを設定する"""
    import base64 as _b64
    global cookie_session
    try:
        import requests as _req
    except ImportError:
        print("[sync_garmin] requestsが未インストール")
        return False
    try:
        cookie_data = json.loads(_b64.b64decode(cookies_b64).decode())
        s = _req.Session()
        s.cookies.update(cookie_data)
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'NK': 'NT',
            'X-app-ver': '4.68.2.0',
            'Di-Backend': 'connectapi.garmin.com',
            'accept': 'application/json, text/plain, */*',
        })
        cookie_session = s
        print("[sync_garmin] クッキー復元成功")
        return True
    except Exception as e:
        print(f"[sync_garmin] クッキー復元失敗: {e}")
        return False


def fetch_day_with_cookies(target_date) -> dict:
    """ブラウザセッションクッキーを使ってその日のデータを取得する"""
    from datetime import date as _date
    d = target_date if isinstance(target_date, _date) else _date.fromisoformat(str(target_date))
    date_str  = d.isoformat()
    date_next = (d + timedelta(days=1)).isoformat()
    BASE = 'https://connect.garmin.com'

    def cget(path, params=None):
        try:
            r = cookie_session.get(f'{BASE}{path}', params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            print(f"  WARN: {path} → HTTP {r.status_code}")
            return None
        except Exception as ex:
            print(f"  WARN: {path} → {ex}")
            return None

    # ユーザープロフィール（displayName取得）
    profile = cget('/userprofile-service/userprofile/personal-information')
    if not profile:
        print("  ERROR: プロフィール取得失敗（クッキー期限切れの可能性あり）")
        return {}
    display_name = profile.get('displayName', '')
    print(f"  ユーザー: {display_name}")

    e = {}

    # 1日サマリー（歩数・カロリー・HR等）
    summary = cget(f'/userstats-service/statistics/daily/{display_name}',
                   params={'fromDate': date_str, 'untilDate': date_str}) or {}
    active_cal  = summary.get("activeKilocalories", 0) or 0
    total_cal   = summary.get("totalKilocalories", 0) or 0
    bmr_cal     = summary.get("bmrKilocalories", 0) or 0
    resting_hr  = summary.get("restingHeartRate", 0) or 0
    min_hr      = summary.get("minHeartRate", 0) or 0
    avg_hr      = summary.get("averageHeartRate", 0) or 0
    max_hr      = summary.get("maxHeartRate", 0) or 0
    steps       = summary.get("totalSteps", 0) or 0
    distance_m  = summary.get("totalDistanceMeters", 0) or 0
    distance_km = round(distance_m / 1000, 2) if distance_m else 0
    floors_up   = summary.get("floorsAscended", 0) or 0
    floors_down = summary.get("floorsDescended", 0) or 0
    mod_minutes = summary.get("moderateIntensityMinutes", 0) or 0
    vig_minutes = summary.get("vigorousIntensityMinutes", 0) or 0

    # Body Battery
    bb_data = cget('/wellness-service/wellness/bodyBattery/scored',
                   params={'startDate': date_str, 'endDate': date_next}) or []
    bb_morning = bb_evening = bb_min_val = bb_max_val = None
    if bb_data:
        try:
            vals = [d[1] for d in bb_data if d[1] is not None]
            if vals:
                bb_morning  = vals[0];  bb_evening = vals[-1]
                bb_min_val  = min(vals); bb_max_val  = max(vals)
        except Exception:
            pass

    # 睡眠
    sleep_score = sleep_hours = deep_sleep = light_sleep = rem_sleep = awake_mins = 0
    sd = cget(f'/wellness-service/wellness/dailySleepData/{display_name}',
              params={'date': date_str, 'nonSleepBufferMinutes': '60'}) or {}
    if sd:
        dto = sd.get("dailySleepDTO", {}) or {}
        sleep_score = dto.get("sleepScores", {}).get("overall", {}).get("value", 0) or dto.get("sleepScore", 0) or 0
        sleep_hours = round((dto.get("sleepTimeSeconds", 0) or 0) / 3600, 1)
        deep_sleep  = round((dto.get("deepSleepSeconds", 0) or 0) / 3600, 1)
        light_sleep = round((dto.get("lightSleepSeconds", 0) or 0) / 3600, 1)
        rem_sleep   = round((dto.get("remSleepSeconds", 0) or 0) / 3600, 1)
        awake_mins  = round((dto.get("awakeSleepSeconds", 0) or 0) / 60, 0)

    # ストレス
    stress_level = "不明"; stress_avg = stress_max = 0
    strd = cget(f'/wellness-service/wellness/dailyStress/{date_str}') or {}
    if strd:
        stress_avg = strd.get("avgStressLevel", 0) or 0
        stress_max = strd.get("maxStressLevel", 0) or 0
        if   stress_avg < 26: stress_level = "低"
        elif stress_avg < 51: stress_level = "やや低"
        elif stress_avg < 76: stress_level = "中"
        elif stress_avg < 86: stress_level = "やや高"
        else:                 stress_level = "高"

    # SpO2
    spo2_avg = spo2_min = 0
    sp = cget(f'/wellness-service/wellness/daily/spo2/{date_str}') or {}
    if sp:
        vals = [r.get("value") for r in (sp.get("spO2HourlyAverages") or []) if r.get("value")]
        if vals: spo2_avg = round(sum(vals)/len(vals), 1); spo2_min = min(vals)

    # 呼吸数
    resp_avg = resp_min = resp_max = 0
    rd = cget(f'/wellness-service/wellness/daily/respiration/{date_str}') or {}
    if rd:
        resp_avg = rd.get("avgWakingRespirationValue", 0) or rd.get("lowestRespirationValue", 0) or 0
        resp_min = rd.get("lowestRespirationValue", 0) or 0
        resp_max = rd.get("highestRespirationValue", 0) or 0

    # HRV
    hrv_weekly_avg = hrv_last_night = 0; hrv_status = None
    hd = cget(f'/hrv-service/hrv/{date_str}') or {}
    if hd:
        s = hd.get("hrvSummary", {}) or {}
        hrv_weekly_avg = s.get("weeklyAvg", 0) or 0
        hrv_last_night = s.get("lastNight", 0) or 0
        hrv_status     = s.get("status")

    # VO2 Max
    vo2_max = fitness_age = 0
    mm = cget(f'/metrics-service/metrics/maxmet/daily/{display_name}',
              params={'fromDate': date_str, 'toDate': date_str}) or {}
    if mm:
        g = mm.get("generic", {}) or {}
        vo2_max     = g.get("vo2MaxPreciseValue", 0) or g.get("vo2MaxValue", 0) or 0
        fitness_age = g.get("fitnessAge", 0) or 0

    # トレーニングステータス
    training_status_val = None; training_load = training_load_7d = 0
    ts_data = cget('/metrics-service/metrics/trainingStatus/daily',
                   params={'fromDate': date_str, 'toDate': date_str}) or {}
    if ts_data:
        ts = ts_data.get("trainingStatusDTO", {}) or ts_data
        training_status_val = ts.get("trainingStatus") or ts.get("latestTrainingStatus")
        training_load    = ts.get("trainingLoad", 0) or 0
        training_load_7d = ts.get("7DayTrainingLoad", 0) or ts.get("sevenDayTrainingLoad", 0) or 0

    # 準備度
    readiness_score = 0; readiness_category = None
    rn = cget('/metrics-service/metrics/trainingReadiness/list',
              params={'fromDate': date_str, 'toDate': date_str}) or {}
    if rn:
        readiness_score    = rn.get("score", 0) or rn.get("trainingReadinessScore", 0) or 0
        readiness_category = rn.get("trainingReadinessCategory") or rn.get("category")

    # 体組成
    weight_kg = bmi = body_fat_pct = muscle_mass = bone_mass = body_water = visceral_fat = metabolic_age = 0
    bc = cget('/weight-service/weight/dateRange',
              params={'startDate': date_str, 'endDate': date_next}) or {}
    if bc:
        ent = bc.get("totalAverage", {}) or {}
        if not ent:
            lst = bc.get("dateWeightList", []) or []
            ent = lst[0] if lst else {}
        w = ent.get("weight", 0) or 0
        weight_kg    = round(w / 1000, 1) if w else 0
        bmi          = ent.get("bmi", 0) or 0
        body_fat_pct = ent.get("bodyFat", 0) or 0
        muscle_mass  = ent.get("muscleMass", 0) or 0
        bone_mass    = ent.get("boneMass", 0) or 0
        body_water   = ent.get("bodyWater", 0) or 0
        visceral_fat = ent.get("visceralFat", 0) or 0
        metabolic_age= ent.get("metabolicAge", 0) or 0

    # 水分
    water_intake_ml = water_goal_ml = 0
    hyd = cget(f'/wellness-service/wellness/hydration/allData/{date_str}') or {}
    if hyd:
        water_intake_ml = hyd.get("totalIntakeInML", 0) or hyd.get("valueInML", 0) or 0
        water_goal_ml   = hyd.get("goalInML", 0) or 0

    print(f"  歩数:{steps} 距離:{distance_km}km 消費:{active_cal}kcal BB:{bb_morning}→{bb_evening} 睡眠:{sleep_score}点 VO2:{vo2_max}")

    if steps:           e["steps"]        = steps
    if distance_km:     e["distanceKm"]   = distance_km
    if active_cal:      e["activeCal"]    = active_cal
    if total_cal:       e["totalCal"]     = total_cal
    if bmr_cal:         e["bmrCal"]       = bmr_cal
    if floors_up:       e["floors"]       = floors_up
    if floors_down:     e["floorsDown"]   = floors_down
    if mod_minutes:     e["modMinutes"]   = mod_minutes
    if vig_minutes:     e["vigMinutes"]   = vig_minutes
    if resting_hr:      e["restingHr"]    = resting_hr
    if min_hr:          e["minHr"]        = min_hr
    if avg_hr:          e["avgHr"]        = avg_hr
    if max_hr:          e["maxHr"]        = max_hr
    if hrv_weekly_avg:  e["hrv"]          = hrv_weekly_avg
    if hrv_last_night:  e["hrvLastNight"] = hrv_last_night
    if hrv_status:      e["hrvStatus"]    = hrv_status
    if bb_morning is not None: e["bbMorning"] = bb_morning
    if bb_evening is not None: e["bbEvening"] = bb_evening
    if bb_min_val is not None: e["bbMin"]     = bb_min_val
    if bb_max_val is not None: e["bbMax"]     = bb_max_val
    if sleep_score:     e["sleepScore"]   = sleep_score
    if sleep_hours:     e["sleepHours"]   = sleep_hours
    if deep_sleep:      e["deepSleep"]    = deep_sleep
    if light_sleep:     e["lightSleep"]   = light_sleep
    if rem_sleep:       e["remSleep"]     = rem_sleep
    if awake_mins:      e["awakeMins"]    = awake_mins
    e["stress"]         = stress_level
    if stress_avg:      e["stressAvg"]    = stress_avg
    if stress_max:      e["stressMax"]    = stress_max
    if spo2_avg:        e["spo2"]         = spo2_avg
    if spo2_min:        e["spo2Min"]      = spo2_min
    if resp_avg:        e["respiration"]  = resp_avg
    if resp_min:        e["respirationMin"] = resp_min
    if resp_max:        e["respirationMax"] = resp_max
    if vo2_max:         e["vo2Max"]       = vo2_max
    if fitness_age:     e["fitnessAge"]   = fitness_age
    if training_status_val: e["trainingStatus"] = training_status_val
    if training_load:   e["trainingLoad"] = training_load
    if training_load_7d: e["trainingLoad7d"] = training_load_7d
    if readiness_score: e["readiness"]    = readiness_score
    if readiness_category: e["readinessCategory"] = readiness_category
    if weight_kg:       e["weightKg"]     = weight_kg
    if bmi:             e["bmi"]          = bmi
    if body_fat_pct:    e["bodyFat"]      = body_fat_pct
    if muscle_mass:     e["muscleMass"]   = muscle_mass
    if bone_mass:       e["boneMass"]     = bone_mass
    if body_water:      e["bodyWater"]    = body_water
    if visceral_fat:    e["visceralFat"]  = visceral_fat
    if metabolic_age:   e["metabolicAge"] = metabolic_age
    if water_intake_ml: e["waterMl"]      = water_intake_ml
    if water_goal_ml:   e["waterGoalMl"]  = water_goal_ml

    return e


def fetch_day_with_garth(target_date) -> dict:
    """garthを使ってその日のデータを取得する"""
    import garth as _garth
    from datetime import date as _date

    d = target_date if isinstance(target_date, _date) else _date.fromisoformat(str(target_date))
    e = {}

    def sg(fn, default=None):
        try: return fn()
        except Exception as ex:
            print(f"  garth WARN: {ex}"); return default

    # ===== DailySummary（メインデータ）=====
    ds = sg(lambda: _garth.DailySummary.get(d))
    if ds:
        def iv(v): return v if v else 0
        steps       = iv(ds.total_steps)
        dist_m      = iv(ds.total_distance_meters)
        dist_km     = round(dist_m / 1000, 2) if dist_m else 0
        active_cal  = iv(ds.active_kilocalories)
        total_cal   = iv(ds.total_kilocalories)
        resting_hr  = iv(ds.resting_heart_rate)
        min_hr      = iv(ds.min_heart_rate)
        avg_hr      = iv(ds.min_avg_heart_rate)
        max_hr      = iv(ds.max_heart_rate)
        stress_avg  = iv(ds.average_stress_level)
        stress_max  = iv(ds.max_stress_level)
        bb_morning  = ds.body_battery_at_wake_time
        bb_max      = ds.body_battery_highest_value
        bb_min      = ds.body_battery_lowest_value
        mod_min     = iv(ds.moderate_intensity_minutes)
        vig_min     = iv(ds.vigorous_intensity_minutes)
        floors_up   = iv(ds.floors_ascended)
        spo2_avg    = iv(ds.average_spo_2)
        spo2_min    = iv(ds.lowest_spo_2)
        resp_avg    = iv(ds.avg_waking_respiration_value)
        resp_max    = iv(ds.highest_respiration_value)
        resp_min    = iv(ds.lowest_respiration_value)

        if stress_avg < 26:    stress_level = "低"
        elif stress_avg < 51:  stress_level = "やや低"
        elif stress_avg < 76:  stress_level = "中"
        elif stress_avg < 86:  stress_level = "やや高"
        else:                  stress_level = "高"

        if steps:           e["steps"]        = steps
        if dist_km:         e["distanceKm"]   = dist_km
        if active_cal:      e["activeCal"]    = active_cal
        if total_cal:       e["totalCal"]     = total_cal
        if floors_up:       e["floors"]       = floors_up
        if mod_min:         e["modMinutes"]   = mod_min
        if vig_min:         e["vigMinutes"]   = vig_min
        if resting_hr:      e["restingHr"]    = resting_hr
        if min_hr:          e["minHr"]        = min_hr
        if avg_hr:          e["avgHr"]        = avg_hr
        if max_hr:          e["maxHr"]        = max_hr
        if bb_morning is not None: e["bbMorning"] = bb_morning
        if bb_max is not None:     e["bbMax"]     = bb_max
        if bb_min is not None:     e["bbMin"]     = bb_min
        e["stress"]         = stress_level
        if stress_avg:      e["stressAvg"]    = stress_avg
        if stress_max:      e["stressMax"]    = stress_max
        if spo2_avg:        e["spo2"]         = spo2_avg
        if spo2_min:        e["spo2Min"]      = spo2_min
        if resp_avg:        e["respiration"]  = resp_avg
        if resp_min:        e["respirationMin"] = resp_min
        if resp_max:        e["respirationMax"] = resp_max

        print(f"  歩数:{steps} 距離:{dist_km}km 消費:{active_cal}kcal BB:{bb_morning} 睡眠:- VO2:-")

    # ===== 睡眠 =====
    sl = sg(lambda: _garth.DailySleepData.get(d))
    if sl and sl.daily_sleep_dto:
        dto = sl.daily_sleep_dto
        score = 0
        if hasattr(dto, 'sleep_scores') and dto.sleep_scores:
            sc = dto.sleep_scores
            score = getattr(sc, 'overall', None)
            if score and hasattr(score, 'value'):
                score = score.value or 0
        def secs2h(attr):
            v = getattr(dto, attr, 0)
            return round((v or 0) / 3600, 1)
        sleep_hours = secs2h('sleep_time_seconds')
        deep_sleep  = secs2h('deep_sleep_seconds')
        light_sleep = secs2h('light_sleep_seconds')
        rem_sleep   = secs2h('rem_sleep_seconds')
        awake_mins  = round((getattr(dto, 'awake_sleep_seconds', 0) or 0) / 60, 0)

        if score:       e["sleepScore"]  = score
        if sleep_hours: e["sleepHours"]  = sleep_hours
        if deep_sleep:  e["deepSleep"]   = deep_sleep
        if light_sleep: e["lightSleep"]  = light_sleep
        if rem_sleep:   e["remSleep"]    = rem_sleep
        if awake_mins:  e["awakeMins"]   = awake_mins

    # ===== HRV =====
    hrv_list = sg(lambda: _garth.DailyHRV.list(d, period=1), [])
    if hrv_list:
        h = hrv_list[0]
        if getattr(h, 'weekly_avg', 0):    e["hrv"]         = h.weekly_avg
        if getattr(h, 'last_night_avg', 0): e["hrvLastNight"] = h.last_night_avg
        if getattr(h, 'status', None):      e["hrvStatus"]    = h.status

    # ===== 体重・体組成 =====
    wt_list = sg(lambda: _garth.WeightData.list(d, period=1), [])
    if wt_list:
        w = wt_list[0]
        if getattr(w, 'weight', None): e["weightKg"]  = round(w.weight / 1000, 1) if w.weight > 500 else w.weight
        if getattr(w, 'bmi', None):    e["bmi"]        = w.bmi
        if getattr(w, 'body_fat', None): e["bodyFat"]  = w.body_fat
        if getattr(w, 'muscle_mass', None): e["muscleMass"] = w.muscle_mass
        if getattr(w, 'bone_mass', None): e["boneMass"] = w.bone_mass
        if getattr(w, 'body_water', None): e["bodyWater"] = w.body_water
        if getattr(w, 'visceral_fat', None): e["visceralFat"] = w.visceral_fat
        if getattr(w, 'metabolic_age', None): e["metabolicAge"] = w.metabolic_age

    # ===== トレーニング =====
    tr_list = sg(lambda: _garth.DailyTrainingStatus.list(d, period=1), [])
    if tr_list:
        tr = tr_list[0]
        if getattr(tr, 'training_status', None): e["trainingStatus"] = tr.training_status
        if getattr(tr, 'weekly_training_load', None): e["trainingLoad"] = tr.weekly_training_load

    return e


# ===== ログイン（優先順位: クッキー > garthトークン > メール/パスワード）=====
client = None

if GARMIN_COOKIES:
    print("[sync_garmin] ブラウザクッキーでログイン中...")
    USE_COOKIES = setup_cookies_from_secret(GARMIN_COOKIES)

if not USE_COOKIES and GARMIN_TOKEN:
    print("[sync_garmin] garthトークンでログイン中...")
    USE_GARTH = setup_garth_from_token(GARMIN_TOKEN)
    if not USE_GARTH:
        print("[sync_garmin] garth失敗。メール/パスワードでログイン試行...")

if not USE_COOKIES and not USE_GARTH:
    try:
        print("[sync_garmin] メール/パスワードでログイン中...")
        client = Garmin(EMAIL, PASSWORD)
        client.login()
        print("[sync_garmin] ログイン成功")
    except Exception as e:
        print(f"[sync_garmin] ログインエラー: {e}")
        sys.exit(1)
elif USE_COOKIES:
    print("[sync_garmin] ログイン成功（クッキー）")
else:
    print("[sync_garmin] ログイン成功（garth）")

def safe(fn, default=None):
    try:
        result = fn()
        return result
    except Exception as e:
        print(f"  WARN: {e}")
        return default

# ===== data.json 読み込み =====
if DATA_FILE.exists():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        store = json.load(f)
else:
    store = {}

# ===== 日付ループ =====
for target_date in target_dates:
    date_str  = target_date.isoformat()
    date_next = (target_date + timedelta(days=1)).isoformat()
    print(f"\n========== {date_str} ==========")

    # クッキーモードはここで分岐
    if USE_COOKIES:
        e = fetch_day_with_cookies(target_date)
        if date_str not in store:
            store[date_str] = {}
        store[date_str].update(e)
        continue

    # garthモードはここで分岐して保存して次の日付へ
    if USE_GARTH:
        e = fetch_day_with_garth(target_date)
        if date_str not in store:
            store[date_str] = {}
        store[date_str].update(e)
        continue

    # 1日サマリー
    summary = safe(lambda: client.get_daily_summary(date_str), {}) or {}
    active_cal  = summary.get("activeKilocalories", 0) or 0
    total_cal   = summary.get("totalKilocalories", 0) or 0
    bmr_cal     = summary.get("bmrKilocalories", 0) or 0
    resting_hr  = summary.get("restingHeartRate", 0) or 0
    min_hr      = summary.get("minHeartRate", 0) or 0
    avg_hr      = summary.get("averageHeartRate", 0) or 0
    max_hr      = summary.get("maxHeartRate", 0) or 0
    steps       = summary.get("totalSteps", 0) or 0
    distance_m  = summary.get("totalDistanceMeters", 0) or 0
    distance_km = round(distance_m / 1000, 2) if distance_m else 0
    floors_up   = summary.get("floorsAscended", 0) or 0
    floors_down = summary.get("floorsDescended", 0) or 0
    mod_minutes = summary.get("moderateIntensityMinutes", 0) or 0
    vig_minutes = summary.get("vigorousIntensityMinutes", 0) or 0

    # 歩数補完
    if not steps:
        steps_data = safe(lambda: client.get_steps_data(date_str), []) or []
        try:
            steps = sum(d.get("steps", 0) for d in steps_data if d.get("steps"))
        except Exception:
            pass

    # Body Battery
    bb_data = safe(lambda: client.get_body_battery(date_str, date_next), []) or []
    bb_morning = bb_evening = bb_min = bb_max = None
    if bb_data:
        try:
            vals = [d[1] for d in bb_data if d[1] is not None]
            if vals:
                bb_morning = vals[0]; bb_evening = vals[-1]
                bb_min = min(vals);   bb_max = max(vals)
        except Exception:
            pass

    # 睡眠
    sleep_score = sleep_hours = deep_sleep = light_sleep = rem_sleep = awake_mins = 0
    sd = safe(lambda: client.get_sleep_data(date_str), {}) or {}
    if sd:
        dto = sd.get("dailySleepDTO", {}) or {}
        sleep_score = dto.get("sleepScores", {}).get("overall", {}).get("value", 0) or dto.get("sleepScore", 0) or 0
        sleep_hours = round((dto.get("sleepTimeSeconds", 0) or 0) / 3600, 1)
        deep_sleep  = round((dto.get("deepSleepSeconds", 0) or 0) / 3600, 1)
        light_sleep = round((dto.get("lightSleepSeconds", 0) or 0) / 3600, 1)
        rem_sleep   = round((dto.get("remSleepSeconds", 0) or 0) / 3600, 1)
        awake_mins  = round((dto.get("awakeSleepSeconds", 0) or 0) / 60, 0)

    # ストレス
    stress_level = "不明"; stress_avg = stress_max = 0
    strd = safe(lambda: client.get_stress_data(date_str), {}) or {}
    if strd:
        stress_avg = strd.get("avgStressLevel", 0) or 0
        stress_max = strd.get("maxStressLevel", 0) or 0
        if   stress_avg < 26: stress_level = "低"
        elif stress_avg < 51: stress_level = "やや低"
        elif stress_avg < 76: stress_level = "中"
        elif stress_avg < 86: stress_level = "やや高"
        else:                 stress_level = "高"

    # SpO2
    spo2_avg = spo2_min = 0
    sp = safe(lambda: client.get_spo2_data(date_str), {}) or {}
    if sp:
        vals = [r.get("value") for r in (sp.get("spO2HourlyAverages") or []) if r.get("value")]
        if vals: spo2_avg = round(sum(vals)/len(vals), 1); spo2_min = min(vals)

    # 呼吸数
    resp_avg = resp_min = resp_max = 0
    rd = safe(lambda: client.get_respiration_data(date_str), {}) or {}
    if rd:
        resp_avg = rd.get("avgWakingRespirationValue", 0) or rd.get("lowestRespirationValue", 0) or 0
        resp_min = rd.get("lowestRespirationValue", 0) or 0
        resp_max = rd.get("highestRespirationValue", 0) or 0

    # HRV
    hrv_weekly_avg = hrv_last_night = 0; hrv_status = None
    hd = safe(lambda: client.get_hrv_data(date_str), {}) or {}
    if hd:
        s = hd.get("hrvSummary", {}) or {}
        hrv_weekly_avg = s.get("weeklyAvg", 0) or 0
        hrv_last_night = s.get("lastNight", 0) or 0
        hrv_status     = s.get("status")

    # VO2 Max
    vo2_max = fitness_age = 0
    mm = safe(lambda: client.get_max_metrics(date_str), {}) or {}
    if mm:
        g = mm.get("generic", {}) or {}
        vo2_max    = g.get("vo2MaxPreciseValue", 0) or g.get("vo2MaxValue", 0) or 0
        fitness_age = g.get("fitnessAge", 0) or 0

    # トレーニング
    training_status_val = None; training_load = training_load_7d = 0
    ts_data = safe(lambda: client.get_training_status(date_str), {}) or {}
    if ts_data:
        ts = ts_data.get("trainingStatusDTO", {}) or ts_data
        training_status_val = ts.get("trainingStatus") or ts.get("latestTrainingStatus")
        training_load    = ts.get("trainingLoad", 0) or 0
        training_load_7d = ts.get("7DayTrainingLoad", 0) or ts.get("sevenDayTrainingLoad", 0) or 0

    # 準備度
    readiness_score = 0; readiness_category = None
    rn = safe(lambda: client.get_training_readiness(date_str), {}) or {}
    if rn:
        readiness_score    = rn.get("score", 0) or rn.get("trainingReadinessScore", 0) or 0
        readiness_category = rn.get("trainingReadinessCategory") or rn.get("category")

    # 体組成
    weight_kg = bmi = body_fat_pct = muscle_mass = bone_mass = body_water = visceral_fat = metabolic_age = 0
    bc = safe(lambda: client.get_body_composition(date_str, date_next), {}) or {}
    if bc:
        ent = bc.get("totalAverage", {}) or {}
        if not ent:
            lst = bc.get("dateWeightList", []) or []
            ent = lst[0] if lst else {}
        w = ent.get("weight", 0) or 0
        weight_kg    = round(w / 1000, 1) if w else 0
        bmi          = ent.get("bmi", 0) or 0
        body_fat_pct = ent.get("bodyFat", 0) or 0
        muscle_mass  = ent.get("muscleMass", 0) or 0
        bone_mass    = ent.get("boneMass", 0) or 0
        body_water   = ent.get("bodyWater", 0) or 0
        visceral_fat = ent.get("visceralFat", 0) or 0
        metabolic_age= ent.get("metabolicAge", 0) or 0

    # 水分・血圧・持久力
    water_intake_ml = water_goal_ml = bp_systolic = bp_diastolic = endurance_score = 0
    hyd = safe(lambda: client.get_hydration_data(date_str), {}) or {}
    if hyd:
        water_intake_ml = hyd.get("totalIntakeInML", 0) or hyd.get("valueInML", 0) or 0
        water_goal_ml   = hyd.get("goalInML", 0) or 0
    bpd = safe(lambda: client.get_blood_pressure(date_str, date_next), {}) or {}
    if bpd:
        meas = bpd.get("measurementSummaries", []) or []
        if meas:
            bp_systolic  = meas[0].get("systolic", 0) or 0
            bp_diastolic = meas[0].get("diastolic", 0) or 0
    end = safe(lambda: client.get_endurance_score(date_str, date_next), {}) or {}
    if end:
        items = end.get("enduranceScoreDTO", []) or end.get("items", []) or []
        if items: endurance_score = items[0].get("enduranceScore", 0) or 0

    print(f"  歩数:{steps} 距離:{distance_km}km 消費:{active_cal}kcal BB:{bb_morning}→{bb_evening} 睡眠:{sleep_score}点 VO2:{vo2_max}")

    # data.json 保存
    if date_str not in store:
        store[date_str] = {}
    e = store[date_str]

    if steps:           e["steps"]        = steps
    if distance_km:     e["distanceKm"]   = distance_km
    if active_cal:      e["activeCal"]    = active_cal
    if total_cal:       e["totalCal"]     = total_cal
    if bmr_cal:         e["bmrCal"]       = bmr_cal
    if floors_up:       e["floors"]       = floors_up
    if floors_down:     e["floorsDown"]   = floors_down
    if mod_minutes:     e["modMinutes"]   = mod_minutes
    if vig_minutes:     e["vigMinutes"]   = vig_minutes
    if resting_hr:      e["restingHr"]    = resting_hr
    if min_hr:          e["minHr"]        = min_hr
    if avg_hr:          e["avgHr"]        = avg_hr
    if max_hr:          e["maxHr"]        = max_hr
    if hrv_weekly_avg:  e["hrv"]          = hrv_weekly_avg
    if hrv_last_night:  e["hrvLastNight"] = hrv_last_night
    if hrv_status:      e["hrvStatus"]    = hrv_status
    if bb_morning is not None: e["bbMorning"] = bb_morning
    if bb_evening is not None: e["bbEvening"] = bb_evening
    if bb_min is not None:     e["bbMin"]     = bb_min
    if bb_max is not None:     e["bbMax"]     = bb_max
    if sleep_score:     e["sleepScore"]   = sleep_score
    if sleep_hours:     e["sleepHours"]   = sleep_hours
    if deep_sleep:      e["deepSleep"]    = deep_sleep
    if light_sleep:     e["lightSleep"]   = light_sleep
    if rem_sleep:       e["remSleep"]     = rem_sleep
    if awake_mins:      e["awakeMins"]    = awake_mins
    e["stress"]         = stress_level
    if stress_avg:      e["stressAvg"]    = stress_avg
    if stress_max:      e["stressMax"]    = stress_max
    if spo2_avg:        e["spo2"]         = spo2_avg
    if spo2_min:        e["spo2Min"]      = spo2_min
    if resp_avg:        e["respiration"]  = resp_avg
    if resp_min:        e["respirationMin"] = resp_min
    if resp_max:        e["respirationMax"] = resp_max
    if vo2_max:         e["vo2Max"]       = vo2_max
    if fitness_age:     e["fitnessAge"]   = fitness_age
    if training_status_val: e["trainingStatus"] = training_status_val
    if training_load:   e["trainingLoad"] = training_load
    if training_load_7d: e["trainingLoad7d"] = training_load_7d
    if readiness_score: e["readiness"]    = readiness_score
    if readiness_category: e["readinessCategory"] = readiness_category
    if endurance_score: e["enduranceScore"] = endurance_score
    if weight_kg:       e["weightKg"]     = weight_kg
    if bmi:             e["bmi"]          = bmi
    if body_fat_pct:    e["bodyFat"]      = body_fat_pct
    if muscle_mass:     e["muscleMass"]   = muscle_mass
    if bone_mass:       e["boneMass"]     = bone_mass
    if body_water:      e["bodyWater"]    = body_water
    if visceral_fat:    e["visceralFat"]  = visceral_fat
    if metabolic_age:   e["metabolicAge"] = metabolic_age
    if water_intake_ml: e["waterMl"]      = water_intake_ml
    if water_goal_ml:   e["waterGoalMl"]  = water_goal_ml
    if bp_systolic:     e["bpSystolic"]   = bp_systolic
    if bp_diastolic:    e["bpDiastolic"]  = bp_diastolic

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(store, f, ensure_ascii=False, indent=2)

print(f"\n[sync_garmin] 保存完了 ({len(target_dates)}日分)")
