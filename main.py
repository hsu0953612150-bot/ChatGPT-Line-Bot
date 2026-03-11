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

# 初始化 Gemini Vision (用於修正 404 錯誤)
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 使用 1.5-flash 作為穩定版模型
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

# 簡易對話記憶體
chat_histories = {}

@app.route("/", methods=['GET'])
def index():
    return "大G 全功能系統：GPT + Tavily + Vision + Sheets 運行中！", 200

# --- 3. 功能函式 ---
def write_to_sheet(action_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Sheet Error: {e}")
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

# --- 4. 處理文字訊息 (搜尋與對話) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # 音樂辨識指令
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！正在透過雲端幫您辨識音樂。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 寫入失敗，請檢查試算表權限。"))
        return

    # Tavily 即時搜尋
    context = ""
    try:
        search_result = tavily_client.search(query=user_text, search_depth="advanced", max_results=3)
        context = "\n".join([f"來源: {r['content']}" for r in search_result['results']])
    except:
        context = "暫時無法取得聯網資訊。"

    # 對話記憶處理
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    
    messages = [
        {"role": "system", "content": f"你是住在淡水的大G。參考資訊：\n{context}"},
        *chat_histories[user_id][-4:],
        {"role": "user", "content": user_text}
    ]
    
    try:
        completion = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply = completion.choices[0].message.content
        
        chat_histories[user_id].append({"role": "user", "content": user_text})
        chat_histories[user_id].append({"role": "assistant", "content": reply})
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 思考中，請稍後再問我。"))

# --- 5. 處理圖片訊息 (修正 404 錯誤) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        
        # 修正 404 models/gemini-1.5-flash is not found 錯誤
        contents = [
            {"mime_type": "image/jpeg", "data": image_data},
            "請詳細描述這張圖片的內容。"
        ]
        response = vision_model.generate_content(contents)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"圖片識別錯誤：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
