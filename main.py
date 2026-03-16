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
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDENTIALS') # 必須是完整 JSON 字串

# --- 2. 初始化服務 ---
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
openai_client = OpenAI(api_key=OPENAI_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)

# 關鍵修復：強制指定 v1 版本，徹底解決日誌中的 404 NOT_FOUND 錯誤
gemini_client = genai.Client(api_key=GOOGLE_KEY, http_options={'api_version': 'v1'})

# --- 3. 記憶讀取 (從試算表) ---
def fetch_user_memory(uid):
    """讀取 UserMemory 分頁內容"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # 處理 JSON 格式
        creds_dict = json.loads(GOOGLE_CREDS.replace('\\n', '\n').strip(), strict=False)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 存取你在截圖中展示的 UserMemory 表格
        wks = client.open_by_key(SHEET_KEY).worksheet("UserMemory")
        records = wks.get_all_records()
        memos = [f"{r['Key']}: {r['Value']}" for r in records if str(r['UserID']) == str(uid)]
        return "\n".join(memos) if memos else "目前無存檔資料。"
    except Exception as e:
        print(f"Sheet Access Error: {e}")
        return "記憶庫讀取失敗。"

# --- 4. LINE 事件處理 ---
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

    # 1. 抓取長期記憶 (確保大G不會再說「無法存取個人資訊」)
    memory_context = fetch_user_memory(uid)
    
    # 2. 透過 Tavily 搜尋聯網資訊 (解決查到錯誤地點天氣的問題)
    search_query = user_text
    if "天氣" in user_text and ("淡水" in memory_context or "淡水" in user_text):
        search_query = f"淡水今日天氣"
    
    web_info = ""
    try:
        # 使用你還有額度的 Tavily
        search_res = tavily_client.search(query=search_query, max_results=2)
        web_info = "\n".join([r['content'] for r in search_res['results']])
    except:
        pass

    # 3. 組合背景給 OpenAI
    system_prompt = (
        f"你是大G。目前時間：{datetime.datetime.now()}\n"
        f"【使用者長期記憶】：\n{memory_context}\n\n"
        f"【聯網即時資訊】：\n{web_info}\n"
        "請根據上述背景回答。若記憶中有住址，請表現出你記得對方的樣子。"
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
    """這才是真正負責「看圖」的 Gemini 1.5 Flash 引擎"""
    try:
        msg_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(msg_content.iter_content())
        
        # 呼叫 Gemini 進行視覺分析
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                "請用繁體中文詳細描述這張圖片。"
            ]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        # 解決之前的 404 或金鑰設定報錯
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片識別暫時失效，請確認 Google API 金鑰設定。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
