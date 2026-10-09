# 首条消息自动生成会话标题

创建会话 `/api/sessions` 时还没有用户消息，先保存临时标题“新会话”。
在 `/api/chat` 保存第一条用户消息后，启动独立的异步任务生成标题，正文的 Agent 同时运行。

调用链：

1. `app/main.py: chat` 判断是不是首条用户消息且标题仍为默认值，提交消息后调用 `start_title_task`。
2. `app/llm/titles.py: generate_title` 复用 `provider.get_llm()`，通过 `ainvoke` 发送标题提示和首条消息。使用独立模型调用，不绑定工具、不改动 Agent checkpoint。只发送首条消息前 4000 个字符。
3. `update_title` 使用独立数据库 Session，验证会话归属及最早用户消息，以条件更新写入标题。自定义标题、生成期间改名、已删除会话均不会被覆盖。
4. 聊天 SSE 首先发送 `session_title_pending`，内容为 `{"session_id": "...", "title": "新会话"}`。前端独立请求 `GET /api/sessions/{sid}`，约每秒一次，最长 20 秒；标题变化时更新侧栏和当前会话标题。正文流结束不需要等待标题。

单个会话查询使用现有登录认证，只有会话所有者能读取；不存在或其他用户的会话返回 404。响应设定 `Cache-Control: no-store`。

默认使用已有模型配置，不需要新密钥。可在 `backend/.env` 设置 `TITLE_TIMEOUT_SECONDS=15`（默认 15 秒；建议低于前端 20 秒等待上限）。模型返回空内容、调用失败或超时均只记录警告，保留“新会话”，不影响正文或审批。标题清理掉引号、前缀和解释，最多保存 64 个字符。

没有数据库结构变更；部署时重启后端并重新构建前端即可。前端保持原有启动方式。测试不调用真实模型：

```powershell
cd D:\P\Codelin\backend
.\.venv\Scripts\python.exe -m pytest tests/test_session_titles.py tests/test_chat_stream.py tests/test_workspaces_api.py -q

cd D:\P\Codelin\frontend
npm run test:e2e -- tests/e2e/workspace.spec.ts --grep "asynchronous title|chat stream|real approval"
npm run build
```

当前标题任务保存在服务进程内。正常关闭时取消未完成任务；进程重启、任务失败时不会自动重试，标题保持临时值。已经有消息的旧会话不会自动补标题。若需要断电后的可靠重试，应另接持久任务队列。判断自动命名资格使用默认标题文字，显式自定义为“新会话”的标题也会自动命名。每个新会话会增加一次独立的模型调用。
