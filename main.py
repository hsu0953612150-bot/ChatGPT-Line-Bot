        if text.startswith('/註冊'):
            api_key = text[3:].strip()
            model = OpenAIModel(api_key=api_key)
            is_successful, _, _ = model.check_token_valid()
            if not is_successful:
                raise ValueError('Invalid API token')
            model_management[user_id] = model
            storage.save({user_id: api_key})
            msg = TextSendMessage(text='Token 有效，註冊成功')
        elif text.startswith('/指令說明'):
            msg = TextSendMessage(text="指令：\n/註冊 + API Token\n/系統訊息 + Prompt\n/清除\n/圖像 + Prompt\n語音輸入\n其他文字輸入")
        elif text.startswith('/系統訊息'):
            memory.change_system_message(user_id, text[5:].strip())
            msg = TextSendMessage(text='輸入成功')
        elif text.startswith('/清除'):
            memory.remove(user_id)
            msg = TextSendMessage(text='歷史訊息清除成功')
        elif text.startswith('/圖像'):
            prompt = text[3:].strip()
            is_successful, response, error_message = model_management[user_id].image_generations(prompt)
            if not is_successful:
                raise Exception(error_message)
            url = response['data'][0]['url']
            msg = ImageSendMessage(original_content_url=url, preview_image_url=url)
        else:
            # 這是最關鍵的對話修復區
            user_model = model_management[user_id]
            memory.append(user_id, 'user', text)
            is_successful, response, error_message = user_model.chat_completions(memory.get(user_id), "gpt-3.5-turbo")
            if not is_successful:
                raise Exception(error_message)
            role, response = get_role_and_content(response)
            msg = TextSendMessage(text=response)
            memory.append(user_id, role, response)
