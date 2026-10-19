import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
import hashlib
import hmac
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.onebot import parse_group_at
from app.ai import AI


def event():
    return {'post_type': 'message', 'message_type': 'group', 'self_id': 123,
            'user_id': 456, 'group_id': 789, 'message_id': -10,
            'message': [{'type': 'at', 'data': {'qq': '123'}},
                        {'type': 'text', 'data': {'text': ' 你好'}}]}


class OneBotTests(unittest.TestCase):
    def test_image_message_and_model_payload(self):
        payload = event()
        payload['message'] = [payload['message'][0], {'type': 'image', 'data': {'url': 'https://example.com/photo.png'}}]
        message = parse_group_at(payload)
        self.assertEqual(message['images'], ['https://example.com/photo.png'])
        def fake(request):
            data = json.loads(request.content)
            self.assertEqual(data['messages'][-1]['content'][1],
                {'type': 'image_url', 'image_url': {'url': 'https://example.com/photo.png'}})
            return httpx.Response(200, json={'choices': [{'message': {'content': '图片描述'}}]})
        async def run():
            settings = Settings(ai_mode='api', ai_base_url='https://example.com', ai_api_key='test', ai_model='deepseek-flash')
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
                return await AI(settings, client).reply([], '看看图片', images=message['images'])
        self.assertEqual(asyncio.run(run()), '图片描述')

    def test_token_delivery_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(ai_mode='mock', database_path=str(Path(tmp) / 'chat.db'),
                onebot_access_token='api-token', onebot_report_secret='', onebot_report_token='push-token')
            with TestClient(create_app(settings)) as client:
                for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'push-token'}):
                    self.assertEqual(client.post('/onebot/events', json={}, headers=headers).status_code, 401)
                self.assertEqual(client.post('/onebot/events', json={}, headers={'Authorization': 'Bearer push-token'}).status_code, 200)
                raw = b'{}'
                signature = 'sha1=' + hmac.new(b'push-token', raw, hashlib.sha1).hexdigest()
                self.assertEqual(client.post('/onebot/events', content=raw, headers={'X-Signature': signature}).status_code, 200)
                self.assertEqual(client.post('/onebot/events', content=b'{"changed":true}', headers={'X-Signature': signature}).status_code, 401)
                settings.onebot_report_token = ''
                self.assertEqual(client.post('/onebot/events', json={}).status_code, 503)

    def test_only_explicit_group_at(self):
        p = event()
        self.assertEqual(parse_group_at(p)['content'], '你好')
        for changes in [{'message_type': 'private'}, {'user_id': 123},
                        {'post_type': 'message_sent'}, {'message': '伪造 @123'},
                        {'message': [{'type': 'at', 'data': {'qq': 'all'}}]},
                        {'message': [{'type': 'at', 'data': {'qq': '999'}}]}]:
            self.assertIsNone(parse_group_at({**p, **changes}))

    def test_signed_delivery_and_dedup(self):
        sent = []
        def fake(request):
            self.assertEqual(request.url.path, '/send_group_msg')
            self.assertEqual(request.headers['Authorization'], 'Bearer api-token')
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={'status': 'ok', 'retcode': 0})
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(ai_mode='mock', database_path=str(Path(tmp) / 'chat.db'),
                onebot_access_token='api-token', onebot_report_secret='report-secret', onebot_report_token='', rate_limit_seconds=0)
            app = create_app(settings, httpx.MockTransport(fake))
            with TestClient(app) as client:
                raw = json.dumps(event()).encode()
                signature = 'sha1=' + hmac.new(b'report-secret', raw, hashlib.sha1).hexdigest()
                self.assertEqual(client.post('/onebot/events', content=raw).status_code, 401)
                for _ in range(2):
                    self.assertEqual(client.post('/onebot/events', content=raw, headers={'X-Signature': signature}).status_code, 200)
                async def done():
                    for _ in range(30):
                        if sent:
                            return True
                        await asyncio.sleep(.1)
                    return False
                self.assertTrue(client.portal.call(done))
                self.assertEqual(len(sent), 1)
                self.assertEqual(sent[0]['group_id'], 789)
                self.assertEqual(sent[0]['message'][0]['type'], 'text')
