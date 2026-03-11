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
# 這些變數必須在 Render 的 Environment 頁面中設定正確
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

# --- 2. 初始化各項服務客戶端 ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# 初始化 Gemini 辨識引擎
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 使用穩定版模型名稱，避免 404 錯誤
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

# 簡易對話快取（解決大G記憶與重複對話問題）
chat_histories = {}

@app.route("/", methods=['GET'])
def index():
    return "大G 全能模式：GPT-3.5 + Gemini Vision + Tavily 聯網版已上線", 200

# 寫入 Google 試算表邏輯
def write_to_sheet(action_name):
    try:
        # 檢查 JSON 是否完整包含花括號
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CREDENTIALS_JSON.strip().startswith('{'):
            print("Error: GOOGLE_CREDENTIALS 格式不正確")
            return False
            
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).worksheet("Commands")
        sheet.append_row(["pending", action_name, str(datetime.datetime.now())])
        return True
    except Exception as e:
        print(f"Sheet Write Failed: {e}")
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

# --- 3. 處理文字訊息 (對話 + 聯網搜尋) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # 特殊指令：識別音樂
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 收到！大G 正在透過雲端進行音樂識別..."))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 Render 的 JSON 憑證內容。"))
        return

    # Tavily 聯網搜尋 (解決天氣與即時問題)
    search_context = ""
    try:
        search_res = tavily_client.search(query=user_text, max_results=3)
        search_context = "\n".join([f"參考資料: {r['content']}" for r in search_res['results']])
    except:
        search_context = "暫時無法聯網獲取資訊。"

    # 對話記憶處理
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    
    # 建立 Prompt
    messages = [
        {"role": "system", "content": f"你是住在淡水的大G助手。請根據以下資訊回答問題：\n{search_context}"},
        *chat_histories[user_id][-4:], # 保留最近 4 則對話
        {"role": "user", "content": user_text}
    ]
    
    try:
        response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply = response.choices[0].message.content
        
        # 存入記憶
        chat_histories[user_id].append({"role": "user", "content": user_text})
        chat_histories[user_id].append({"role": "assistant", "content": reply})
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 目前思考中，請稍後再試。"))

# --- 4. 處理圖片訊息 (Gemini 視覺辨識) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not GOOGLE_API_KEY:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 請先在 Render 設定 GOOGLE_API_KEY。"))
        return
        
    try:
        # 下載 LINE 圖片
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join(message_content.iter_content())
        
        # 使用 Gemini 1.5 Flash 辨識
        res = vision_model.generate_content([
            {"mime_type": "image/jpeg", "data": image_data},
            "請詳細用繁體中文描述這張圖片裡的內容。"
        ])
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
    except Exception as e:
        # 捕捉模型 404 或 Key 錯誤
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"圖片識別錯誤：{str(e)}"))

if __name__ == "__main__":
    # Render 預設使用 10000 埠位
    app.run(host='0.0.0.0', port=10000)
