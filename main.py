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
    return "大G 全能視覺與搜尋系統已上線", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 核心 1：圖片視覺解析 (GPT-4o Vision) ---
def analyze_image(image_bytes):
    if not OPENAI_KEY: return "⚠️ 未偵測到 OpenAI Key。"
    
    # 將圖片轉為 Base64 格式
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    
    # 針對你的截圖內容優化 Prompt
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "你是住淡水的大G。請分析這張圖片，如果是物品（如鞋子）請識別品牌型號；如果是單據請讀取金額日期。請以親切的語氣回覆。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    }
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30).json()
        return res['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ 視覺解析異常：{str(e)}"

# --- 核心 2：聯網搜尋 (Tavily) ---
def search_web(query):
    if not TAVILY_KEY: return "⚠️ 未偵測到 Tavily Key。"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY,
        "query": f"淡水 {query}",
        "search_depth": "advanced",
        "include_images": True
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        # 提取結果連結
        results = [f"🔗 {r['title']}\n{r['url']}" for r in response.get('results', [])]
        return "【即時搜尋報告】：\n\n" + "\n\n".join(results[:3]) if results else "❌ 搜尋不到相關資料。"
    except:
        return "❌ 搜尋服務暫時無法連線。"

# --- 處理圖片訊息 (調用相機/相簿權限後產生的訊息) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    # 下載圖片位元組
    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = message_content.content
    
    # 調用視覺解析
    reply_text = analyze_image(image_bytes)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# --- 處理文字訊息 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    # 1. 指令：清除記憶
    if user_text == "/清除":
        reply = "記憶已清空，大G 重新待命。"
    # 2. 判斷搜尋需求
    elif any(k in user_text for k in ['搜尋', '找', '美食', '照片']):
        reply = search_web(user_text)
    # 3. 一般對話 (包含地址紀錄)
    else:
        headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "你是住淡水的大G。如果用戶提供地址，請回覆『收到，已為您記錄淡水居住地：[地址]』"},
                {"role": "user", "content": user_text}
            ]
        }
        try:
            res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data).json()
            reply = res['choices'][0]['message']['content']
        except:
            reply = f"您好！我是大G。您可以傳送照片讓我辨識，或說「搜尋淡水美食」！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
