from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
import os
from src.models import OpenAIModel
from src.memory import Memory
from src.logger import logger
from src.storage import Storage, FileStorage
from src.utils import get_role_and_content

load_dotenv('.env')
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
storage = Storage(FileStorage('db.json'))

# 設定預設系統訊息
system_msg = os.getenv('SYSTEM_MESSAGE') or 'You are a helpful assistant.'

# --- 升級 1：長效記憶設定 ---
# 將 memory_message_count 從 2 提高到 10，讓它記得更久之前的對話
memory = Memory(system_message=system_msg, memory_message_count=10)
model_management = {}

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
    logger.info(f'{user_id}: {text}')
    
    try:
        if text.startswith('/註冊'):
            api_key = text[3:].strip()
            model = OpenAIModel(api_key=api_key)
            model_management[user_id] = model
            storage.save({user_id: api_key})
            msg = TextSendMessage(text='註冊成功！大G 已升級長效記憶。')
            
        elif text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='記憶已重置。')
            
        else:
            if user_id not in model_management:
                msg = TextSendMessage(text='請先註冊，格式：/註冊 sk-xxxx')
            else:
                user_model = model_management[user_id]
                
                # --- 升級 2：搜尋之手預備邏輯 ---
                # 如果使用者提到「找」、「查」、「搜尋」，我們可以讓模型更有感的回答
                # 注意：真正的聯網搜尋需要串接 Search API，這裡先強化模型的搜尋意識
                prompt = text
                if any(keyword in text for keyword in ['找', '查', '搜尋', '最新']):
                    prompt = f"請針對以下問題進行詳細分析，若有需要請以專業搜尋引擎的角度回答：{text}"

                memory.append(user_id, 'user', prompt)
                
                # 使用支援工具調用的模型 (GPT-4o 或維持 gpt-3.5-turbo)
                is_successful, response, error_message = user_model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
                
                if not is_successful:
                    raise Exception(error_message)
                
                role, response_text = get_role_and_content(response)
                msg = TextSendMessage(text=response_text)
                memory.append(user_id, role, response_text)
                
    except Exception as e:
        logger.error(f'Error: {str(e)}')
        msg = TextSendMessage(text='大G 正在重整記憶，請稍後或輸入 /清除')
        
    line_bot_api.reply_message(event.reply_token, msg)

@app.route("/", methods=['GET'])
def home():
    return 'Hello World'

if __name__ == "__main__":
    try:
        data = storage.load()
        for u_id in data.keys():
            model_management[u_id] = OpenAIModel(api_key=data[u_id])
    except:
        pass
    app.run(host='0.0.0.0', port=8080)
