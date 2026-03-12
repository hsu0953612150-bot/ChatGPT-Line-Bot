import os
import json
import datetime
from flask import Flask, request, abort

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# AI & Search SDK
from openai import OpenAI
from tavily import TavilyClient
import google.generativeai as genai

# Google Sheets 相關
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

# 短期對話記憶 (UserID: [messages])
session_storage = {}

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 確保使用穩定模型名稱
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 3. 記憶功能函式 ---

def get_sheet_connection(sheet_name):
    """建立 Google Sheet 連接"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # 處理可能的換行字元
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON.replace('\n', '\\n').strip(), strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_KEY).worksheet(sheet_name)

def fetch_long_term_memory(user_id):
    """從 UserMemory 分頁獲取該用戶的長期記憶"""
    try:
        wks = get_sheet_connection("UserMemory")
        records = wks.get_all_records()
        user_notes = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(user_id)]
        return "\n".join(user_notes) if user_notes else "尚無個人資料紀錄。"
    except Exception as e:
        print(f"Fetch Memory Error: {e}")
        return "記憶讀取暫時失效。"

def save_long_term_memory(user_id, key, value):
    """將使用者的個人資訊存入 Google Sheet"""
    try:
        wks = get_sheet_connection("UserMemory")
        wks.append_row([str(user_id), key, value, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Save Memory Error: {e}")
        return False

# --- 4. 路由與事件處理 ---

@app.route("/", methods=['GET'])
def index():
    return "大G 記憶加強版已啟動", 200

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
    # 範例指令：記住地址是淡水
    if user_text.startswith("記住"):
        try:
            content = user_text.replace("記住", "").strip()
            key, value = content.split("是", 1) # 只切分第一個「是」
            if save_long_term_memory(user_id, key.strip(), value.strip()):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 好的，大G 記住了：{key.strip()} 是 {value.strip()}"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 記憶寫入失敗，請檢查權限。"))
            return
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 格式錯誤。請輸入：記住 [項目]是[內容]"))
            return

    # [提取長期記憶與聯網搜尋]
    long_term_memory = fetch_long_term_memory(user_id)
    search_context = ""
    search_query = user_text
    
    # 根據記憶自動補強搜尋關鍵字 (例如問天氣時自動補上住址)
    if ("天氣" in user_text or "家" in user_text) and "淡水" in long_term_memory:
        search_query = f"淡水 {user_text}"
    
    try:
        search_res = tavily_client.search(query=search_query, max_results=2)
        search_context = "\n".join([r['content'] for r in search_res['results']])
    except:
        search_context = "暫時無法獲取網路資訊。"

    # [短期記憶管理]
    if user_id not in session_storage:
        session_storage[user_id] = []
    
    # 組合給 OpenAI 的 Prompt
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【你對該用戶的長期記憶】：\n{long_term_memory}\n\n"
        f"【相關網路資訊】：\n{search_context}\n"
        f"請參考上述背景與過去對話，用親切的繁體中文回答。"
    )

    messages = [{"role": "system", "content": system_prompt}]
    # 加上最近 5 則歷史對話 (短期記憶)
    messages.extend(session_storage[user_id][-5:])
    messages.append({"role": "user", "content": user_text})

    try:
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply_content = response.choices[0].message.content
        
        # 儲存到短期記憶字典中
        session_storage[user_id].append({"role": "user", "content": user_text})
        session_storage[user_id].append({"role": "assistant", "content": reply_content})
        # 限制記憶長度，避免內存佔用過高
        session_storage[user_id] = session_storage[user_id][-10:]
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_content))
    except Exception as e:
        print(f"AI Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在忙碌。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not GOOGLE_API_KEY:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 尚未配置 Gemini API Key"))
        return
        
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(message_content.iter_content())
        
        # 修正後的 Gemini 呼叫格式，解決 404 問題
        response = vision_model.generate_content([
            "請用繁體中文詳細描述圖片內容。",
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Gemini Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別錯誤：{str(e)}"))

if __name__ == "__main__":
    # Render 環境預設使用 10000 Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
