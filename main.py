import os
import json
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
from openai import OpenAI
from tavily import TavilyClient
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google import genai
from google.genai import types

app = Flask(__name__)

# --- 1. 環境變數讀取 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') # 務必在 Render 新增此項
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS') # 務必填入完整 JSON

# --- 2. 初始化服務 ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 初始化新版 Gemini 客戶端 (解決 404 問題)
gemini_client = None
if GOOGLE_API_KEY:
    gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

@app.route("/", methods=['GET'])
def index():
    return "大G 2026 核心系統已上線", 200

# 雲端寫入邏輯
def write_to_sheet(action_name):
    try:
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CREDENTIALS_JSON.startswith('{'):
            return False
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # 移除換行符號以防格式損壞
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON.replace('\n', '').strip())
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Sheet Write Error: {e}")
        return False

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
    user_text = event.message.text
    
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！大G 正在透過雲端進行識別..."))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗：請確認 GOOGLE_CREDENTIALS 為完整的 JSON 內容。"))
        return

    # Tavily 聯網搜尋
    search_context = ""
    try:
        search_res = tavily_client.search(query=user_text, max_results=2)
        search_context = "\n".join([r['content'] for r in search_res['results']])
    except:
        search_context = "無法取得即時資料。"

    try:
        messages = [
            {"role": "system", "content": f"你是住在淡水的大G助手。參考資訊：\n{search_context}"},
            {"role": "user", "content": user_text}
        ]
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 思考中，請稍後再試。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not gemini_client:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 尚未設定 GOOGLE_API_KEY，無法辨識圖片。"))
        return
        
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(message_content.iter_content())
        
        # 呼叫 2026 最新 Gemini 模型
        response = gemini_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                '請用繁體中文詳細描述這張圖片。'
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"圖片識別錯誤：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
