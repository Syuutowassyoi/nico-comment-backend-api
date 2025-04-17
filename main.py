from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta, timezone
import requests
import json
import os
import xml.etree.ElementTree as ET
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_FILE = "comment_log.json"
JST = timezone(timedelta(hours=9))

# Google Sheets 保存関数
def save_to_spreadsheet(time_str, count):
    try:
        creds_info = json.loads(os.getenv("GCP_CREDENTIALS_JSON"))
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )

        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()

        spreadsheet_id = os.getenv("SPREADSHEET_ID")
        sheet_name = os.getenv("SHEET_NAME")

        utc_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        body = {
            "values": [[utc_time_str, count]]
        }

        result = sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:B",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()

        print(f"✅ スプレッドシートに書き込み成功: {result}")
    except Exception as e:
        print(f"❌ スプレッドシート保存エラー: {e}")

# コメント数取得関数（XMLパース版）
def fetch_comment_count():
    url = "https://ext.nicovideo.jp/api/getthumbinfo/sm125732"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    res = requests.get(url, headers=headers)
    print("✅ レスポンス status:", res.status_code)
    print("✅ レスポンス content:", res.text[:300])  # デバッグ用に先頭300文字だけ表示

    if res.status_code != 200:
        raise Exception(f"API request failed: {res.status_code}")

    try:
        root = ET.fromstring(res.content)
        comment_num = root.find(".//comment_num")
        if comment_num is None:
            raise Exception("comment_num not found in XML")
        return int(comment_num.text)
    except ET.ParseError as e:
        raise Exception(f"XML parse error: {e}")

@app.get("/")
def root():
    return {"message": "Nico Comment Backend is running!"}

@app.get("/update")
def update_count():
    try:
        count = fetch_comment_count()
        time_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    log = json.load(f)
            except json.JSONDecodeError:
                log = []
        else:
            log = []

        log.append({"time": time_str, "count": count})

        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        save_to_spreadsheet(time_str, count)

        return {"status": "success", "count": count}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/data")
def get_data():
    try:
        if not os.path.exists(LOG_FILE):
            return []

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except json.JSONDecodeError:
        return {"status": "error", "message": "ログファイルが破損しています。"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def on_startup():
    try:
        await run_in_threadpool(update_count)
        print("✅ 起動時にコメント数を更新しました")
    except Exception as e:
        print(f"❌ 起動時の自動更新失敗: {e}")
