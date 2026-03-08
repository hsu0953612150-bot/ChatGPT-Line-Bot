import os
import requests
import base64
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# 配置金鑰
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')

@app.route("/", methods=['GET'])
def index():
    return "大G 全能視覺系統已就緒 (Port 10000)", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 視覺解析功能：讓大G 看懂圖片 ---
def analyze_image_with_openai(image_bytes):
    if not OPENAI_KEY: return "⚠️ 未設定 OpenAI Key，無法解析圖片。"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "你是一位住在淡水的專業助手大G。請詳細描述這張圖片的內容。如果是收據或電費單，請提取上面的金額、日期與地址。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    }
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30).json()
        return res['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ 圖片解析失敗：{str(e)}"

# --- 聯網搜尋功能 ---
def search_tavily(query):
    if not TAVILY_KEY: return "⚠️ 未設定搜尋 Key。"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY,
        "query": f"淡水 {query}",
        "search_depth": "advanced",
        "include_images": True,
        "max_results": 5
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        results = [f"🔗 {r['title']}\n{r['url']}" for r in response.get('results', [])]
        images = [f"📸 圖片：{img}" for img in response.get('images', []) if img.startswith('http')]
        return "【大G 搜尋報告】：\n\n" + "\n\n".join(results[:3] + images[:2]) if results else "❌ 找不到結果。"
    except:
        return "❌ 搜尋異常。"

# --- 智能對話功能 ---
def chat_with_ai(user_msg):
    if not OPENAI_KEY: return "你好！我是淡水大G。請設定 OpenAI Key 以啟用對話。"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    data = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "你是住淡水的大G，口吻親切有禮。你會記住使用者的淡水地址並協助生活瑣事。"},
            {"role": "user", "content": user_msg}
        ]
    }
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data).json()
        return res['choices'][0]['message']['content']
    except:
        return "大G 正在思考中..."

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = message_content.content
    reply_text = analyze_image_with_openai(image_bytes)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    if user_text == "/清除":
        reply = "記憶已清空，大G 重新待命。"
    elif any(k in user_text for k in ['搜尋', '找', '照片', '美食']):
        reply = search_tavily(user_text)
    else:
        reply = chat_with_ai(user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
