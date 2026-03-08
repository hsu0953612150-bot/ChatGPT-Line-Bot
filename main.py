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

# 從環境變數讀取，不再寫死在代碼中以防失效
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 智能體核心設定
system_msg = "你是一個先進的 AI 智能體。你記得使用者住在淡水。回答搜尋結果時必須附上網頁連結。"
memory = Memory(system_message=system_msg, memory_message_count=15)
model = OpenAIModel(api_key=OPENAI_KEY)

def google_search(query):
    if not TAVILY_KEY: return "搜尋功能未配置。"
    url = "https://api.tavily.com/search"
    payload = {"api_key": TAVILY_KEY, "query": query, "search_depth": "smart"}
    try:
        response = requests.post(url, json=payload).json()
        results = [f"標題: {r['title']}\n網址: {r['url']}\n內容: {r['content']}" for r in response['results'][:3]]
        return "\n\n".join(results)
    except: return "搜尋引擎連線失敗。"

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
            # 判斷搜尋意圖
            if any(k in text for k in ['找', '查', '搜尋', '最新', '天氣']):
                search_data = google_search(text)
                text = f"參考資料：\n{search_data}\n\n根據以上資料回答並附上連結：{text}"

            memory.append(user_id, 'user', text)
            # 使用 GPT-3.5-Turbo 以節省額度並保持速度
            is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
            
            if is_successful:
                role, res_text = get_role_and_content(response)
                msg = TextSendMessage(text=res_text)
                memory.append(user_id, role, res_text)
            else:
                msg = TextSendMessage(text=f"OpenAI 回報錯誤，請檢查 Render 的 API Key 設定。")
                
    except Exception as e:
        msg = TextSendMessage(text="系統繁忙，請稍後再試。")
        
    line_bot_api.reply_message(event.reply_token, msg)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
