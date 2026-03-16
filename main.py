import os
import json
import datetime
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

from openai import OpenAI
from tavily import TavilyClient
from google import genai 
from google.genai import types

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數 ---
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_KEY = os.environ.get('TAVILY_API_KEY') # 負責聯網搜尋
GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY') # 負責圖片辨識
SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDENTIALS')

# --- 2. 初始化客戶端 ---
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
openai_client = OpenAI(api_key=OPENAI_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)
# 修正重點：強制使用穩定版 v1，避免截圖中的 404 錯誤
gemini_client = genai.Client(api_key=GOOGLE_KEY, http_options={'api_version': 'v1'})

# --- 3. 記憶存取功能 ---
def fetch_memory_from_sheet(uid):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = json.loads(GOOGLE_CREDS.replace('\n', '\\n').strip(), strict=False)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        wks = gspread.authorize(creds).open_by_key(SHEET_KEY).worksheet("UserMemory")
        records = wks.get_all_records()
        notes = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(uid)]
        return "\n".join(notes) if notes else "無個人偏好紀錄。"
    except: return "記憶系統連線中。"

# --- 4. 訊息處理邏輯 ---
@app.route("/callback", methods=['POST'])
def callback():
    sig = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try: handler.handle(body, sig)
    except: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    uid = event.source.user_id
    text = event.message.text

    # 1. 讀取長期記憶
    user_context = fetch_memory_from_sheet(uid)
    
    # 2. 最佳化搜尋關鍵字 (如果記憶有淡水，問天氣時自動補上)
    search_query = text
    if "天氣" in text and "淡水" in user_context:
        search_query = f"淡水 {text}"
    
    web_info = ""
    try:
        # 使用 Tavily 進行聯網搜尋
        search_res = tavily_client.search(query=search_query, max_results=2)
        web_info = "\n".join([r['content'] for r in search_res['results']])
    except: web_info = "暫無即時網路資訊。"

    # 3. 組合 Prompt (解決 AI 聲稱沒記憶的問題)
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【使用者長期記憶】：\n{user_context}\n\n"
        f"【網路參考資訊】：\n{web_info}\n"
        "請根據上述資訊回答。如果記憶中有相關地點或偏好，請表現出你記得對方的樣子。"
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=resp.choices[0].message.content))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在努力思考中..."))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """真正處理圖片辨識的區塊"""
    try:
        content = line_bot_api.get_message_content(event.message.id)
        img_bytes = b"".join(content.iter_content())
        
        # 呼叫 Gemini 1.5 Flash 進行視覺分析
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                "請用繁體中文詳細描述圖片內容。"
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片識別暫時失效，請確認 Google API 金鑰設定。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
