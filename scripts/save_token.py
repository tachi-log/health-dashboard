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
    import garth
except ImportError:
    print("ERROR: garth が未インストールです。")
    print("以下を実行してください: pip3 install garth --break-system-packages")
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
    garth.login(email, password, prompt_mfa=get_mfa_code)
    print("ログイン成功！")
except Exception as e:
    print(f"ログイン失敗: {e}")
    sys.exit(1)

# garthトークンを一時ディレクトリに保存
tmpdir = tempfile.mkdtemp()
try:
    garth.client.dump(tmpdir)
    print(f"トークン保存完了: {os.listdir(tmpdir)}")
except Exception as e:
    print(f"トークン保存エラー: {e}")
    sys.exit(1)

# ファイルを読み込んでJSON化 → Base64エンコード
token_data = {}
for filename in os.listdir(tmpdir):
    filepath = os.path.join(tmpdir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        token_data[filename] = f.read()

if not token_data:
    print("エラー: トークンファイルが生成されませんでした")
    sys.exit(1)

# メールも保存（API呼び出し時に使用）
token_data['_email'] = email

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
print("（既存のGARMIN_TOKENを「Update secret」で上書きしてください）")
print("=" * 50)
