import os, requests
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)

load_dotenv('.env')
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 這裡建議直接貼上你的 API Key 測試，或確保 Render 上的 Key 名稱正確
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# --- 核心搜尋工具：確保抓到真實數據 ---
def search_the_web(query):
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY,
        "query": query,
        "search_depth": "smart",
        "include_images": True,
        "max_results": 3
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        # 提取真實的標題與網址
        links = [f"✅ {r['title']}\n{r['url']}" for r in response.get('results', [])]
        imgs = [f"🖼️ 圖片：{img}" for img in response.get('images', [])]
        return "\n\n".join(links + imgs) if links else "搜尋引擎回傳空結果。"
    except Exception as e:
        return f"連線 Tavily 失敗：{str(e)}"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    
    # 如果訊息包含「搜尋」或「找」，強迫進入工具流程
    if any(k in user_msg for k in ['搜尋', '找', '查', '圖片', '連結']):
        real_data = search_the_web(user_msg)
        # 直接把搜尋結果回傳，繞過 AI 的幻覺
        reply_text = f"【大G 為您找到的真實連結】：\n\n{real_data}"
    else:
        reply_text = "我目前已就緒，請跟我說「搜尋淡水活動」來測試連結。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
