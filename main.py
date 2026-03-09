import os
import requests
import base64
import json
import gspread
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage)
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# 配置 LINE 與 API 金鑰
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')

# --- 1. 長期記憶系統 (Google Sheets) ---
def get_sheet():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = json.loads(os.getenv('GOOGLE_CREDENTIALS'))
        creds = Credentials.from_service_account_info(creds_json, scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_key(os.getenv('GOOGLE_SHEET_KEY')).sheet1
    except:
        return None

def save_memory(user_key, value):
    sheet = get_sheet()
    if sheet:
        cell = sheet.find(user_key)
        if cell:
            sheet.update_cell(cell.row, 2, value)
        else:
            sheet.append_row([user_key, value])

# --- 2. 視覺與影片分析 (GPT-4o Vision) ---
def analyze_media(content_bytes, mode="image"):
    if not OPENAI_KEY: return "⚠️ 未設定 OpenAI Key。"
    base64_data = base64.b64encode(content_bytes).decode('utf-8')
    prompt = "你是住淡水的大G。請詳細分析內容，如果是鞋子請識別型號；如果是單據請讀取金額。" if mode == "image" else "請根據影片截圖分析這是什麼曲目或場景。"
    
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}}
            ]
        }]
    }
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload).json()
        return res['choices'][0]['message']['content']
    except:
        return "❌ 媒體解析失敗。"

# --- 3. 即時聯網監控搜尋 ---
def search_and_monitor(query):
    if not TAVILY_KEY: return "⚠️ 未設定 Tavily Key。"
    url = "https://api.tavily.com/search"
    # 自動補強關鍵字，避免出現 example 連結
    payload = {
        "api_key": TAVILY_KEY,
        "query": f"台灣 淡水 {query} 最新實時資訊",
        "search_depth": "advanced",
        "max_results": 3
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        results = [f"🔗 {r['title']}\n{r['url']}" for r in response.get('results', [])]
        if not results: return "❌ 目前網路上沒有更新的即時資訊。"
        return "【大G 實時監控報告】：\n\n" + "\n\n".join(results)
    except:
        return "❌ 網路監控連線異常。"

# --- LINE 訊息處理器 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    msg_content = line_bot_api.get_message_content(event.message.id)
    result = analyze_media(msg_content.content)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    if user_text == "/清除":
        save_memory("last_address", "") # 清除 Google Sheets 中的紀錄
        reply = "記憶已在雲端清空，大G 重新待命。"
    elif "搜尋" in user_text or "監控" in user_text:
        reply = search_and_monitor(user_text)
    elif "住" in user_text:
        save_memory("last_address", user_text) # 將地址存入長期記憶
        reply = f"收到！大G 已將您的居住地記在雲端資料庫：\n{user_text}"
    else:
        # 一般對話交給 AI
        headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
        data = {
            "model": "gpt-4o",
            "messages": [{"role": "system", "content": "你是住淡水的大G，語氣專業且幽默。"}, {"role": "user", "content": user_text}]
        }
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data).json()
        reply = res['choices'][0]['message']['content']

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
