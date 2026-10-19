import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.qq import signing_key
from app.store import Store


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(ai_mode='mock', database_path=str(Path(self.tmp.name) / 'test.db'),
                                 rate_limit_seconds=0, qq_app_id='123', qq_app_secret='test-secret')

    def tearDown(self):
        self.tmp.cleanup()

    def signed(self, payload):
        raw = json.dumps(payload).encode()
        ts = str(int(time.time()))
        return raw, {'X-Bot-Appid': '123', 'X-Signature-Timestamp': ts,
                     'X-Signature-Ed25519': signing_key('test-secret').sign(ts.encode() + raw).hex()}

    def test_demo_history_isolation_clear_and_page(self):
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get('/').status_code, 200)
            def chat(session, content):
                return client.post('/api/demo/chat', json={'session_id': session, 'content': content}).json()['reply']
            self.assertIn('0 轮', chat('a', '你好'))
            self.assertIn('1 轮', chat('a', '继续'))
            self.assertIn('0 轮', chat('b', '你好'))
            self.assertIn('已清空', chat('a', '/清空'))
            self.assertIn('0 轮', chat('a', '重来'))

    def test_official_challenge_vector(self):
        self.settings.qq_app_id = '11111111'
        self.settings.qq_app_secret = 'DG5g3B4j9X2KOErG'
        with TestClient(create_app(self.settings)) as client:
            response = client.post('/qq/webhook', headers={'X-Bot-Appid': '11111111'}, json={
                'op': 13, 'd': {'plain_token': 'Arq0D5A61EgUu4OxUvOp', 'event_ts': '1725442341'}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['signature'], '87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706')

    def test_invalid_signature_timestamp_and_appid(self):
        with TestClient(create_app(self.settings)) as client:
            raw, headers = self.signed({'op': 0, 't': 'UNKNOWN', 'd': {}})
            self.assertEqual(client.post('/qq/webhook', content=raw, headers=headers).status_code, 200)
            self.assertEqual(client.post('/qq/webhook', content=raw + b' ', headers=headers).status_code, 401)
            headers['X-Signature-Timestamp'] = '1'
            self.assertEqual(client.post('/qq/webhook', content=raw, headers=headers).status_code, 401)
            headers['X-Bot-Appid'] = 'wrong'
            self.assertEqual(client.post('/qq/webhook', content=raw, headers=headers).status_code, 401)

    def test_qq_delivery_dedup_group_and_token_cache(self):
        sent, tokens = [], []
        def fake(request):
            if 'getAppAccessToken' in str(request.url):
                tokens.append(request)
                return httpx.Response(200, json={'access_token': 'fake', 'expires_in': '7200'})
            sent.append((request.url.path, json.loads(request.content), request.headers))
            return httpx.Response(200, json={'id': 'sent'})
        app = create_app(self.settings, httpx.MockTransport(fake))
        with TestClient(app) as client:
            for i, kind in enumerate(['C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE']):
                data = {'id': str(i), 'content': '<@!123> 你好', 'group_openid': 'group1',
                        'author': {'user_openid': 'user1', 'member_openid': 'user1'}}
                raw, headers = self.signed({'op': 0, 't': kind, 'd': data})
                for _ in range(2):
                    self.assertEqual(client.post('/qq/webhook', content=raw, headers=headers).status_code, 200)
            async def wait_done():
                for _ in range(30):
                    done = app.state.store.db.execute("SELECT count(*) FROM events WHERE status='done'").fetchone()[0]
                    if done == 2:
                        return True
                    await asyncio.sleep(.1)
                return False
            self.assertTrue(client.portal.call(wait_done))
            self.assertEqual(len(sent), 2)
            self.assertEqual(len(tokens), 1)
            self.assertEqual(sent[0][0], '/v2/users/user1/messages')
            self.assertEqual(sent[1][0], '/v2/groups/group1/messages')
            self.assertEqual(sent[1][1]['msg_seq'], 1)
            self.assertEqual(sent[1][2]['Authorization'], 'QQBot fake')
            self.assertIn('0 轮', sent[1][1]['content'])
            self.assertNotIn('<@', sent[1][1]['content'])

    def test_api_model_contract_and_limit(self):
        self.settings.ai_mode = 'api'
        self.settings.ai_base_url = 'https://model.test/v1'
        self.settings.ai_api_key = 'test'
        self.settings.ai_model = 'test-model'
        self.settings.max_reply_chars = 8
        requests = []
        def fake(request):
            requests.append(json.loads(request.content))
            self.assertEqual(request.url.path, '/v1/chat/completions')
            self.assertEqual(request.headers['Authorization'], 'Bearer test')
            return httpx.Response(200, json={'choices': [{'message': {'content': '这是一个超过长度限制的回复'}}]})
        with TestClient(create_app(self.settings, httpx.MockTransport(fake))) as client:
            for content in ['第一次', '第二次']:
                response = client.post('/api/demo/chat', json={'session_id': 'a', 'content': content})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()['reply']), 8)
            self.assertEqual(len(requests[1]['messages']), 4)

    def test_limits_and_disabled_demo(self):
        self.settings.rate_limit_seconds = 30
        with TestClient(create_app(self.settings)) as client:
            body = {'session_id': 'a', 'content': '你好'}
            client.post('/api/demo/chat', json=body)
            self.assertIn('稍后', client.post('/api/demo/chat', json=body).json()['reply'])
            body['content'] = 'x' * 2001
            self.assertEqual(client.post('/api/demo/chat', json=body).status_code, 422)
        self.settings.enable_demo = False
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get('/').status_code, 404)
            self.assertEqual(client.post('/api/demo/chat', json={'session_id': 'a', 'content': '你好'}).status_code, 404)

    def test_persistent_queue_recovery_and_retry(self):
        payload = {'op': 0, 't': 'C2C_MESSAGE_CREATE', 'd': {
            'id': 'recover', 'content': '你好', 'author': {'user_openid': 'user'}}}
        store = Store(self.settings.database_path)
        with store.db:
            store.db.execute("INSERT INTO events(id,payload,status,reply,created) VALUES (?,?, 'processing',?,?)",
                             ('recover', json.dumps(payload), '已缓存的回复', time.time()))
        store.close()
        sends = []
        def fake(request):
            if 'getAppAccessToken' in str(request.url):
                return httpx.Response(200, json={'access_token': 'fake', 'expires_in': 7200})
            sends.append(json.loads(request.content))
            return httpx.Response(503 if len(sends) == 1 else 200, json={})
        app = create_app(self.settings, httpx.MockTransport(fake))
        with TestClient(app) as client:
            async def wait_done():
                for _ in range(50):
                    if app.state.store.db.execute("SELECT status FROM events WHERE id='recover'").fetchone()[0] == 'done':
                        return True
                    await asyncio.sleep(.1)
                return False
            self.assertTrue(client.portal.call(wait_done))
            self.assertEqual(len(sends), 2)
            self.assertEqual(sends[0], sends[1])
            self.assertEqual(sends[1]['content'], '已缓存的回复')


if __name__ == '__main__':
    unittest.main()
