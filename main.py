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

# --- 硬核設定：直接鎖定你的 API Key ---
# 請將下方的 sk-xxxx 換成你真正的 OpenAI Key
MY_OPENAI_KEY = "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"

# 智能體設定
system_msg = "你是一個先進的 AI 智能體。你記得使用者住在淡水，且對 2026 年市場規劃有深入了解。回答搜尋結果時必須附上連結。"
memory = Memory(system_message=system_msg, memory_message_count=10)

# 初始化模型
global_model = OpenAIModel(api_key=MY_OPENAI_KEY)

def google_search(query):
    tavily_key = os.getenv('TAVILY_API_KEY')
    if not tavily_key: return "搜尋功能未配置。"
    url = "https://api.tavily.com/search"
    payload = {"api_key": tavily_key, "query": query, "search_depth": "smart"}
    try:
        response = requests.post(url, json=payload).json()
        results = [f"標題: {r['title']}\n網址: {r['url']}\n內容: {r['content']}" for r in response['results'][:3]]
        return "\n\n".join(results)
    except: return "無法連接搜尋引擎。"

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
        if text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='記憶已重置。')
        else:
            # 偵測搜尋意圖
            if any(k in text for k in ['找', '查', '搜尋', '最新', '推薦']):
                search_data = google_search(text)
                text = f"參考資料：\n{search_data}\n\n根據以上資料回答問題：{text}"

            memory.append(user_id, 'user', text)
            # 使用我們鎖定的 global_model
            is_successful, response, error_message = global_model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
            
            if is_successful:
                role, response_text = get_role_and_content(response)
                msg = TextSendMessage(text=response_text)
                memory.append(user_id, role, response_text)
            else:
                msg = TextSendMessage(text=f"連線失敗: {error_message}")
                
    except Exception as e:
        msg = TextSendMessage(text='大G 正在重新連線，請稍後再試。')
        
    line_bot_api.reply_message(event.reply_token, msg)

@app.route("/", methods=['GET'])
def home():
    return 'Hello World'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
