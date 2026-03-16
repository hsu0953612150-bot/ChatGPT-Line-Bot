import os
import json
import datetime
from flask import Flask, request, abort

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# AI 客戶端
from openai import OpenAI
from tavily import TavilyClient
from google import genai 
from google.genai import types

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- 1. 環境變數 ---
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
TAVILY_KEY = os.environ.get('TAVILY_API_KEY')
GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY')
SHEET_KEY = os.environ.get('GOOGLE_SHEET_KEY')      # 必須是試算表 ID
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDENTIALS') # 必須是完整的 JSON 字串

# --- 2. 初始化 ---
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
openai_client = OpenAI(api_key=OPENAI_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)
# 強制指定 api_version='v1' 解決 404 models/gemini-1.5-flash not found 問題
gemini_client = genai.Client(api_key=GOOGLE_KEY, http_options={'api_version': 'v1'})

# --- 3. 記憶讀取功能 ---
def get_memory(uid):
    """從 Google Sheets 分頁 UserMemory 抓取資料"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(GOOGLE_CREDS.replace('\n', '\\n').strip(), strict=False)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        wks = gspread.authorize(creds).open_by_key(SHEET_KEY).worksheet("UserMemory")
        records = wks.get_all_records()
        memos = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(uid)]
        return "\n".join(memos) if memos else "目前無相關紀錄。"
    except Exception as e:
        print(f"Sheet Error: {e}")
        return "記憶庫連線異常。"

# --- 4. 路由處理 ---
@app.route("/callback", methods=['POST'])
def callback():
    sig = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    uid = event.source.user_id
    user_text = event.message.text

    # 1. 讀取長期記憶 (解決大G說不記得住址的問題)
    long_term_memory = get_memory(uid)
    
    # 2. 結合記憶進行 Tavily 搜尋 (解決天氣查到丹佛的問題)
    search_query = user_text
    if "天氣" in user_text and "淡水" in long_term_memory:
        search_query = f"淡水今日天氣"
    
    web_info = ""
    try:
        # 使用 Tavily 搜尋即時資訊
        search_res = tavily_client.search(query=search_query, max_results=2)
        web_info = "\n".join([r['content'] for r in search_res['results']])
    except:
        pass

    # 3. 組合 Prompt 送給 OpenAI
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【使用者長期記憶】：\n{long_term_memory}\n\n"
        f"【聯網即時資訊】：\n{web_info}\n"
        "請根據記憶與聯網資訊，以親切的語氣回應用戶。若記憶中有地點，回答地點相關問題請以此為準。"
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.choices[0].message.content))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在開機中..."))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """真正負責圖片辨識的功能 (使用 Gemini)"""
    try:
        # 下載 LINE 圖片
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(message_content.iter_content())
        
        # 呼叫 Gemini 1.5 Flash 進行辨識
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                "請用繁體中文詳細描述這張圖片的內容。"
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        # 修正截圖中的識別失敗報錯
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"識別暫時失效，請確認 API 權限或金鑰。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
