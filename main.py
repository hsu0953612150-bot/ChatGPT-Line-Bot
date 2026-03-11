import os
import json
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 2. Gemini AI 設定 (包含搜尋與記憶) ---
genai.configure(api_key=GOOGLE_API_KEY)
# 使用 gemini-1.5-flash 兼顧速度與圖片處理
model = genai.GenerativeModel('gemini-1.5-flash')
# 建立對話記憶體
chat_sessions = {}

# --- 3. Google Sheets 寫入功能 (手機遙控) ---
def write_to_sheet(action_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 確認分頁名稱為 Commands
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Sheet Error: {e}")
        return False

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. 處理文字訊息 (搜尋、記憶、遙控指令) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # [手機遙控模式]
    if "識別音樂" in user_text or "辨識音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 指令已送達雲端！手機正在啟動音樂識別，請稍候。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 Google Sheets 權限。"))
        return

    # [AI 搜尋與記憶模式]
    try:
        # 如果是新用戶，開啟新的對話 Session 實現記憶功能
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        response = chat.send_message(user_text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"AI 暫時無法回應，請稍後再試。原因: {e}"))

# --- 5. 處理圖片訊息 (恢復看圖功能) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        # 取得 LINE 傳來的圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        
        # 視覺分析
        contents = [
            {"mime_type": "image/jpeg", "data": image_data},
            "這張圖片裡有什麼？請詳細說明。"
        ]
        response = model.generate_content(contents)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌ 圖片識別發生錯誤：{e}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
