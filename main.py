from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageSendMessage)
import os
import uuid
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
memory = Memory(system_message=os.getenv('SYSTEM_MESSAGE'), memory_message_count=2)
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
            msg = TextSendMessage(text='註冊成功')
        elif text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='歷史訊息清除成功')
        else:
            if user_id not in model_management:
                msg = TextSendMessage(text='請先註冊，格式：/註冊 sk-xxxx')
            else:
                user_model = model_management[user_id]
                memory.append(user_id, 'user', text)
                is_successful, response, error_message = user_model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
                if not is_successful:
                    raise Exception(error_message)
                role, response = get_role_and_content(response)
                msg = TextSendMessage(text=response)
                memory.append(user_id, role, response)
    except Exception as e:
        msg = TextSendMessage(text='執行出錯，請重新輸入 /清除 後再試一次')
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
        print("尚未有資料庫檔案，跳過載入")
    app.run(host='0.0.0.0', port=8080)
