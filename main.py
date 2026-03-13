import os
import json
import datetime
from flask import Flask, request, abort

# 導入 SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
from openai import OpenAI
from tavily import TavilyClient
from google import genai  # 使用最新版 SDK 解決 404 問題
from google.genai import types

# 導入 Google Sheets 相關
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數對接 (根據你提供的變數名稱) ---
LINE_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY')
SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
DEFAULT_MODEL = os.environ.get('DEFAULT_MODEL', 'gpt-3.5-turbo')

# --- 2. 初始化服務 ---
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
openai_client = OpenAI(api_key=OPENAI_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)
# 初始化新版 Gemini 客戶端
gemini_client = genai.Client(api_key=GOOGLE_KEY) if GOOGLE_KEY else None

# 短期記憶緩存 (UserID: [messages])
session_storage = {}

# --- 3. Google Sheets 記憶功能 ---
def get_wks(sheet_name):
    """建立與 Google Sheets 的連線"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # 處理環境變數中的 JSON 格式
    creds_dict = json.loads(GOOGLE_CREDS_JSON.replace('\n', '\\n').strip(), strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds).open_by_key(SHEET_KEY).worksheet(sheet_name)

def fetch_memory(user_id):
    """提取長期記憶"""
    try:
        wks = get_wks("UserMemory")
        records = wks.get_all_records()
        notes = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(user_id)]
        return "\n".join(notes) if notes else "無個人偏好紀錄。"
    except Exception as e:
        print(f"Memory Fetch Error: {e}")
        return "記憶系統維護中。"

def save_memory(user_id, key, value):
    """存入長期記憶"""
    try:
        wks = get_wks("UserMemory")
        wks.append_row([str(user_id), key, value, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Memory Save Error: {e}")
        return False

# --- 4. Webhook 路由 ---
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

    # [功能：主動儲存記憶] 格式：記住地址是淡水
    if user_text.startswith("記住"):
        try:
            content = user_text.replace("記住", "").strip()
            key, value = content.split("是", 1)
            if save_memory(user_id, key.strip(), value.strip()):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 大G 記住了：{key.strip()} 是 {value.strip()}"))
            return
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 格式錯誤。請用：記住 [項目]是[內容]"))
            return

    # [功能：提取長期記憶並優化搜尋]
    long_term_mem = fetch_memory(user_id)
    search_query = user_text
    # 智慧補強：若提到天氣且記憶中有地址，自動結合
    if "天氣" in user_text and "淡水" in long_term_mem:
        search_query = f"淡水 {user_text}"

    # [功能：執行聯網搜尋]
    web_info = ""
    try:
        search_res = tavily_client.search(query=search_query, max_results=2)
        web_info = "\n".join([r['content'] for r in search_res['results']])
    except:
        web_info = "無法取得即時網路資訊。"

    # [功能：管理短期記憶與生成回覆]
    if user_id not in session_storage:
        session_storage[user_id] = []
    
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【使用者的長期記憶】：\n{long_term_mem}\n\n"
        f"【網路參考資訊】：\n{web_info}\n"
        f"請參考上述資訊並結合對話脈絡回覆，保持親切。"
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(session_storage[user_id][-5:]) # 加入最近 5 輪對話
    messages.append({"role": "user", "content": user_text})

    try:
        response = openai_client.chat.completions.create(model=DEFAULT_MODEL, messages=messages)
        reply_content = response.choices[0].message.content
        
        # 更新短期記憶
        session_storage[user_id].append({"role": "user", "content": user_text})
        session_storage[user_id].append({"role": "assistant", "content": reply_content})
        session_storage[user_id] = session_storage[user_id][-10:] # 只留 10 則
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_content))
    except Exception as e:
        print(f"OpenAI Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在處理中，請稍後。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not gemini_client:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ Gemini API 未配置"))
        return
    try:
        # 下載圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(message_content.iter_content())
        
        # 使用新版 SDK 核心語法，徹底解決 404 問題
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                "請用繁體中文詳細描述圖片內容。"
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別失敗：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
