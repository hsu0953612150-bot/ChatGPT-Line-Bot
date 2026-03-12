import os
import json
import datetime
import requests
from flask import Flask, request, abort

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# AI & Search SDK
from openai import OpenAI
from tavily import TavilyClient
import google.generativeai as genai

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數 (請確保在 Render 設定中已填妥) ---
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

# 初始化 Gemini (解決 404 關鍵：明確指定版本與配置)
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 使用穩定模型名稱，不需要加 'models/' 前綴
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

@app.route("/", methods=['GET'])
def index():
    return "大G 穩定版服務運行中", 200

def write_to_sheet(action_name):
    try:
        if not GOOGLE_CREDENTIALS_JSON:
            return False
        
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # 處理 JSON 格式中可能的換行問題
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON, strict=False)
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
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 3. 處理文字訊息 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text
    
    # 指令識別
    if "識別音樂" in user_text:
        if write_to_sheet("play_music"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎵 指令已寫入雲端！"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 雲端寫入失敗，請檢查 API 權限。"))
        return

    # 聯網搜尋 (Tavily)
    search_context = ""
    if TAVILY_API_KEY:
        try:
            search_res = tavily_client.search(query=user_text, max_results=2)
            search_context = "\n".join([r['content'] for r in search_res['results']])
        except:
            search_context = "（目前無法獲取即時網路資訊）"

    # OpenAI 回答
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": f"你是大G。參考資料：\n{search_context}\n請用繁體中文回答。"},
                {"role": "user", "content": user_text}
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"大G 遇到了一點問題：{str(e)}"))

# --- 4. 處理圖片訊息 (Gemini Vision) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not GOOGLE_API_KEY:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 尚未配置 GOOGLE_API_KEY"))
        return
        
    try:
        # 下載圖片
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(message_content.iter_content())
        
        # 準備圖片格式
        image_parts = [
            {
                "mime_type": "image/jpeg",
                "data": image_bytes
            }
        ]
        
        # 呼叫 Gemini 1.5 Flash
        response = vision_model.generate_content([
            "請詳細用繁體中文描述這張圖片的內容。", 
            image_parts[0]
        ])
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Gemini Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別錯誤：系統暫時無法分析圖片。"))

if __name__ == "__main__":
    # 使用 Render 要求的 Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
