#!/usr/bin/env python3
"""
ChromeのクッキーDBからGarminセッションクッキーを自動取得する。
macOS専用。Chromeが開いていても動作する。
"""

import os
import sys
import json
import sqlite3
import shutil
import tempfile
import subprocess
import base64

CHROME_COOKIES_PATH = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome/Default/Cookies"
)
GARMIN_HOST = "connect.garmin.com"


def get_chrome_key():
    """macOSキーチェーンからChromeの暗号化キーを取得する"""
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-a", "Chrome", "-s", "Chrome Safe Storage"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError("Chromeの暗号化キーをキーチェーンから取得できませんでした")
    return result.stdout.strip()


def decrypt_cookie(encrypted_value, key_str):
    """Chromeのクッキー値を復号する (v10/v11)"""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pycryptodome", "-q"])
        from Crypto.Cipher import AES
    import hashlib

    if isinstance(encrypted_value, str):
        encrypted_value = encrypted_value.encode()

    prefix = encrypted_value[:3]
    if prefix not in (b'v10', b'v11'):
        if isinstance(encrypted_value, bytes):
            return encrypted_value.decode('utf-8', errors='replace')
        return encrypted_value

    # PBKDF2 でキーを派生
    dk = hashlib.pbkdf2_hmac('sha1', key_str.encode(), b'saltysalt', 1003, dklen=16)
    payload = encrypted_value[3:]
    iv = b' ' * 16
    cipher = AES.new(dk, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(payload)

    # PKCS7パディング除去
    padding = decrypted[-1]
    if 1 <= padding <= 16:
        result = decrypted[:-padding]
    else:
        result = decrypted

    # クッキー値は印字可能ASCII(0x20-0x7e)のみで構成される。
    # 先頭の非印字バイト（AES復号アーティファクト）を読み飛ばす。
    # 先頭64バイト以内で最後に出現した非印字バイトの直後から始める。
    last_garbage = -1
    for i in range(min(64, len(result))):
        if result[i] < 0x20 or result[i] > 0x7e:
            last_garbage = i
    if last_garbage >= 0:
        result = result[last_garbage + 1:]

    return result.decode('utf-8', errors='replace')


def get_garmin_cookies():
    """Garmin Connect用のクッキーをChromeから取得して辞書で返す"""
    if not os.path.exists(CHROME_COOKIES_PATH):
        raise FileNotFoundError(f"Chrome Cookiesファイルが見つかりません: {CHROME_COOKIES_PATH}")

    # DBはChromeが掴んでいることが多いのでコピーして読む
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(CHROME_COOKIES_PATH, tmp)

    try:
        key = get_chrome_key()
        conn = sqlite3.connect(tmp)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
            (f"%{GARMIN_HOST}%",)
        )
        rows = cursor.fetchall()
        conn.close()
    finally:
        os.unlink(tmp)

    cookies = {}
    for name, enc_val in rows:
        try:
            val = decrypt_cookie(enc_val, key)
            if val:
                cookies[name] = val
        except Exception:
            pass

    return cookies


def get_garmin_cookies_b64():
    """クッキーをbase64エンコードして返す（GitHub Secret用）"""
    cookies = get_garmin_cookies()
    # 重要なクッキーだけ抽出
    important = ['session', 'SESSIONID', 'JWT_WEB', 'GARMIN-SSO',
                 'GARMIN-SSO-CUST-GUID', '__cflb', '_cfuvid']
    filtered = {k: v for k, v in cookies.items() if k in important and v}
    # 全部も保存（フォールバック用）
    filtered['_all'] = '; '.join(f'{k}={v}' for k, v in cookies.items() if v)
    return base64.b64encode(json.dumps(filtered).encode()).decode()


def build_cookie_header(cookies_b64):
    """base64クッキーからCookieヘッダー文字列を作成"""
    data = json.loads(base64.b64decode(cookies_b64).decode())
    all_cookies = data.get('_all', '')
    if all_cookies:
        return all_cookies
    # _allがない場合は個別キーから作成（旧形式との互換性）
    parts = []
    for k, v in data.items():
        if not k.startswith('_'):
            parts.append(f'{k}={v}')
    return '; '.join(parts)


if __name__ == "__main__":
    print("ChromeからGarminクッキーを取得中...")
    try:
        b64 = get_garmin_cookies_b64()
        data = json.loads(base64.b64decode(b64).decode())
        print(f"取得成功: {len(data)-1}個のクッキー")
        print()
        print("GitHub Secret 'GARMIN_COOKIES' に登録する値:")
        print("=" * 60)
        print(b64)
        print("=" * 60)
        print()
        print("登録先: https://github.com/tachi-log/health-dashboard/settings/secrets/actions")
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)
