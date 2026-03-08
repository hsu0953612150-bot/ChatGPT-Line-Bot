import os
import requests
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()

app = Flask(__name__)

# 配置 LINE 與 Tavily 金鑰
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 首頁檢查點：確認 Render 服務是否在線
@app.route("/", methods=['GET'])
def index():
    return "大G 核心系統運行中 (Port 10000)", 200

# LINE Webhook 入口點
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"Callback Error: {e}")
        return 'Error', 500
    return 'OK'

# 強化的 Tavily 搜尋工具：解決「未找到結果」問題
def search_tavily(query):
    if not TAVILY_KEY:
        return "⚠️ 系統未偵測到 Tavily API Key，請檢查環境變數設定。"
    
    url = "https://api.tavily.com/search"
    
    # 自動優化關鍵字，確保針對淡水與圖片進行精準檢索
    optimized_query = f"{query} 淡水 推薦 照片" if "淡水" not in query else f"{query} 推薦 照片"
    
    payload = {
        "api_key": TAVILY_KEY,
        "query": optimized_query,
        "search_depth": "advanced", # 使用進階模式提高準確度
        "include_images": True,
        "max_results": 5
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        
        # 提取真實連結與標題
        results = [f"🔗 {r['title']}\n{r['url']}" for r in response.get('results', [])]
        
        # 提取真實圖片網址
        images = [f"📸 圖片連結：{img}" for img in response.get('images', []) if img.startswith('http')]
        
        if not results and not images:
            return "❌ 目前搜尋引擎無法找到相關即時資訊，請嘗試縮短關鍵字（例如：只輸入『淡水阿給』）。"
            
        # 組合回覆內容
        final_reply = "【大G 為您找到的即時資訊】：\n\n" + "\n\n".join(results[:3] + images[:2])
        return final_reply
        
    except Exception as e:
        return f"❌ 搜尋服務連線異常，請稍後再試。({str(e)})"

# 處理收到的 LINE 訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    
    # 搜尋觸發邏輯：只要包含關鍵字就調用 Tavily
    search_keywords = ['搜尋', '找', '活動', '照片', '連結', '美食', '景點']
    
    if any(k in user_text for k in search_keywords):
        reply_content = search_tavily(user_text)
    elif user_text == "/清除":
        reply_content = "記憶已清空，大G 重新待命。"
    else:
        # 基本對話回應，提醒使用者可以使用搜尋功能
        reply_content = f"您好！我是住在淡水的大G。您可以對我說「搜尋淡水活動」或「找阿給的照片」，我會為您抓取最新資訊！"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_content)
    )

if __name__ == "__main__":
    # 自動適應 Render 的 Port 10000 設定
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
