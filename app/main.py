import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .ai import AI
from .config import Settings
from .qq import QQClient, parse_message, signing_key
from .service import ChatService
from .store import Store
from .onebot import OneBotClient, parse_group_at, verify_report

log = logging.getLogger('qqai')


def create_app(settings=None, transport=None):
    settings = settings or Settings()
    settings.validate()

    async def worker(app):
        db = app.state.store.db
        while True:
            row = db.execute("SELECT id,payload,reply,created,attempts FROM events WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if not row:
                await asyncio.sleep(0.3)
                continue
            event_id, raw, reply, created, attempts = row
            db.execute("UPDATE events SET status='processing',attempts=attempts+1 WHERE id=?", (event_id,))
            db.commit()
            try:
                payload = json.loads(raw)
                is_onebot = event_id.startswith('onebot:')
                message = parse_group_at(payload) if is_onebot else parse_message(payload)
                if time.time() - created > 240:
                    raise ValueError('事件已超过本服务回复期限')
                if reply is None:
                    try:
                        reply = await app.state.chat.chat(message['session'], message['content'], images=message.get('images'))
                    except (httpx.HTTPError, ValueError, KeyError, IndexError):
                        log.warning('模型调用失败；不记录消息或密钥')
                        reply = 'AI 服务暂时不可用，请稍后再试。'
                    db.execute('UPDATE events SET reply=? WHERE id=?', (reply, event_id))
                    db.commit()
                await (app.state.onebot if is_onebot else app.state.qq).send(message, reply)
                db.execute("UPDATE events SET status='done' WHERE id=?", (event_id,))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('QQ事件处理失败，类型=%s，尝试=%s', type(exc).__name__, attempts + 1)
                # OneBot 无发送幂等键，发送结果不确定时避免自动重复发送。
                retry = not event_id.startswith('onebot:') and attempts < 2 and time.time() - created < 240
                db.execute('UPDATE events SET status=? WHERE id=?', ('pending' if retry else 'failed', event_id))
                if retry:
                    db.commit()
                    await asyncio.sleep(2 ** attempts)
            db.commit()
            # 去重记录保留 7 天；正文不会写入常规日志。
            db.execute("DELETE FROM events WHERE status IN ('done','failed') AND created<?", (time.time() - 604800,))
            db.commit()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings.database_path)
        async with httpx.AsyncClient(timeout=20, transport=transport) as client:
            app.state.chat = ChatService(settings, app.state.store, AI(settings, client))
            app.state.qq = QQClient(settings, client)
            app.state.onebot = OneBotClient(settings, client)
            task = asyncio.create_task(worker(app))
            try:
                yield
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                app.state.store.close()

    app = FastAPI(title='QQ AI 助手', lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'ai_mode': settings.ai_mode,
                'qq_configured': bool(settings.qq_app_id and settings.qq_app_secret)}

    @app.get('/', include_in_schema=False)
    async def home():
        if not settings.enable_demo:
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / 'static' / 'index.html')

    class ChatInput(BaseModel):
        session_id: str = Field(min_length=1, max_length=100)
        content: str = Field(max_length=settings.max_input_chars)

    @app.post('/api/demo/chat')
    async def demo(data: ChatInput):
        if not settings.enable_demo:
            raise HTTPException(404)
        try:
            return {'reply': await app.state.chat.chat('demo:' + data.session_id, data.content)}
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            raise HTTPException(502, 'AI 服务暂时不可用，请检查模型配置') from None

    @app.post('/onebot/events')
    async def onebot_events(request: Request):
        if not settings.onebot_access_token or not (settings.onebot_report_secret or settings.onebot_report_token):
            raise HTTPException(503, '请配置 OneBot API Token 和上报 Token 或 Secret')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413)
        raw = bytes(raw)
        if settings.onebot_report_token:
            authorization = request.headers.get('Authorization', '')
            bearer_valid = hmac.compare_digest(authorization.encode(), ('Bearer ' + settings.onebot_report_token).encode())
            signature_valid = verify_report(raw, request.headers.get('X-Signature', ''), settings.onebot_report_token)
            if not (bearer_valid or signature_valid):
                log.warning('OneBot auth mismatch: authorization_present=%s signature_present=%s',
                            bool(authorization), bool(request.headers.get('X-Signature')))
                raise HTTPException(401, 'OneBot 上报 Token 或签名无效')
        if settings.onebot_report_secret and not verify_report(raw, request.headers.get('X-Signature', ''), settings.onebot_report_secret):
            raise HTTPException(401, 'OneBot 上报签名无效')
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, '无效 JSON') from None
        message = parse_group_at(payload)
        if message:
            event_id = f"onebot:{message['bot']}:{message['target']}:{message['message_id']}"
            with app.state.store.db:
                app.state.store.db.execute('INSERT OR IGNORE INTO events(id,payload,created) VALUES (?,?,?)',
                                          (event_id, raw.decode(), time.time()))
        return {}

    @app.post('/qq/webhook')
    async def webhook(request: Request):
        if not settings.qq_app_id or not settings.qq_app_secret:
            raise HTTPException(503, 'QQ 配置未完成')
        if request.headers.get('X-Bot-Appid') != settings.qq_app_id:
            raise HTTPException(401, 'AppID 不匹配')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, '请求过大')
        raw = bytes(raw)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, '无效 JSON') from None
        key = signing_key(settings.qq_app_secret)
        if payload.get('op') == 13:
            data = payload.get('d')
            if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ('plain_token', 'event_ts')):
                raise HTTPException(400, '无效验证请求')
            return {'plain_token': data['plain_token'],
                    'signature': key.sign((data['event_ts'] + data['plain_token']).encode()).hex()}
        try:
            timestamp = request.headers.get('X-Signature-Timestamp', '')
            if abs(time.time() - int(timestamp)) > 300:
                raise ValueError()
            signature = bytes.fromhex(request.headers.get('X-Signature-Ed25519', ''))
            key.public_key().verify(signature, timestamp.encode() + raw)
        except (ValueError, InvalidSignature):
            raise HTTPException(401, '签名无效或请求过期') from None
        if payload.get('op') == 0:
            try:
                message = parse_message(payload)
            except ValueError:
                raise HTTPException(400, '消息结构无效') from None
            if message:
                event_id = f"{message['scope']}:{message['target']}:{message['message_id']}"
                db = app.state.store.db
                with db:
                    db.execute('INSERT OR IGNORE INTO events(id,payload,created) VALUES (?,?,?)',
                               (event_id, raw.decode(), time.time()))
        return {'op': 12}

    return app


app = create_app()
