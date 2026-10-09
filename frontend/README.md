# Codelin 前端

React + TypeScript + Vite 的 AI 编程工作台，按照 UI Skills 的 baseline-ui、fixing-accessibility 和 Apple 设计规范实现。使用 Tailwind CSS 4、Radix 无障碍对话框和 Lucide 图标。

## 启动

需要 Node.js 20.19+ 或 22.12+（本机已使用 Node.js 24 验证）。在 PowerShell 中执行：

```powershell
cd D:\P\Codelin\frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173。后端默认运行在 http://127.0.0.1:8000，开发服务器将 `/api` 代理到该地址，无需修改后端 CORS。可以在 `.env` 中按 `.env.example` 配置代理目标。

登录页面的“体验演示”可直接预览交互；所有示例均明确标注，不发送后端请求，不执行命令。退出演示后可以注册或登录真实账户。

## 功能与接口

| 功能 | 后端接口 |
| --- | --- |
| 注册 / 登录 | `POST /api/auth/register`、`POST /api/auth/login` |
| 会话列表 / 创建 | `GET /api/sessions`、`POST /api/sessions` |
| 删除会话 | `DELETE /api/sessions/{sid}`，前端提供删除确认 |
| 加载历史消息 | `GET /api/sessions/{sid}/messages` |
| 流式对话 | `POST /api/chat`，携带 `session_id`、`message` |
| 命令审批与恢复 | `POST /api/chat/approve`，携带 `session_id`、`approved` |

注册和登录使用 JSON `{ username, password }`。登录凭证存储于当前标签页的 `sessionStorage`，后续请求携带 Bearer token，401 会返回登录页。

SSE 支持 `token`、`tool_start`、`tool_result`、`approval_required`、`done`、`error`。中文多字节内容和跨网络分片的事件均可正确解析。Markdown 不启用原始 HTML，链接使用安全协议过滤，外链附带 `noopener noreferrer`。

支持浅色 / 深色模式、手机导航、会话搜索、消息与代码复制、执行记录展开和错误重试。停止按钮只中止浏览器接收；现有后端没有取消执行接口，因此会明确提示服务端可能继续执行。

后端没有文件上传、项目目录选择、会话重命名、模型切换等接口，前端不会展示这些不可用的操作。每个会话使用后端新建的 `workspaces/{sid}` 目录。

## 验证与构建

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

端到端测试使用按后端真实契约编写的接口替身，验证请求格式、认证、历史消息、审批、断线、会话删除和无障碍。它不代替完整后端联调。运行测试后，`preview/` 中会生成桌面、登录、深色和手机截图。

构建产物位于 `dist/`。生产部署建议通过同源反向代理将 `/api` 转发到 FastAPI，并关闭代理响应缓冲以支持 SSE。如配置 `VITE_API_BASE_URL` 为独立 API 域名，后端需要允许该站点的 CORS。

## 当前后端联调注意事项

前端实现后，联调时已修复聊天和审批恢复漏传 `session_id` 的问题，并将会话 ID 写入图状态。以下是其余已知后端限制：

1. `/api/chat/approve` 没有将恢复后生成的回复存入 `Message` 表。因此前端当前标签页可看到恢复回复，但重新加载历史时可能丢失该部分。后端也未提供审批状态查询，刷新页面无法恢复尚未决定的审批卡片。
2. 会话删除仅删除 `ChatSession`，`Message` 等外键没有配置级联删除；存在消息的会话可能被数据库拒绝删除。前端会保留会话并显示后端错误。
3. 完整联调还需要 PostgreSQL（含 pgvector）、Redis 和有效的模型配置。它们由现有后端配置，不应把密钥写入前端环境变量。

真实聊天可以开始验证；审批回复的历史保存和有消息会话的删除仍需要后端改进。
