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

try:
    from garminconnect import Garmin
except ImportError:
    print("ERROR: garminconnect が未インストールです。")
    print("以下を実行してください: pip install garminconnect")
    import sys
    sys.exit(1)

print("=" * 50)
print("Garmin トークン取得ツール")
print("=" * 50)
print()

email    = input("Garmin メールアドレス: ").strip()
password = getpass.getpass("Garmin パスワード（入力は非表示）: ")

print()
print("ログイン中...")

try:
    client = Garmin(email, password)
    client.login()
    print("ログイン成功！")
except Exception as e:
    print(f"ログイン失敗: {e}")
    import sys
    sys.exit(1)

# トークンを一時ディレクトリに保存
tmpdir = tempfile.mkdtemp()
try:
    client.garth.dump(tmpdir)
except Exception as e:
    print(f"トークン保存エラー: {e}")
    import sys
    sys.exit(1)

# ファイルを読み込んでJSON化 → Base64エンコード
token_data = {}
for filename in os.listdir(tmpdir):
    filepath = os.path.join(tmpdir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        token_data[filename] = f.read()

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
