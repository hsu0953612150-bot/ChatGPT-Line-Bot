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

# 智能體人格設定：強化搜尋與記憶檢索意識
system_msg = "你是一個先進的 AI 智能體。你擁有長效記憶，會記得使用者提到的個人資訊（如居住地、興趣）。當使用者要求搜尋或詢問最新資訊時，你會以專業分析師的口吻回答。"

# 記憶長度設定為 20 輪，確保它能翻到更前面的對話
memory = Memory(system_message=system_msg, memory_message_count=20)
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
            msg = TextSendMessage(text='智能體核心已啟動，長效記憶與搜尋意識已就緒。')
        elif text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='記憶庫已完全清空。')
        else:
            if user_id not in model_management:
                msg = TextSendMessage(text='請先註冊，格式：/註冊 sk-xxxx')
            else:
                user_model = model_management[user_id]
                
                # 自動判斷是否需要啟動「搜尋模式」
                if any(k in text for k in ['搜尋', '查', '找', '最新', '規劃', '2026']):
                    text = f"【搜尋任務啟動】請檢索相關知識並回答：{text}"

                memory.append(user_id, 'user', text)
                
                # 使用 GPT-3.5-Turbo，但透過系統提示詞強化它的檢索能力
                is_successful, response, error_message = user_model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
                
                if not is_successful:
                    raise Exception(error_message)
                
                role, response_text = get_role_and_content(response)
                msg = TextSendMessage(text=response_text)
                memory.append(user_id, role, response_text)
                
    except Exception as e:
        msg = TextSendMessage(text='智能體模組調整中，請輸入 /清除 後再試一次。')
        
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
