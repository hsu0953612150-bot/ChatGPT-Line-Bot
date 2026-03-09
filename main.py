import os
import time
import json
import gspread
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot import (LineBotApi, WebhookHandler)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage)

app = Flask(__name__)

# --- 初始化 API ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

def get_sheet_client():
    creds_json = json.loads(os.getenv('GOOGLE_CREDENTIALS'))
    creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    return gspread.authorize(creds)

# --- 核心功能：寫入手機指令 ---
def add_phone_command(command):
    try:
        client = get_sheet_client()
        # 開啟名為 Commands 的工作表
        sheet = client.open_by_key(os.getenv('GOOGLE_SHEET_KEY')).worksheet("Commands")
        # 寫入資料：pending(待處理), 指令內容, 時間戳記
        sheet.append_row(["pending", command, str(int(time.time()))])
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    # 判斷是否為代理指令
    if "幫我" in user_text:
        if "音樂" in user_text or "歌曲" in user_text:
            if add_phone_command("play_music"):
                reply = "🎵 指令已送達雲端！手機代理即將為您辨識/播放音樂。"
            else:
                reply = "❌ 雲端同步失敗，請檢查表格設定。"
        elif "導航" in user_text or "地圖" in user_text:
            add_phone_command("open_navigation")
            reply = "🗺️ 收到！手機代理正在為您開啟導航功能。"
        else:
            reply = "大G 收到指令！目前我支持幫您操作音樂與導航任務。"
    else:
        # 一般 AI 對話邏輯
        reply = "我是住淡水的大G，有什麼我可以幫您的嗎？"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
