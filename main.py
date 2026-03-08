import os, requests
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# 從 Render 環境變數讀取金鑰
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 確認首頁是否正常（用來測試 Render 是否活著）
@app.route("/", methods=['GET'])
def index():
    return "Bot is running!", 200

# 核心：LINE Webhook 入口
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    # 增加日誌紀錄，方便在 Render 監測
    app.logger.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Check your Channel Secret.")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return 'Error', 500
    return 'OK'

def search_tavily(query):
    if not TAVILY_KEY:
        return "搜尋 API Key 未設定。"
    
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY,
        "query": query,
        "search_depth": "smart",
        "include_images": True,
        "max_results": 3
    }
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        results = [f"✅ {r['title']}\n{r['url']}" for r in res.get('results', [])]
        images = [f"🖼️ 圖片：{img}" for img in res.get('images', [])]
        return "\n\n".join(results + images) if results else "未找到結果。"
    except:
        return "搜尋引擎連線失敗。"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    
    # 如果提到搜尋相關關鍵字，直接呼叫 Tavily
    if any(k in user_text for k in ['搜尋', '找', '活動', '照片', '連結']):
        # 自動加上淡水作為地點優化
        query = f"淡水 {user_text}" if "淡水" not in user_text else user_text
        reply = f"【即時搜尋結果】：\n\n{search_tavily(query)}"
    else:
        # 這裡可以接回你的 OpenAI 模型，或者簡單回應
        reply = "你好！我可以幫你搜尋淡水的最新活動或照片，請輸入「搜尋」試試看。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    # Render 會自動設定 PORT 變數，預設為 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
