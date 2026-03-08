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

# 環境變數配置
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# OpenClaw 核心：要求 AI 必須使用聯網工具
SYSTEM_PROMPT = """你是一個 OpenClaw 風格的自主智能體秘書。
你記得使用者住在淡水。當問題涉及「活動」、「優惠」、「最新消息」或「圖片」時：
1. 你必須先參考提供的搜尋數據。
2. 回答時請具體列出時間、地點，並附上參考連結。
3. 若使用者要求圖片，請在回答中包含搜尋到的 JPG 網址。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

# 搜尋驅動函數
def tavily_search(query):
    if not TAVILY_KEY: return "搜尋功能未配置 API Key。"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY, 
        "query": query, 
        "search_depth": "smart",
        "include_images": True # 同時抓取相關圖片網址
    }
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        results = []
        for r in response.get('results', []):
            results.append(f"【{r['title']}】\n網址: {r['url']}\n摘要: {r['content']}")
        
        # 抓取搜尋到的圖片
        images = response.get('images', [])
        image_str = "\n\n相關圖片連結:\n" + "\n".join(images[:2]) if images else ""
        
        return "\n\n".join(results) + image_str
    except:
        return "搜尋引擎暫時無法連線。"

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
        # 自主判斷是否需要啟動「搜尋任務」
        search_triggers = ['活動', '優惠', '推薦', '搜尋', '找', '照片', '圖片']
        if any(k in text for k in search_triggers):
            # 針對地理位置優化搜尋
            search_query = f"淡水 {text}" if "淡水" not in text else text
            search_data = tavily_search(search_query)
            text = f"【即時檢索到的資訊如下】：\n{search_data}\n\n【使用者原始要求】：{text}"

        memory.append(user_id, 'user', text)
        # 使用支援視覺理解的模型
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 正在讀取資料中..."))
    except Exception:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請稍後再試。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
