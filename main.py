import os
import json
import datetime
from flask import Flask, request, abort

# LINE & AI SDKs
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
from openai import OpenAI
from tavily import TavilyClient
from google import genai  # 最新版 Google AI SDK
from google.genai import types

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 讀取環境變數 ---
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_KEY = os.environ.get('TAVILY_API_KEY') # 這是搜尋用的
GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY') # 這是辨識圖片用的
SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDENTIALS')

# --- 2. 初始化客戶端 ---
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
openai_client = OpenAI(api_key=OPENAI_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)

# 修正 404 的關鍵：明確指定 api_version='v1'
gemini_client = genai.Client(api_key=GOOGLE_KEY, http_options={'api_version': 'v1'})

# 短期記憶快取
session_storage = {}

# --- 3. 記憶功能函式 ---
def fetch_memory(uid):
    """從 UserMemory 分頁讀取記憶"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = json.loads(GOOGLE_CREDS.replace('\n', '\\n').strip(), strict=False)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        wks = gspread.authorize(creds).open_by_key(SHEET_KEY).worksheet("UserMemory")
        records = wks.get_all_records()
        memos = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(uid)]
        return "\n".join(memos) if memos else "目前無相關紀錄。"
    except: return "記憶庫讀取失敗。"

# --- 4. 處理對話與圖片 ---
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
    
    # 讀取長期記憶
    long_term_mem = fetch_memory(uid)

    # Tavily 聯網搜尋邏輯
    search_q = text
    if "天氣" in text and "淡水" in long_term_mem:
        search_q = f"淡水 {text}"
    
    web_info = ""
    try:
        res = tavily_client.search(query=search_q, max_results=2)
        web_info = "\n".join([r['content'] for r in res['results']])
    except: web_info = "無法搜尋網路。"

    # 組合 Prompt 給 OpenAI
    sys_prompt = (
        f"你是大G。目前對該使用者的記憶：\n{long_term_mem}\n\n"
        f"網路資訊：\n{web_info}\n"
        "請用親切的繁體中文回答。"
    )

    # 呼叫 OpenAI 產生回答
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 思考中..."))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """這部分才是真正的圖片辨識功能"""
    try:
        # 下載圖片
        content = line_bot_api.get_message_content(event.message.id)
        img_data = b"".join(content.iter_content())
        
        # 呼叫 Gemini 進行辨識 (非 Tavily)
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=img_data, mime_type="image/jpeg"),
                "請用繁體中文詳細描述這張圖片。"
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        # 解決截圖中出現的 404 報錯
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別失敗，請確認 GOOGLE_API_KEY 是否正確。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
