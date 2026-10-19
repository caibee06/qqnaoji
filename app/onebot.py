import hashlib
import hmac
from urllib.parse import urlsplit


def verify_report(raw, signature, secret):
    expected = 'sha1=' + hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature)


def parse_group_at(payload):
    if payload.get('post_type') != 'message' or payload.get('message_type') != 'group':
        return None
    bot, user, group, mid = (payload.get(k) for k in ('self_id', 'user_id', 'group_id', 'message_id'))
    if not all(isinstance(v, (int, str)) and str(v).isdigit() for v in (bot, user, group)):
        return None
    if not isinstance(mid, (int, str)) or not str(mid).lstrip('-').isdigit():
        return None
    if str(bot) == str(user):
        return None
    segments = payload.get('message')
    if not isinstance(segments, list):
        return None
    mentioned = False
    texts = []
    images = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get('data'), dict):
            continue
        data = segment['data']
        if segment.get('type') == 'at' and str(data.get('qq')) == str(bot):
            mentioned = True
        if segment.get('type') == 'text' and isinstance(data.get('text'), str):
            texts.append(data['text'])
        if segment.get('type') == 'image':
            url = data.get('url') or data.get('file')
            if isinstance(url, str) and urlsplit(url).scheme in {'http', 'https'}:
                images.append(url)
    if not mentioned:
        return None
    return {'session': f'onebot:{bot}:{group}:{user}', 'target': int(group),
            'message_id': str(mid), 'bot': str(bot), 'content': ''.join(texts).strip(), 'images': images}


class OneBotClient:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def send(self, message, content):
        headers = {'Authorization': f'Bearer {self.settings.onebot_access_token}'}
        response = await self.client.post(self.settings.onebot_api_url.rstrip('/') + '/send_group_msg',
            headers=headers, json={'group_id': message['target'],
                'message': [{'type': 'text', 'data': {'text': content}}]})
        response.raise_for_status()
        result = response.json()
        if result.get('status') != 'ok' or result.get('retcode') != 0:
            raise ValueError('OneBot 发送失败')
