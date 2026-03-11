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

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 初始化 Gemini
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 這裡使用相容性較高的模型名稱調用
    vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text
    
    # 1. 處理音樂辨識指令 (Sheet 寫入)
    if "識別音樂" in user_text:
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
            sheet.append_row(["pending", "play_music", str(datetime.datetime.now())])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！指令已寫入雲端。"))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請確認 JSON 格式。"))
        return

    # 2. 即時搜尋與對話
    context = ""
    try:
        search = tavily_client.search(query=user_text, max_results=2)
        context = "\n".join([r['content'] for r in search['results']])
    except: pass

    # 強制 GPT 進入對話模式，避免跳針回覆
    messages = [
        {"role": "system", "content": f"你是大G，一位親切的助手。請根據以下資訊回答：\n{context}"},
        {"role": "user", "content": user_text}
    ]
    
    response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not GOOGLE_API_KEY:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 未設定 GOOGLE_API_KEY"))
        return
    
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join(message_content.iter_content())
        
        # 修正 404 錯誤：明確指定內容格式
        contents = [{"mime_type": "image/jpeg", "data": image_data}, "這是什麼？"]
        response = vision_model.generate_content(contents)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"圖片識別錯誤：{str(e)[:50]}..."))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
