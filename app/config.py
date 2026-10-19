import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    onebot_api_url: str = os.getenv('ONEBOT_API_URL', 'http://127.0.0.1:3000')
    onebot_access_token: str = os.getenv('ONEBOT_ACCESS_TOKEN', '')
    onebot_report_secret: str = os.getenv('ONEBOT_REPORT_SECRET', '')
    onebot_report_token: str = os.getenv('ONEBOT_REPORT_TOKEN', '')
    ai_mode: str = os.getenv('AI_MODE', 'mock')
    ai_base_url: str = os.getenv('AI_BASE_URL', '')
    ai_api_key: str = os.getenv('AI_API_KEY', '')
    ai_model: str = os.getenv('AI_MODEL', '')
    system_prompt: str = os.getenv('SYSTEM_PROMPT', '你是友善的QQ助手，用简洁中文回答。')
    system_prompt_furina: str = os.getenv('SYSTEM_PROMPT_FURINA', '')
    qq_app_id: str = os.getenv('QQ_APP_ID', '')
    qq_app_secret: str = os.getenv('QQ_APP_SECRET', '')
    qq_sandbox: bool = os.getenv('QQ_SANDBOX', 'true').lower() == 'true'
    enable_demo: bool = os.getenv('ENABLE_DEMO', 'true').lower() == 'true'
    database_path: str = os.getenv('DATABASE_PATH', 'data/chat.db')
    history_turns: int = int(os.getenv('HISTORY_TURNS', '10'))
    rate_limit_seconds: float = float(os.getenv('RATE_LIMIT_SECONDS', '3'))
    max_input_chars: int = int(os.getenv('MAX_INPUT_CHARS', '2000'))
    max_reply_chars: int = int(os.getenv('MAX_REPLY_CHARS', '1500'))

    def validate(self):
        if self.ai_mode not in {'mock', 'api'}:
            raise ValueError('AI_MODE 必须是 mock 或 api')
        if self.ai_mode == 'api' and not all((self.ai_base_url, self.ai_api_key, self.ai_model)):
            raise ValueError('api 模式需要 AI_BASE_URL、AI_API_KEY、AI_MODEL')
        if min(self.history_turns, self.max_input_chars, self.max_reply_chars) < 1 or self.rate_limit_seconds < 0:
            raise ValueError('历史轮数和长度必须为正数，限频不能为负数')
