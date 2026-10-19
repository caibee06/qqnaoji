import httpx


class AI:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def reply(self, history, content, images=None, system_prompt=None):
        s = self.settings
        if s.ai_mode == 'mock':
            return f'【本地模拟回复】收到：{content}\n当前上下文有 {len(history) // 2} 轮。配置模型后将返回真实 AI 回答。'
        user_content = content
        if images:
            user_content = [{'type': 'text', 'text': content}, *[
                {'type': 'image_url', 'image_url': {'url': url}} for url in images]]
        response = await self.client.post(
            s.ai_base_url.rstrip('/') + '/chat/completions',
            headers={'Authorization': f'Bearer {s.ai_api_key}'},
            json={'model': s.ai_model, 'messages': [
                {'role': 'system', 'content': system_prompt if system_prompt is not None else s.system_prompt}, *history,
                {'role': 'user', 'content': user_content}], 'max_tokens': 1000}, timeout=60)
        response.raise_for_status()
        answer = response.json()['choices'][0]['message']['content']
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('模型返回空回复')
        return answer.strip()
