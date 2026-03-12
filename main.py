import os
import json
import datetime
from flask import Flask, request, abort

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# AI & Search
from openai import OpenAI
from tavily import TavilyClient
import google.generativeai as genai

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

# --- 2. 初始化服務 ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 短期記憶存儲 (UserID: [messages])
session_storage = {}

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 3. 記憶功能函式 ---

def get_sheet_connection(sheet_name):
    """建立 Google Sheet 連接"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON.replace('\n', '').strip())
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_KEY).worksheet(sheet_name)

def fetch_long_term_memory(user_id):
    """從 UserMemory 分頁獲取長期記憶"""
    try:
        wks = get_sheet_connection("UserMemory")
        records = wks.get_all_records()
        user_notes = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(user_id)]
        return "\n".join(user_notes) if user_notes else "尚無個人資料。"
    except Exception as e:
        print(f"Memory Fetch Error: {e}")
        return "記憶讀取失敗。"

def save_long_term_memory(user_id, key, value):
    """存入長期記憶"""
    try:
        wks = get_sheet_connection("UserMemory")
        wks.append_row([str(user_id), key, value, str(datetime.datetime.now())])
        return True
    except:
        return False

# --- 4. 路由與事件處理 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # [主動記憶功能]
    if user_text.startswith("記住"):
        try:
            # 格式：記住 地址是淡水
            content = user_text.replace("記住", "").strip()
            key, value = content.split("是")
            if save_long_term_memory(user_id, key.strip(), value.strip()):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 記住了！{key} 是 {value}"))
            return
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 格式錯誤。請用：記住 [項目]是[內容]"))
            return

    # [提取長期記憶]
    long_term_memory = fetch_long_term_memory(user_id)

    # [聯網搜尋優化]
    search_context = ""
    search_query = user_text
    # 如果對話中提到「天氣」或「我家」且記憶中有地址，自動補齊地點
    if ("天氣" in user_text or "家" in user_text) and "淡水" in long_term_memory:
        search_query = f"淡水 {user_text}"
    
    try:
        search_res = tavily_client.search(query=search_query, max_results=2)
        search_context = "\n".join([r['content'] for r in search_res['results']])
    except:
        search_context = "暫時無法聯網。"

    # [短期記憶處理]
    if user_id not in session_storage:
        session_storage[user_id] = []
    
    # 組合 Prompt
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【使用者的長期記憶】：\n{long_term_memory}\n\n"
        f"【最新網路資訊】：\n{search_context}\n"
        f"請參考上述資訊並結合對話脈絡回覆，保持親切。"
    )

    messages = [{"role": "system", "content": system_prompt}]
    # 加上最近 5 則歷史訊息
    messages.extend(session_storage[user_id][-5:])
    messages.append({"role": "user", "content": user_text})

    try:
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply_content = response.choices[0].message.content
        
        # 儲存到短期記憶
        session_storage[user
