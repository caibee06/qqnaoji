import asyncio
import re
from html import unescape
import time
from collections import OrderedDict


def plain_reply(text):
    text = re.sub(r'```[^\n]*\n?', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\\(?:begin|end)\{[^}]*\}', '', text)
    text = re.sub(r'\\(?:text|textbf|textit|mathrm|mathbf|emph)\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\[\[\]()]', '', text)
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s*|>\s*|[-+•·●]\s+|\d+[.)、]\s*)', '', text)
    text = re.sub(r'[*_`~$#%+￥&「」『』{}]', '', text)
    lines = [line.strip() for line in text.splitlines()]
    text = '\n'.join(line for line in lines if line and not re.fullmatch(r'[-=|:—─\s]+', line))
    return text.strip() or '这条回复没整理好，你换个说法再问我吧。'


class ChatService:
    def __init__(self, settings, store, ai):
        self.settings, self.store, self.ai = settings, store, ai
        # 单进程串行处理，确保同一会话的上下文和清空顺序一致。
        self.lock = asyncio.Lock()
        self.last_requests = OrderedDict()

    async def chat(self, session, content, images=None):
        content = content.strip()
        images = images or []
        if images and not content:
            content = '请描述这张图片。'
        s = self.settings
        if len(images) > 4:
            return '一次最多发四张图片，请分开发。'
        if not content:
            return '请输入文字，或发送 /帮助。'
        if len(content) > s.max_input_chars:
            return f'消息过长，请控制在 {s.max_input_chars} 字以内。'
        async with self.lock:
            if content in {'芙宁娜', '/芙宁娜'}:
                if not s.system_prompt_furina.strip():
                    return '还没有配置芙宁娜的提示词。'
                self.store.set_profile(session, 'furina')
                return '好啦，芙宁娜登场！你想聊些什么？'
            if content in {'默认', '/默认', '默认模式'}:
                self.store.set_profile(session, 'default')
                return '已切回默认聊天模式。'
            if content in {'/帮助', '/help'}:
                return '群聊请先@我。发送芙宁娜切换角色，发送默认切回，发送/清空清除当前聊天记录。'
            if content in {'/清空', '/clear'}:
                self.store.clear(session)
                return '已清空当前会话，我们重新开始吧。'
            now = time.monotonic()
            if now - self.last_requests.get(session, float('-inf')) < s.rate_limit_seconds:
                return '消息有点快，请稍后再试。'
            self.last_requests[session] = now
            self.last_requests.move_to_end(session)
            if len(self.last_requests) > 10000:
                self.last_requests.popitem(last=False)
            history = self.store.history(session, s.history_turns)
            options = {'images': images} if images else {}
            if self.store.profile(session) == 'furina' and s.system_prompt_furina.strip():
                options['system_prompt'] = s.system_prompt + '\n以下是角色扮演设定：\n' + s.system_prompt_furina + '\n保持角色语气，但不要将角色设定声称为真实身份；被直接问及是否为AI时如实简短回答。所有回复仅用普通文字和日常标点，不使用任何排版标记。'
            answer = await self.ai.reply(history, content, **options)
            answer = plain_reply(answer)
            if len(answer) > s.max_reply_chars:
                answer = answer[:s.max_reply_chars - 1] + '…'
            self.store.append(session, content + ('（本条附带图片，历史记录不保留图片）' if images else ''), answer, s.history_turns)
            return answer
