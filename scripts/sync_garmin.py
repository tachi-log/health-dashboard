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

# macOS上でGARMIN_COOKIESが未設定の場合、ChromeからCookieを自動取得する
if not GARMIN_COOKIES and sys.platform == 'darwin':
    try:
        import subprocess as _sp
        _script = Path(__file__).parent / 'get_chrome_cookies.py'
        if _script.exists():
            print("[sync_garmin] macOS: ChromeからGarmin Cookieを自動取得中...")
            _result = _sp.run(
                [sys.executable, str(_script)],
                capture_output=True, text=True, timeout=60
            )
            _b64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
            for _line in _result.stdout.split('\n'):
                _line = _line.strip()
                if len(_line) > 100 and all(c in _b64_chars for c in _line):
                    GARMIN_COOKIES = _line
                    print("[sync_garmin] Chrome Cookie自動取得成功")
                    break
            if not GARMIN_COOKIES and _result.stderr:
                print(f"[sync_garmin] Chrome Cookie取得エラー: {_result.stderr[:200]}")
    except Exception as _e:
        print(f"[sync_garmin] Chrome Cookie自動取得失敗: {_e}")

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
    """ブラウザクッキーを復元してcurl_cffiセッションを設定する"""
    import base64 as _b64
    import re as _re
    global cookie_session
    try:
        from curl_cffi import requests as _cffi_req
    except ImportError:
        import subprocess as _sp
        _sp.run([sys.executable, "-m", "pip", "install", "curl-cffi", "-q"])
        from curl_cffi import requests as _cffi_req
    try:
        cookie_data = json.loads(_b64.b64decode(cookies_b64).decode())
        s = _cffi_req.Session(impersonate="chrome124")
        s.headers.update({
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'ja,en-US;q=0.9,en;q=0.8',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
        })
        for k in ('JWT_WEB', 'SESSIONID', 'session', '__cflb', 'GARMIN-SSO', 'GARMIN-SSO-CUST-GUID'):
            if k in cookie_data:
                s.cookies.set(k, cookie_data[k])
        # /app/ を取得してCSRFトークンをメタタグから抽出
        try:
            r = s.get('https://connect.garmin.com/app/', timeout=15)
            m = _re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', r.text)
            if not m:
                m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf-token["\']', r.text)
            if m:
                s.headers['connect-csrf-token'] = m.group(1)
                print(f"[sync_garmin] CSRFトークン取得成功")
        except Exception as _ce:
            print(f"[sync_garmin] CSRFトークン取得失敗: {_ce}")
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
    USER_UUID = '21e1dcd0-c83d-4073-a595-bda1e98497c2'  # gc-api用UUID
    USER_PK   = '131347661'

    def cget(path, params=None):
        if not path.startswith('/gc-api/'):
            path = '/gc-api' + path
        try:
            r = cookie_session.get(f'{BASE}{path}', params=params, timeout=30)
            if r.status_code == 200:
                data = r.json()
                return data if data else None
            print(f"  WARN: {path} → HTTP {r.status_code}")
            return None
        except Exception as ex:
            print(f"  WARN: {path} → {ex}")
            return None

    e = {}

    # 1日サマリー（usersummary-service 使用）
    summary = cget(f'/usersummary-service/usersummary/daily/{USER_UUID}',
                   params={'calendarDate': date_str}) or {}
    active_cal  = summary.get("activeKilocalories", 0) or 0
    total_cal   = summary.get("totalKilocalories", 0) or 0
    bmr_cal     = summary.get("bmrKilocalories", 0) or 0
    resting_hr  = summary.get("restingHeartRate", 0) or 0
    min_hr      = summary.get("minHeartRate", 0) or 0
    avg_hr      = summary.get("minAvgHeartRate", 0) or 0
    max_hr      = summary.get("maxHeartRate", 0) or 0
    steps       = summary.get("totalSteps", 0) or 0
    distance_m  = summary.get("totalDistanceMeters", 0) or 0
    distance_km = round(distance_m / 1000, 2) if distance_m else 0
    floors_up   = summary.get("floorsAscended", 0) or 0
    floors_down = summary.get("floorsDescended", 0) or 0
    mod_minutes = summary.get("moderateIntensityMinutes", 0) or 0
    vig_minutes = summary.get("vigorousIntensityMinutes", 0) or 0
    stress_avg  = summary.get("averageStressLevel", 0) or 0
    stress_max  = summary.get("maxStressLevel", 0) or 0
    bb_morning  = summary.get("bodyBatteryAtWakeTime")
    bb_highest  = summary.get("bodyBatteryHighestValue")
    bb_lowest   = summary.get("bodyBatteryLowestValue")
    bb_recent   = summary.get("bodyBatteryMostRecentValue")
    spo2_avg    = summary.get("averageSpo2", 0) or 0
    spo2_min    = summary.get("lowestSpo2", 0) or 0

    if stress_avg:
        if   stress_avg < 26: stress_level = "低"
        elif stress_avg < 51: stress_level = "やや低"
        elif stress_avg < 76: stress_level = "中"
        elif stress_avg < 86: stress_level = "やや高"
        else:                 stress_level = "高"
    else:
        stress_level = "不明"

    # 睡眠
    sleep_score = sleep_hours = deep_sleep = light_sleep = rem_sleep = awake_mins = 0
    sd = cget(f'/wellness-service/wellness/dailySleepData/{USER_UUID}',
              params={'date': date_str}) or {}
    if sd:
        dto = sd.get("dailySleepDTO", {}) or {}
        sleep_score = (dto.get("sleepScores") or {}).get("overall", {}).get("value", 0) or dto.get("sleepScore", 0) or 0
        sleep_hours = round((dto.get("sleepTimeSeconds", 0) or 0) / 3600, 1)
        deep_sleep  = round((dto.get("deepSleepSeconds", 0) or 0) / 3600, 1)
        light_sleep = round((dto.get("lightSleepSeconds", 0) or 0) / 3600, 1)
        rem_sleep   = round((dto.get("remSleepSeconds", 0) or 0) / 3600, 1)
        awake_mins  = round((dto.get("awakeSleepSeconds", 0) or 0) / 60, 0)

    # HRV
    hrv_weekly_avg = hrv_last_night = 0; hrv_status = None
    hd = cget(f'/hrv-service/hrv/{date_str}') or {}
    if hd:
        hs = hd.get("hrvSummary", {}) or {}
        hrv_weekly_avg = hs.get("weeklyAvg", 0) or 0
        hrv_last_night = hs.get("lastNight", 0) or 0
        hrv_status     = hs.get("status")

    # 呼吸数
    resp_avg = resp_min = resp_max = 0
    rd = cget(f'/wellness-service/wellness/daily/respiration/{date_str}') or {}
    if rd:
        resp_avg = rd.get("avgWakingRespirationValue", 0) or 0
        resp_min = rd.get("lowestRespirationValue", 0) or 0
        resp_max = rd.get("highestRespirationValue", 0) or 0

    # VO2 Max
    vo2_max = fitness_age = 0
    mm = cget(f'/metrics-service/metrics/maxmet/daily/{USER_UUID}',
              params={'fromDate': date_str, 'toDate': date_str}) or {}
    if mm:
        g = mm.get("generic", {}) or {}
        vo2_max     = g.get("vo2MaxPreciseValue", 0) or g.get("vo2MaxValue", 0) or 0
        fitness_age = g.get("fitnessAge", 0) or 0

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

    print(f"  歩数:{steps} 距離:{distance_km}km 消費:{active_cal}kcal BB:{bb_morning}→{bb_recent} 睡眠:{sleep_score}点 VO2:{vo2_max}")

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
    if bb_recent  is not None: e["bbEvening"] = bb_recent
    if bb_lowest  is not None: e["bbMin"]     = bb_lowest
    if bb_highest is not None: e["bbMax"]     = bb_highest
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
    if weight_kg:       e["weightKg"]     = weight_kg
    if bmi:             e["bmi"]          = bmi
    if body_fat_pct:    e["bodyFat"]      = body_fat_pct
    if muscle_mass:     e["muscleMass"]   = muscle_mass
    if bone_mass:       e["boneMass"]     = bone_mass
    if body_water:      e["bodyWater"]    = body_water
    if visceral_fat:    e["visceralFat"]  = visceral_fat
    if metabolic_age:   e["metabolicAge"] = metabolic_age

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


# ===== ログイン（優先順位: クッキー > ~/.garth/ > garthトークン > メール/パスワード）=====
client = None

if GARMIN_COOKIES:
    print("[sync_garmin] ブラウザクッキーでログイン中...")
    USE_COOKIES = setup_cookies_from_secret(GARMIN_COOKIES)

# macOS: ~/.garth/ にトークンがあればgarthで認証（自動更新対応）
if not USE_COOKIES and sys.platform == 'darwin':
    _garth_dir = Path.home() / '.garth'
    if _garth_dir.exists():
        try:
            import garth as _garth_mod
            _garth_mod.client.load(str(_garth_dir))
            USE_GARTH = True
            garth_email = _garth_mod.client.username or ""
            print(f"[sync_garmin] ~/.garth/ からgarthトークンロード成功")
        except Exception as _ge:
            print(f"[sync_garmin] ~/.garth/ ロード失敗: {_ge}")

if not USE_COOKIES and not USE_GARTH and GARMIN_TOKEN:
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

# ===== Git commit & push (macOS自動同期時) =====
if sys.platform == 'darwin':
    import subprocess as _git_sp
    _repo = DATA_FILE.parent
    try:
        # 変更があるか確認
        _status = _git_sp.run(
            ['git', 'status', '--porcelain', 'data.json'],
            capture_output=True, text=True, cwd=_repo
        )
        if _status.stdout.strip():
            # pull --rebase して最新に合わせてからpush
            _git_sp.run(['git', 'pull', '--rebase', '--autostash'], cwd=_repo, capture_output=True)
            _git_sp.run(['git', 'add', 'data.json'], cwd=_repo, check=True)
            _today = target_dates[0].isoformat()
            _git_sp.run(
                ['git', 'commit', '-m', f'chore: sync garmin data {_today}'],
                cwd=_repo, check=True
            )
            _push = _git_sp.run(['git', 'push'], cwd=_repo, capture_output=True, text=True)
            if _push.returncode == 0:
                print("[sync_garmin] GitHubにpush完了")
            else:
                print(f"[sync_garmin] push失敗: {_push.stderr.strip()}")
        else:
            print("[sync_garmin] data.jsonに変更なし（push不要）")
    except Exception as _ge:
        print(f"[sync_garmin] git操作エラー: {_ge}")
