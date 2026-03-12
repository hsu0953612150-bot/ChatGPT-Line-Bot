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
import google.generativeai as genai  # 改回目前的 SDK 名稱

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

# 初始化 Gemini
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 使用穩定模型名稱，避免 v1beta 404 錯誤
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

@app.route("/", methods=['GET'])
def index():
    return "大G 穩定版已啟動", 200

def write_to_sheet(action_name):
    try:
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CREDENTIALS_JSON.startswith('{'):
            return False
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON.replace('\n', '').strip())
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Sheet Error: {e}")
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
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 指令已寫入雲端！"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 JSON 格式。"))
        return

    # 聯網搜尋
    search_context = ""
    try:
        search_res = tavily_client.search(query=user_text, max_results=2)
        search_context = "\n".join([r['content'] for r in search_res['results']])
    except:
        search_context = "暫時無法聯網。"

    try:
        messages = [
            {"role": "system", "content": f"你是大G。參考資料：\n{search_context}"},
            {"role": "user", "content": user_text}
        ]
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在忙碌。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not GOOGLE_API_KEY:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 缺少 GOOGLE_API_KEY"))
        return
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join(message_content.iter_content())
        
        # 穩定版 Gemini 呼叫方式
        response = vision_model.generate_content([
            "請詳細用繁體中文描述這張圖片。",
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別錯誤：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
