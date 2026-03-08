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

# 從環境變數讀取
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
memory = Memory(system_message="你是一個全能智能體，具備視覺分析與聯網搜尋能力。你記得使用者住在淡水。", memory_message_count=10)
model = OpenAIModel(api_key=OPENAI_KEY)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 處理文字訊息 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    try:
        memory.append(user_id, 'user', text)
        # 升級至 gpt-4o-mini，速度快且支援視覺
        is_successful, response, error_message = model.chat_completions(memory.get(user_id), "gpt-4o-mini")
        if is_successful:
            role, res_text = get_role_and_content(response)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_text))
            memory.append(user_id, role, res_text)
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大G 思考中，請稍候..."))

# --- 處理圖片訊息 (視覺之眼) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    message_content = line_bot_api.get_message_content(event.message.id)
    
    # 將圖片轉為 Base64 格式傳給 OpenAI
    base64_image = base64.b64encode(message_content.content).decode('utf-8')
    
    try:
        headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "請問這張圖片裡面有什麼？請詳細描述。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload).json()
        description = response['choices'][0]['message']['content']
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=description))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="我看到了圖片，但目前解析有點問題..."))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
