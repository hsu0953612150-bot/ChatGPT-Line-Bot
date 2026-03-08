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

# 環境變數設定
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# OpenClaw 核心提示詞：嚴禁虛構網址
SYSTEM_PROMPT = """你是一個具備實時聯網能力的 OpenClaw 智能體。
你住在淡水。當你需要提供連結或圖片時：
1. 必須從【搜尋數據】中精確提取原始 URL。
2. 嚴禁使用 example.com 或任何想像的網址。
3. 若搜尋結果中沒有 JPG 連結，請誠實告知並提供文章來源網址。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

# 強化搜尋函數：確保抓取真實圖片與連結
def tavily_power_search(query):
    if not TAVILY_KEY: return "搜尋 API 未設定。"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY, 
        "query": query, 
        "search_depth": "smart", 
        "include_images": True, 
        "max_results": 5
    }
    try:
        response = requests.post(url, json=payload, timeout=15).json()
        results = [f"【{r['title']}】\n內容：{r['content']}\n網址：{r['url']}" for r in response.get('results', [])]
        images = [f"📸 真實圖片網址：{img}" for img in response.get('images', [])]
        return "\n\n".join(results + images)
    except: return "檢索連線超時。"

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
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="記憶已清空，大G 重新待命。"))
            return

        # 搜尋意圖深度鎖定
        search_keywords = ['搜尋', '找', '照片', '連結', '活動', '今天']
        if any(k in text for k in search_keywords):
            # 自動補充地理位置資訊
            query = f"淡水 {text}" if "淡水" not in text else text
            search_data = tavily_power_search(query)
            # 強迫 AI 在回答前讀取真實數據
            text = f"【搜尋到的真實數據如下】：\n{search_data}\n\n根據上述數據，回答使用者的需求：{text}"

        memory.append(user_id, 'user', text)
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
    except Exception:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="核心系統重整中..."))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
