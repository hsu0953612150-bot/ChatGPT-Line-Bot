from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage)
import os, requests, base64
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

# --- 智能體核心提示詞 (OpenClaw 風格) ---
# 強調邏輯思維與連結提供
SYSTEM_PROMPT = """你是一個 OpenClaw 風格的自主智能體。
你住在台灣淡水，擁有長效記憶。
你的運作邏輯如下：
1. 分析問題：判斷是否需要即時數據。
2. 執行搜尋：若需要，會使用 Tavily 檢索最新資訊。
3. 整合回答：必須提供詳細分析、具體建議，並在末尾附上參考連結。
請保持專業且親切的語氣。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=15)
model = OpenAIModel(api_key=OPENAI_KEY)

# 搜尋引擎驅動
def tavily_search(query):
    if not TAVILY_KEY: return "搜尋功能未配置。"
    url = "https://api.tavily.com/search"
    payload = {"api_key": TAVILY_KEY, "query": query, "search_depth": "smart"}
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        results = [f"【{r['title']}】\n網址: {r['url']}\n摘要: {r['content'][:150]}..." for r in response['results'][:3]]
        return "\n\n".join(results)
    except Exception: return "搜尋引擎暫時斷線。"

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
        # 智能體決策：是否需要連網搜尋
        search_keywords = ['搜尋', '查', '找', '最新', '天氣', '新聞', '2026', '推薦']
        if any(k in text for k in search_keywords):
            search_context = tavily_search(text)
            text = f"【即時檢索數據】\n{search_context}\n\n【使用者原始需求】：{text}"

        memory.append(user_id, 'user', text)
        # 使用 GPT-4o-mini 提供視覺與邏輯能力
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="核心連線中，請稍後..."))
                
    except Exception:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="智能體重整中，請輸入 /清除"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
