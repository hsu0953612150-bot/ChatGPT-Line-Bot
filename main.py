import os
import json
import time
import gspread
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()
app = Flask(__name__)

# --- 1. 基礎配置 (請確保 Render 的 Environment Variables 已設定) ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# --- 2. 核心功能：寫入手機代理指令到 Google Sheets ---
def trigger_phone_proxy(action_code):
    try:
        # 設定 Google Sheets 存取權限
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = json.loads(os.getenv('GOOGLE_CREDENTIALS'))
        creds = Credentials.from_service_account_info(creds_json, scopes=scope)
        client = gspread.authorize(creds)
        
        # 開啟名為 Commands 的工作表
        sheet = client.open_by_key(os.getenv('GOOGLE_SHEET_KEY')).worksheet("Commands")
        
        # 依照你的表格標題：status(A1), action(B1), timestamp(C1) 寫入資料
        # 寫入：待處理(pending), 指令動作, 目前時間戳記
        sheet.append_row(["pending", action_code, str(int(time.time()))])
        return True
    except Exception as e:
        print(f"Google Sheets 寫入失敗: {e}")
        return False

# --- 3. 路由設定 (修正日誌中的 404 錯誤) ---

@app.route("/", methods=['GET'])
def home():
    # 建立根目錄路由，讓 Render 的健康檢查 (HEAD/GET /) 能回傳 200 而非 404
    return "大G 全能代理系統：運作中", 200

@app.route("/callback", methods=['POST'])
def callback():
    # 處理來自 LINE 的 Webhook 訊息
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. 訊息處理邏輯 ---

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    # 識別「幫我」開頭的代理指令
    if "幫我" in user_text:
        if any(k in user_text for k in ["音樂", "歌曲", "識別"]):
            # 觸發手機端的音樂識別或播放動作
            if trigger_phone_proxy("play_music"):
                reply = "🎵 指令已送達雲端！大G 正在透過手機代理為您處理音樂任務。"
            else:
                reply = "❌ 寫入指令失敗，請檢查 Google Sheets 權限與設定。"
        elif "導航" in user_text or "地圖" in user_text:
            # 觸發手機端的導航動作
            if trigger_phone_proxy("open_navigation"):
                reply = "🗺️ 沒問題！手機代理正在為您規劃回淡水的路線。"
            else:
                reply = "❌ 雲端同步失敗。"
        else:
            reply = "大G 收到指令，但我還在學習如何讓手機執行這項特定任務喔！"
    else:
        # 一般 AI 對話回應
        reply = "我是大G，今天有什麼想讓手機幫你完成的事嗎？"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    # Render 預設使用 port 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
