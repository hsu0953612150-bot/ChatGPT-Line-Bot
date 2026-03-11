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
import google.generativeai as genai

app = Flask(__name__)

# --- 1. 環境變數讀取 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

# --- 2. 初始化客戶端 ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

chat_histories = {}

@app.route("/", methods=['GET'])
def index():
    return "大G 已準備就緒！", 200

def write_to_sheet(action_name):
    try:
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CREDENTIALS_JSON.strip().startswith('{'):
            return False
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
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
    signature = request.headers['X-Signature'] if 'X-Signature' in request.headers else request.headers.get('X-Line-Signature')
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

    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！指令已寫入。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗。"))
        return

    search_context = ""
    try:
        search_res = tavily_client.search(query=user_text, max_results=3)
        search_context = "\n".join([r['content'] for r in search_res['results']])
    except:
        search_context = "無法取得即時資訊。"

    if user_id not in chat_histories:
        chat_histories[user_id] = []
    
    messages = [
        {"role": "system", "content": f"你是大G。參考資訊：\n{search_context}"},
        *chat_histories[user_id][-4:],
        {"role": "user", "content": user_text}
    ]
    
    try:
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply = response.choices[0].message.content
        chat_histories[user_id].append({"role": "user", "content": user_text})
        chat_histories[user_id].append({"role": "assistant", "content": reply})
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在忙碌中。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join(message_content.iter_content())
        res = vision_model.generate_content([
            {"mime_type": "image/jpeg", "data": image_data},
            "請詳細描述這張圖片。"
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別失敗：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
