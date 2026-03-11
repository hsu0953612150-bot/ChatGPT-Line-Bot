import os
import json
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
from tavily import TavilyClient
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 讀取環境變數 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 簡易對話記憶體
chat_histories = {}

@app.route("/", methods=['GET'])
def index():
    return "大G 系統運行中：OpenAI + Tavily 模式", 200

# Google Sheets 寫入邏輯
def write_to_sheet(action_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # 解析完整的 JSON 憑證字串
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"!!! 試算表寫入失敗: {str(e)}")
        return False

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
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

    # [指令辨識]
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！正在透過雲端幫您辨識音樂。"))
        else:
            # 這邊會對應到截圖中的失敗訊息
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 JSON 格式與試算表權限。"))
        return

    # [Tavily 聯網搜尋]
    try:
        search = tavily_client.search(query=user_text, search_depth="advanced", max_results=3)
        context = "\n".join([f"- {r['content']}" for r in search['results']])
    except:
        context = "無法取得即時搜尋資訊。"

    # [OpenAI 對話處理]
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    
    messages = [
        {"role": "system", "content": f"你是住在淡水的大G。請參考資訊回答：\n{context}"},
        *chat_histories[user_id][-4:], # 帶入最近 4 則對話紀錄
        {"role": "user", "content": user_text}
    ]
    
    try:
        completion = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply = completion.choices[0].message.content
        
        # 存入記憶
        chat_histories[user_id].append({"role": "user", "content": user_text})
        chat_histories[user_id].append({"role": "assistant", "content": reply})
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"大G 暫時無法回應：{e}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
