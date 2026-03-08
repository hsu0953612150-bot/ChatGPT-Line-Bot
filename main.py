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

# 從環境變數讀取
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TAVILY_KEY = os.getenv('TAVILY_API_KEY')

# 核心指令：要求 AI 必須使用搜尋到的真實 URL
SYSTEM_PROMPT = """你是一個 OpenClaw 風格的專業助手。
你記得使用者住在淡水。當使用者要求搜尋或圖片時：
1. 必須先從提供的搜尋結果中提取網址。
2. 禁止編造網址，若連結打不開請告知原因。
3. 優先選擇以 .jpg 或 .png 結尾的圖片連結。"""

memory = Memory(system_message=SYSTEM_PROMPT, memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

# 強化搜尋與圖片抓取函數
def tavily_agent_search(query):
    if not TAVILY_KEY: return "搜尋 API 未配置。"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_KEY, 
        "query": query, 
        "search_depth": "smart",
        "include_images": True, # 強制抓取圖片連結
        "max_results": 3
    }
    try:
        response = requests.post(url, json=payload, timeout=12).json()
        
        # 提取文字結果
        text_results = [f"🔗 {r['title']}\n網址: {r['url']}" for r in response.get('results', [])]
        
        # 提取圖片結果
        images = [f"🖼️ 圖片連結: {img}" for img in response.get('images', [])]
        
        final_info = "\n\n".join(text_results + images)
        return final_info if final_info else "未找到相關有效連結。"
    except:
        return "連網功能暫時不穩定。"

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
            msg = TextSendMessage(text="記憶已清空。")
        else:
            # 偵測搜尋意圖
            if any(k in text for k in ['搜尋', '查', '找', '活動', '照片', '圖片']):
                search_data = tavily_agent_search(text)
                text = f"【最新搜尋數據】：\n{search_data}\n\n【請依據數據回答】：{text}"

            memory.append(user_id, 'user', text)
            is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
            
            if is_successful:
                role, res_text = get_role_and_content(response)
                msg = TextSendMessage(text=res_text)
                memory.append(user_id, role, res_text)
            else:
                msg = TextSendMessage(text="OpenAI 回應失敗，請檢查 Key。")
    except Exception:
        msg = TextSendMessage(text="系統繁忙，請稍後再試。")
        
    line_bot_api.reply_message(event.reply_token, msg)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
