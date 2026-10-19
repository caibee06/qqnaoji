# QQ AI 助手

Python + FastAPI + SQLite 的可运行项目框架。默认使用模拟回复，无需 QQ 或模型密钥即可验证流程。

## 本地启动

在项目目录的 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

打开 http://127.0.0.1:8000。首次启动安装依赖并生成 `.env`。模拟回复不是大模型回答。
也可手动创建虚拟环境，安装 `requirements.txt`，复制 `.env.example` 为 `.env`，运行 `python -m uvicorn app.main:app`。

## 连接模型

在 `.env` 设置 `AI_MODE=api`、`AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`，然后重启。
`AI_BASE_URL` 是模型服务的 API 根地址（通常以 `/v1` 结尾），不包含 `/chat/completions`。
支持提供 Chat Completions 兼容接口的服务。密钥只保存在服务端，请勿提交 `.env`。

## 连接 QQ

### SnowLuma / OneBot（普通 QQ 账号，仅群 @回复）

在 `.env` 添加：
```ini
ONEBOT_API_URL=http://127.0.0.1:3000
ONEBOT_ACCESS_TOKEN=SnowLuma的HTTP_API授权Token
ONEBOT_REPORT_TOKEN=HTTP推送客户端的授权Token
ONEBOT_REPORT_SECRET=
```
SnowLuma HTTP API：监听 `127.0.0.1:3000`，保持授权 Token。
SnowLuma HTTP 推送客户端：目标 URL 为 `http://127.0.0.1:8000/onebot/events`，消息格式选数组，授权 Token 与 `ONEBOT_REPORT_TOKEN` 相同。支持使用此 Token 验证 X-Signature 的 HMAC-SHA1 签名，也兼容 Authorization: Bearer。HTTP API 服务端的 Token 对应 `ONEBOT_ACCESS_TOKEN`，两者可以不同。没有 Secret 选项时保持 `ONEBOT_REPORT_SECRET` 为空；同时配置 Secret 则还必须通过该 Secret 的签名校验。
这里只处理群消息中指向 `self_id` 的 at 消息段；忽略私聊、自身消息、@全体和普通文本。
保存后重启本项目，用另一账号在测试群 @机器人测试。默认 AI_MODE=mock 返回模拟回答。
OneBot 发送缺少幂等键，发送失败不自动重试，避免发送结果不明确时刷屏。未完成队列仍在重启后恢复，极端情况下可能重复发送。
普通账号接入无需 QQ_APP_ID / QQ_APP_SECRET；下面是可选的官方机器人路径。

1. 在 https://q.qq.com/ 创建官方机器人，确认账户具有需要的单聊/群聊权限。
2. 填写 `.env` 的 `QQ_APP_ID` 和 `QQ_APP_SECRET`。开发阶段保持 `QQ_SANDBOX=true`。
3. 将服务部署到可通过公网 HTTPS 访问的服务器，反向代理到本服务，回调地址设为 `https://你的域名/qq/webhook`。本地 127.0.0.1 地址不能直接作为平台回调地址。
4. 在平台按已获权限订阅 `C2C_MESSAGE_CREATE` 和/或 `GROUP_AT_MESSAGE_CREATE`，配置沙箱测试用户、群及平台要求的出口 IP 白名单。
5. 用测试账户私聊或群聊 @机器人，验证真实收发。上线前关闭 `ENABLE_DEMO`，按平台要求完成审核，将 `QQ_SANDBOX` 改为 `false`。

公开部署启动示例：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`。必须保持单个 worker；当前设计使用单进程队列与会话锁。
本框架接入官方机器人，不是登录个人 QQ 账号代发消息。

## 已实现

- 私聊、群聊 @消息解析与被动文本回复。
- 回调地址验证、Ed25519 原始请求验签、AppID 校验、时间戳检查。
- QQ access token 缓存；消息 ID 去重。
- SQLite 持久化待处理事件，先入库再快速返回 ACK；进程重启恢复未完成任务。
- 失败最多尝试 3 次，回复缓存复用；使用相同 msg_id + msg_seq 降低重复发送风险。
- 按群及用户隔离记忆；`/帮助`、`/清空`；输入/输出长度限制和限频。
- 本地聊天页面、健康检查 `/health`、接口文档 `/docs`。

## 项目结构

```text
app/main.py          HTTP 入口和持久化事件工作循环
app/qq.py            QQ 验签、消息解析、token、发消息
app/ai.py            模拟/真实模型调用
app/service.py       对话、命令、限频
app/store.py         SQLite 记忆和事件
app/config.py        环境配置
app/static/          本地体验页面
tests/               接入和业务测试
```

## 验证与扩展

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

适用于原型或小规模使用。AI 请求串行执行，队列繁忙时会超过被动回复期限；扩容时应引入独立任务队列、按会话串行的工作进程和共享限频。
聊天记录为本地明文，窗口只保留配置轮数；事件正文保留最多七天并在处理事件时清理。上线时需配置数据库访问权限、备份与数据删除策略。
跨外部发送与本地事务无法保证严格恰好一次；进程在发送期间退出时，恢复重试可能收到平台的重复序号错误，应检查对应记录。
本版不包含图片、知识库、主动推送和后台管理。真实 QQ / 模型联调需要你的账号权限与密钥。

官方协议参考：
- https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/dev-prepare/interface-framework/event-emit.md
- https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/dev-prepare/interface-framework/sign.md
- https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md
