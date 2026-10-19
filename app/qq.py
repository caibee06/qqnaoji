import asyncio
import re
import time
from urllib.parse import quote
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def signing_key(secret):
    if not secret:
        raise ValueError('QQ_APP_SECRET 未配置')
    seed = secret.encode()
    return Ed25519PrivateKey.from_private_bytes((seed * (32 // len(seed) + 1))[:32])


def parse_message(payload):
    kind, data = payload.get('t'), payload.get('d')
    if not isinstance(data, dict) or kind not in {'C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'}:
        return None
    author = data.get('author') or {}
    if not isinstance(author, dict):
        raise ValueError('无效发送者')
    group = kind == 'GROUP_AT_MESSAGE_CREATE'
    user = author.get('member_openid' if group else 'user_openid')
    target = data.get('group_openid') if group else user
    message_id = data.get('id')
    if not all(isinstance(v, str) and v for v in (user, target, message_id)):
        raise ValueError('消息缺少用户、群或消息 ID')
    content = data.get('content', '')
    if not isinstance(content, str):
        raise ValueError('消息内容必须是文字')
    # 只移除前导机器人 @ 标记，保留正文中的其他提及。
    content = re.sub(r'^\s*<@!?\d+>\s*', '', content).strip()
    scope = 'group' if group else 'c2c'
    return {'session': f'qq:{scope}:{target}:{user}', 'scope': scope,
            'target': target, 'message_id': message_id, 'content': content}


class QQClient:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client
        self.token, self.expires = '', 0
        self.lock = asyncio.Lock()

    async def access_token(self):
        async with self.lock:
            if self.token and time.monotonic() < self.expires:
                return self.token
            s = self.settings
            response = await self.client.post('https://bots.qq.com/app/getAppAccessToken',
                                             json={'appId': s.qq_app_id, 'clientSecret': s.qq_app_secret})
            response.raise_for_status()
            data = response.json()
            self.token = data['access_token']
            self.expires = time.monotonic() + max(1, int(data['expires_in']) - 60)
            return self.token

    async def send(self, message, content):
        base = 'https://sandbox.api.sgroup.qq.com' if self.settings.qq_sandbox else 'https://api.sgroup.qq.com'
        resource = 'groups' if message['scope'] == 'group' else 'users'
        token = await self.access_token()
        response = await self.client.post(
            f"{base}/v2/{resource}/{quote(message['target'], safe='')}/messages",
            headers={'Authorization': f'QQBot {token}', 'X-Union-Appid': self.settings.qq_app_id},
            json={'content': content, 'msg_type': 0, 'msg_id': message['message_id'], 'msg_seq': 1})
        if response.status_code == 401:
            self.token = ''
        response.raise_for_status()
