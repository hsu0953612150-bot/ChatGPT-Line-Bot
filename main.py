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

# --- 基礎配置 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')

# --- 1. 雲端大腦 (Google Sheets 長期記憶) ---
def get_sheet():
    try:
        # 讀取環境變數中的 JSON 憑證
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = json.loads(os.getenv('GOOGLE_CREDENTIALS'))
        creds = Credentials.from_service_account_info(creds_json, scopes=scope)
        client = gspread.authorize(creds)
        # 開啟指定的試算表
        return client.open_by_key(os.getenv('GOOGLE_SHEET_KEY')).sheet1
    except Exception as e:
        print(f"Sheet Error: {e}")
        return None

def update_memory(key_name, value):
    sheet = get_sheet()
    if sheet:
        cell = sheet.find(key_name)
        if cell:
            sheet.update_cell(cell.row, 2, value)
        else:
            sheet.append_row([key_name, value])

# --- 2. 視覺與媒體分析 (GPT-4o Vision) ---
def analyze_media(content_bytes):
    if not OPENAI_KEY: return "⚠️ 大G 尚未連接 OpenAI 視覺大腦。"
    base64_image = base64.b64encode(content_bytes).decode('utf-8')
    
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "你是住淡水的大G。請分析圖片內容，如果是商品請找型號，如果是收據請讀取金額，並以親切口吻回覆。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }]
    }
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30).json()
        return res['choices'][0]['message']['content']
    except:
        return "❌ 視覺解析出了一點問題，請稍後再試。"

# --- 3. 即時聯網監控 ---
def web_monitor_search(query):
    if not TAVILY_KEY: return "⚠️ 聯網監控功能尚未開啟。"
    url = "https://api.tavily.com/search"
    # 加入特定語法確保搜尋結果在地化
    payload = {
        "api_key": TAVILY_KEY,
        "query": f"台灣 淡水 {query} 最新消息",
        "search_depth": "advanced",
        "max_results": 3
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        results = [f"📌 {r['title']}\n{r['url']}" for r in response.get('results', [])]
        return "【大G 即時監控報告】：\n\n" + "\n\n".join(results) if results else "❌ 暫時查無最新動態。"
    except:
        return "❌ 網路搜尋異常。"

# --- 4. LINE 路由處理 ---

@app.route("/", methods=['GET'])
def home():
    return "大G 全能監控系統運作中", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    reply_text = analyze_media(message_content.content)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    if user_text == "/清除":
        update_memory("address", "")
        reply = "雲端記憶已重置，大G 重新待命。"
    elif any(k in user_text for k in ["搜尋", "監控", "找"]):
        reply = web_monitor_search(user_text)
    elif "住" in user_text:
        update_memory("address", user_text) # 紀錄地址到試算表
        reply = f"🏠 收到！大G 已記下您的位置：\n{user_text}"
    else:
        # 使用 AI 進行日常對話
        headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "你是住淡水的大G。你會主動參考使用者的居住地來提供建議。"},
                {"role": "user", "content": user_text}
            ]
        }
        try:
            res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data).json()
            reply = res['choices'][0]['message']['content']
        except:
            reply = "大G 正在喝阿給湯，請稍後再跟我說話喔！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
