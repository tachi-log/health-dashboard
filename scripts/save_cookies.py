#!/usr/bin/env python3
"""
ChromeのGarminセッションクッキーを取得してGitHub Secretに登録する文字列を出力します。
このスクリプトは自分のMacで実行してください。
"""

import json
import base64

print("=" * 50)
print("Garmin クッキー登録ツール")
print("=" * 50)
print()
print("Chrome DevTools で取得したクッキー値を貼り付けてください。")
print("（DevTools → Application → Cookies → connect.garmin.com）")
print()

session_val = input("「session」クッキーの値: ").strip()
sessionid_val = input("「SESSIONID」クッキーの値: ").strip()

if not session_val or not sessionid_val:
    print("エラー: 両方の値を入力してください")
    exit(1)

cookie_data = {
    "session": session_val,
    "SESSIONID": sessionid_val
}

encoded = base64.b64encode(json.dumps(cookie_data).encode()).decode()

print()
print("=" * 50)
print("以下の文字列をコピーして GitHub Secret に登録してください")
print("Secret 名: GARMIN_COOKIES")
print("=" * 50)
print()
print(encoded)
print()
print("=" * 50)
print("登録先URL:")
print("https://github.com/tachi-log/health-dashboard/settings/secrets/actions/new")
print("（既存のGARMIN_COOKIESがあれば「Update secret」で上書き）")
print("=" * 50)
