#!/usr/bin/env python3
"""
Garminのログイン情報を一度だけ入力してトークンを保存するスクリプト。
このスクリプトを一度実行すれば、以後は自動でトークンが更新され
パスワードなしでデータ同期が動くようになります。

実行方法:
  python3 scripts/setup_garth.py
"""

import sys
import getpass
from pathlib import Path

try:
    import garth
except ImportError:
    print("garthをインストール中...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "garth", "-q"])
    import garth

GARTH_DIR = Path.home() / ".garth"

def main():
    print("=" * 50)
    print("Garmin Connect 初期セットアップ")
    print("=" * 50)
    print()
    print("GarminアカウントのメールアドレスとパスワードをMFAコードを入力してください。")
    print("入力内容はこのMacにのみ保存され、GitHubには送られません。")
    print()

    email = input("メールアドレス: ").strip()
    password = getpass.getpass("パスワード: ")

    print()
    print("ログイン中...")

    try:
        garth.login(email, password)
        garth.save(str(GARTH_DIR))
        print()
        print(f"成功！トークンを {GARTH_DIR} に保存しました。")
        print("以後、sync_garmin.py は自動でこのトークンを使います。")
        print("トークンは定期的に自動更新されるので、再ログインは不要です。")
    except Exception as e:
        print(f"ログイン失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
