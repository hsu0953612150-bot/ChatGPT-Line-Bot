import os
import json
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
from tavily import TavilyClient  # 新增 Tavily
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 環境變數讀取 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY') # 確保 Render 有這個變數
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 簡易記憶
chat_histories = {}

def write_to_sheet(action_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except: return False

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # 1. 識別音樂指令
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 正在為您識別音樂..."))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 JSON 格式"))
        return

    # 2. Tavily 搜尋
    try:
        search_result = tavily_client.search(query=user_text, max_results=3)
        context = "\n".join([r['content'] for r in search_result['results']])
    except:
        context = "無法取得即時資訊。"

    # 3. GPT 回答 (帶入搜尋結果)
    if user_id not in chat_histories: chat_histories[user_id] = []
    
    messages = [
        {"role": "system", "content": f"你是大G，住在淡水。請參考以下最新資訊回答：\n{context}"},
        *chat_histories[user_id][-5:],
        {"role": "user", "content": user_text}
    ]
    
    response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    reply = response.choices[0].message.content
    
    chat_histories[user_id].append({"role": "user", "content": user_text})
    chat_histories[user_id].append({"role": "assistant", "content": reply})
    
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
