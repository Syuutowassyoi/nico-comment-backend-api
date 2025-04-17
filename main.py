from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta, timezone
import requests
import json
import os
import xml.etree.ElementTree as ET
import asyncio
import threading
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

# CORS対応（GitHub Pagesなどから許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_FILE = "comment_log.json"
JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = os.getenv("SHEET_NAME", "SHEET1")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# Google Sheets 接続
def get_sheet_service():
    creds_info = json.loads(os.getenv("GCP_CREDENTIALS_JSON"))
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

# 空いてる列ペアを探す（A&B, C&D, E&F...）
def find_available_column_pair(sheet):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for i in range(0, len(alphabet), 2):
        col1 = alphabet[i]
        col2 = alphabet[i+1] if i+1 < len(alphabet) else None
        if not col2:
            continue
        range_ = f"{SHEET_NAME}!{col1}:{col1}"
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=range_).execute()
        row_count = len(result.get("values", []))
        if row_count < 18000:
            return col1, col2, row_count + 1
    raise Exception("すべての列が埋まっています！")

# コメント数を取得（XML）
def fetch_comment_count():
    url = "https://ext.nicovideo.jp/api/getthumbinfo/sm125732"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    res = requests.get(url, headers=headers)
    print("✅ レスポンス status:", res.status_code)
    print("✅ レスポンス content:", res.text[:300])

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

        sheet = get_sheet_service()
        col1, col2, row = find_available_column_pair(sheet)
        cell_range = f"{SHEET_NAME}!{col1}{row}:{col2}{row}"
        values = [[time_str, count]]

        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=cell_range,
            valueInputOption="RAW",
            body={"values": values}
        ).execute()

        return {"status": "success", "count": count}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/data")
def get_data():
    try:
        sheet = get_sheet_service()
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        entries = []

        for i in range(0, len(alphabet), 2):
            col1 = alphabet[i]
            col2 = alphabet[i+1] if i+1 < len(alphabet) else None
            if not col2:
                continue
            cell_range = f"{SHEET_NAME}!{col1}:{col2}"
            result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=cell_range).execute()
            rows = result.get("values", [])
            for row in rows:
                if len(row) >= 2:
                    entries.append({"time": row[0], "count": int(row[1].replace(',', ''))})

        entries.sort(key=lambda x: x["time"])
        return entries[-30:]

    except Exception as e:
        return {"status": "error", "message": f"サーバー内部エラー: {str(e)}"}

# 自動更新処理（バックグラウンドで毎分）
def start_background_update():
    async def loop_update():
        while True:
            try:
                await run_in_threadpool(update_count)
                print("✅ 自動更新実行完了")
            except Exception as e:
                print(f"❌ 自動更新失敗: {e}")
            await asyncio.sleep(60)

    threading.Thread(target=lambda: asyncio.run(loop_update()), daemon=True).start()

@app.on_event("startup")
async def on_startup():
    try:
        await run_in_threadpool(update_count)
        print("✅ 起動時にコメント数を更新しました")
    except Exception as e:
        print(f"❌ 起動時の自動更新失敗: {e}")

    start_background_update()
