import os
import requests
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# 配置 LINE 與 Tavily 金鑰
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')

@app.route("/", methods=['GET'])
def index():
    return "大G 核心系統穩定運行中", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 強化的 Tavily 搜尋函數
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
        if not results: return "❌ 暫時找不到相關資訊。"
        return "【即時搜尋結果】：\n\n" + "\n\n".join(results[:3] + images[:2])
    except:
        return "❌ 搜尋連線異常。"

# 新增：OpenAI 對話處理（處理地址、生活瑣事）
def chat_with_ai(user_msg):
    if not OPENAI_KEY: return "你好！我是住淡水的大G，目前純對話功能尚未設定完成，請使用「搜尋」功能。"
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    data = {
        "model": "gpt-3.5-turbo", # 或 gpt-4
        "messages": [
            {"role": "system", "content": "你是住淡水的大G，說話口吻親切。如果使用者提到地址或電費，請告訴他們你會記住地址，但目前無法直接查詢台電即時電費。"},
            {"role": "user", "content": user_msg}
        ]
    }
    try:
        res = requests.post(url, headers=headers, json=data).json()
        return res['choices'][0]['message']['content']
    except:
        return "大G 思考中，請稍後再試。"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    
    # 1. 處理清空指令
    if user_text == "/清除":
        reply_content = "記憶已清空，大G 重新待命。"
    # 2. 判斷是否為搜尋需求
    elif any(k in user_text for k in ['搜尋', '找', '照片', '美食', '活動']):
        reply_content = search_tavily(user_text)
    # 3. 其他所有對話交給 AI 處理，不再跳重複提示
    else:
        reply_content = chat_with_ai(user_text)

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_content))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
