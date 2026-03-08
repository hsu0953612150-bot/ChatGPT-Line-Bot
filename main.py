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

# 環境變數
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 智能體核心提示詞：強制要求參考檢索數據
SYSTEM_PROMPT = """你是一個具備連網能力的 OpenClaw 智能體。
你住在淡水。當你的輸入訊息中包含『【即時檢索數據】』時，你必須：
1. 深入閱讀數據內容，不可直接說找不到。
2. 提取網址並以 Markdown 格式 [標題](網址) 呈現。
3. 若數據中包含 JPG 連結，請直接列出。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

def tavily_search(query):
    if not TAVILY_KEY: return "搜尋功能未配置。"
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
        # 整合文字與圖片數據
        results = [f"資料：{r['content']}\n來源：{r['url']}" for r in response.get('results', [])]
        images = [f"圖片：{img}" for img in response.get('images', [])]
        return "\n\n".join(results + images)
    except: return "檢索連線失敗。"

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
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="記憶已清空。"))
            return

        # 搜尋意圖偵測
        if any(k in text for k in ['搜尋', '找', '查', '活動', '照片', '最新']):
            raw_data = tavily_search(text)
            # 將原始搜尋數據直接塞入對話，強迫 AI 看到
            text = f"【即時檢索數據】：\n{raw_data}\n\n根據上述數據回答：{text}"

        memory.append(user_id, 'user', text)
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
    except Exception:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="系統重整中，請稍後。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
