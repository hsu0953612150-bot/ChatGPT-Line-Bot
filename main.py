from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
import os, requests
from src.models import OpenAIModel
from src.memory import Memory
from src.storage import Storage, FileStorage
from src.utils import get_role_and_content

load_dotenv('.env')
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
storage = Storage(FileStorage('db.json'))

# 智能體設定：賦予搜尋權限
system_msg = "你是一個具備聯網能力的 AI 智能體。若使用者詢問最新資訊、天氣或需要查證的事實，你會參考搜尋結果並給出準確回答。"
memory = Memory(system_message=system_msg, memory_message_count=10)
model_management = {}

# --- 搜尋功能函數 ---
def google_search(query):
    api_key = os.getenv('TAVILY_API_KEY')
    if not api_key: return "搜尋功能尚未配置 Key。"
    url = "https://api.tavily.com/search"
    payload = {"api_key": api_key, "query": query, "search_depth": "smart"}
    try:
        response = requests.post(url, json=payload).json()
        results = [f"標題: {r['title']}\n內容: {r['content']}" for r in response['results'][:3]]
        return "\n\n".join(results)
    except: return "暫時無法連接搜尋引擎。"

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
        if text.startswith('/註冊'):
            api_key = text[3:].strip()
            model_management[user_id] = OpenAIModel(api_key=api_key)
            storage.save({user_id: api_key})
            msg = TextSendMessage(text='註冊成功！搜尋之手已準備就緒。')
        elif text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='記憶已清空。')
        else:
            if user_id not in model_management:
                msg = TextSendMessage(text='請先註冊 API Key')
            else:
                # 偵測是否需要搜尋
                if any(k in text for k in ['找', '查', '搜尋', '最新', '天氣', '新聞', '2026']):
                    search_result = google_search(text)
                    text = f"根據以下搜尋結果回答問題：\n{search_result}\n\n使用者問題：{text}"

                memory.append(user_id, 'user', text)
                is_successful, response, error_message = model_management[user_id].chat_completions(memory.get(user_id), "gpt-3.5-turbo")
                role, response_text = get_role_and_content(response)
                msg = TextSendMessage(text=response_text)
                memory.append(user_id, role, response_text)
    except Exception as e:
        msg = TextSendMessage(text='大G 正在處理數據中...')
        
    line_bot_api.reply_message(event.reply_token, msg)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
