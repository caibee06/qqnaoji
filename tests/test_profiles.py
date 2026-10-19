import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.config import Settings
from app.service import ChatService
from app.store import Store


class ProfileTests(unittest.TestCase):
    def test_switch_isolation_reset_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'chat.db')
            store = Store(path)
            settings = Settings(system_prompt='base', system_prompt_furina='furina-role', rate_limit_seconds=0)
            ai = AsyncMock()
            ai.reply.return_value = '回答'
            service = ChatService(settings, store, ai)

            async def run():
                store.append('user1', 'old', 'old reply', 10)
                await service.chat('user1', '芙宁娜')
                self.assertEqual(store.history('user1', 10), [])
                self.assertEqual(store.profile('user2'), 'default')
                await service.chat('user1', '你好')
                self.assertIn('furina-role', ai.reply.call_args.kwargs['system_prompt'])
                await service.chat('user1', '/清空')
                self.assertEqual(store.profile('user1'), 'furina')

            asyncio.run(run())
            store.close()
            store = Store(path)
            self.assertEqual(store.profile('user1'), 'furina')
            service = ChatService(settings, store, ai)
            asyncio.run(service.chat('user1', '默认'))
            self.assertEqual(store.profile('user1'), 'default')
            self.assertEqual(store.history('user1', 10), [])
            store.close()
