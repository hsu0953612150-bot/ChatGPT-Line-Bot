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

# 環境變數讀取
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 智能體核心指令：要求必須檢查即時資訊
SYSTEM_PROMPT = """你是一個 OpenClaw 自主智能體。
你住在淡水，擁有長效記憶。
當使用者詢問活動、天氣、新聞或任何需要最新數據的問題時，你必須優先參考提供的搜尋結果。
如果搜尋結果存在，請結合結果回答並列出參考網址。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

def google_search(query):
    if not TAVILY_KEY: return "搜尋 API 未配置。"
    url = "https://api.tavily.com/search"
    # 增加搜尋深度以獲得更準確的 2026 年資訊
    payload = {"api_key": TAVILY_KEY, "query": query, "search_depth": "smart", "max_results": 5}
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        results = [f"【{r['title']}】\n來源: {r['url']}\n內容: {r['content']}" for r in response.get('results', [])]
        return "\n\n".join(results) if results else "未找到相關即時資訊。"
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
        # 強制偵測搜尋意圖：包含「搜尋」、「找」、「活動」、「今天」等關鍵字
        if any(k in text for k in ['搜尋', '找', '查', '活動', '天氣', '最新', '推薦']):
            search_info = google_search(text)
            text = f"【即時聯網數據】\n{search_info}\n\n【使用者需求】：{text}"

        memory.append(user_id, 'user', text)
        # 使用支援視覺與長邏輯的 gpt-4o-mini
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="OpenAI 連線異常，請檢查 Key 設定。"))
    except Exception:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="智能體模組重整中..."))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
