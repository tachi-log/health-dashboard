#!/usr/bin/env python3
"""
Garminのセッショントークンを取得してGitHub Secretに登録する文字列を出力します。
このスクリプトは自分のMacで一度だけ実行してください。
"""

import os
import json
import base64
import tempfile
import getpass
import sys

try:
    from garminconnect import Garmin
except ImportError:
    print("ERROR: garminconnect が未インストールです。")
    print("以下を実行してください: pip3 install garminconnect --break-system-packages")
    sys.exit(1)

print("=" * 50)
print("Garmin トークン取得ツール")
print("=" * 50)
print()

email    = input("Garmin メールアドレス: ").strip()
password = getpass.getpass("Garmin パスワード（入力は非表示）: ")

print()
print("ログイン中...")

def get_mfa_code():
    print()
    print("Garminから認証コードが届いています。")
    return input("認証コード（6桁）を入力してください: ").strip()

try:
    client = Garmin(email, password, prompt_mfa=get_mfa_code)
    client.login()
    print("ログイン成功！")
except Exception as e:
    print(f"ログイン失敗: {e}")
    sys.exit(1)

# セッションクッキーを保存
token_data = {}

# 方法1: requestsのセッションクッキー
try:
    if hasattr(client, 'session') and hasattr(client.session, 'cookies'):
        cookies = dict(client.session.cookies)
        if cookies:
            token_data['cookies'] = cookies
            token_data['email']   = email
            print(f"セッションクッキー取得成功: {len(cookies)} 件")
except Exception as e:
    print(f"  cookies取得スキップ: {e}")

# 方法2: curl_cffiのクッキー
try:
    if hasattr(client, 'client') and hasattr(client.client, 'cookies'):
        cffi_cookies = dict(client.client.cookies)
        if cffi_cookies:
            token_data['cffi_cookies'] = cffi_cookies
            token_data['email'] = email
            print(f"curl_cffiクッキー取得成功: {len(cffi_cookies)} 件")
except Exception as e:
    print(f"  cffi_cookies取得スキップ: {e}")

# 方法3: garthのトークン（別途インストールされている場合）
try:
    import garth
    tmpdir = tempfile.mkdtemp()
    garth.save(tmpdir)
    garth_data = {}
    for filename in os.listdir(tmpdir):
        filepath = os.path.join(tmpdir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            garth_data[filename] = f.read()
    if garth_data:
        token_data['garth'] = garth_data
        print(f"garthトークン取得成功: {list(garth_data.keys())}")
except Exception as e:
    print(f"  garth取得スキップ: {e}")

# 認証情報も保存（フォールバック用）
token_data['email']    = email
token_data['password'] = password

if len(token_data) <= 2:  # email + password のみの場合
    print("警告: セッション情報が取得できませんでした。メール/パスワードのみ保存します。")

token_json   = json.dumps(token_data)
token_base64 = base64.b64encode(token_json.encode()).decode()

print()
print("=" * 50)
print("以下の文字列をコピーして GitHub Secret に登録してください")
print("Secret 名: GARMIN_TOKEN")
print("=" * 50)
print()
print(token_base64)
print()
print("=" * 50)
print("登録先URL:")
print("https://github.com/tachi-log/health-dashboard/settings/secrets/actions/new")
print("=" * 50)
