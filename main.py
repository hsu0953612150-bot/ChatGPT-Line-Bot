from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
import os, requests
from src.models import OpenAIModel
from src.memory import Memory
from src.utils import get_role_and_content

load_dotenv('.env')
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 從 Render 環境變數讀取
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 核心指令：要求 AI 絕對不可虛構網址
SYSTEM_PROMPT = """你是一個專業的自主智能體秘書。
你記得使用者住在淡水。當使用者詢問最新活動或連結時：
1. 必須使用提供的搜尋數據，絕對禁止自行編造網址。
2. 優先提供來自台灣 (.tw) 的官方或新聞連結。
3. 如果搜尋不到有效連結，請誠實告知，不要提供無效的網址。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

# 強化版聯網搜尋函數
def google_search(query):
    if not TAVILY_KEY: return "搜尋功能未配置。"
    url = "https://api.tavily.com/search"
    # 加入 site:.tw 限制，確保連結對台灣使用者有效
    payload = {
        "api_key": TAVILY_KEY, 
        "query": f"{query} site:.tw", 
        "search_depth": "smart",
        "max_results": 5
    }
    try:
        response = requests.post(url, json=payload, timeout=12).json()
        results = []
        for r in response.get('results', []):
            # 格式化輸出：標題 + 完整網址
            results.append(f"🔗 {r['title']}\n{r['url']}")
        
        return "\n\n".join(results) if results else "找不到相關的即時有效連結。"
    except Exception:
        return "搜尋引擎連線超時，請稍後再試。"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    
    try:
        if text == "/清除":
            memory.remove(user_id)
            msg = TextSendMessage(text="記憶已清空")
        else:
            # 偵測搜尋意圖
            search_keywords = ['搜尋', '找', '查', '連結', '活動', '優惠', '最新']
            if any(k in text for k in search_keywords):
                # 如果關鍵字包含淡水，則直接搜尋；否則自動補上淡水
                query = text if "淡水" in text else f"淡水 {text}"
                search_data = google_search(query)
                text = f"【即時搜尋結果】：\n{search_data}\n\n【請根據以上資料回答】：{text}"

            memory.append(user_id, 'user', text)
            # 使用支援視覺與長邏輯的 gpt-4o-mini
            is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
            
            if is_successful:
                role, res_text = get_role_and_content(response)
                msg = TextSendMessage(text=res_text)
                memory.append(user_id, role, res_text)
            else:
                msg = TextSendMessage(text="OpenAI 連線不穩定，請檢查 API Key 餘額或設定。")
                
    except Exception:
        msg = TextSendMessage(text="系統重整中，請輸入 /清除 後再試。")
        
    line_bot_api.reply_message(event.reply_token, msg)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
