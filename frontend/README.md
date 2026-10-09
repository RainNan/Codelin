# Codelin 前端

React 19 + TypeScript + Vite 的 AI 编程工作台。沿用 Apple 风格、系统字体、浅灰白背景、克制蓝色与独立深色变量。ui-skills-root 选用 emilkowalski/apple-design 和 ibelick/fixing-accessibility；复杂交互使用 Radix Dialog/Tabs，拖动和键盘分隔条使用 react-resizable-panels，图标统一使用 Lucide。

## 启动

建议 Node.js 24；Vite 最低要求 Node.js 20.19+ 或 22.12+，单元测试脚本需要支持 --experimental-strip-types 的 Node.js。

```powershell
cd D:\P\Codelin\frontend
npm ci
npm run dev
```

访问 http://127.0.0.1:5173。默认将 /api 代理到 http://127.0.0.1:8000；通过 .env.example 配置 VITE_BACKEND_URL。需要后端启动且已执行工作区迁移，详见项目根目录 README 和 backend/WORKSPACE_API.md。

## 文件工作台

工作空间入口可展开 / 收起文件栏。文件栏提供工作区切换、面包屑、上一级、刷新、新建文件 / 文件夹、目录列表和加载更多。单击选择，双击或 Enter 打开；方向键、Home、End 移动选择。每一行的打开箭头支持触屏操作，不依赖双击。文件夹优先和自然排序来自后端。

宽屏（1200px 起）默认编辑器 / 对话分栏，支持专注文件与专注对话；768–1199px 使用文件 / 对话标签；手机使用独立文件列表、编辑与聊天视图。导航、文件栏和主内容的宽度可调整，分隔条支持键盘操作，布局偏好保存于 localStorage。

新建会话复用当前工作区。切换工作区优先切换到已有的关联会话，没有会话则先创建；创建失败时保留当前会话。AI 生成期间只禁用会话和工作区切换，文件操作与布局切换仍可用。进入目录不会改变 AI 的根目录。刷新后恢复当前账户最后选择的、仍存在的会话。

Monaco 按需加载并本地打包 worker，不连接 CDN。编辑器支持标签、语言识别、高亮、行号、草稿保留、保存、Ctrl/Cmd + S 和关闭确认。关闭按钮位于当前文件工具栏右侧。相同文件只开一个标签。切换工作区时仍保留页面内该工作区的草稿。

外部更新处理：无草稿的文件自动载入；有草稿时显示提示，可以重新载入、保留草稿或打开只读差异比较。保留草稿将外部版本作为下一次保存基线，不立即写入。所有保存都带后端的 SHA-256 版本，冲突返回 409；错误不清除用户草稿。保存中继续编辑也会保留新增修改。刷新目录同时检查所有打开文件。

点击“将当前文件路径添加到对话”只插入相对路径，随后可编辑输入并自主发送。对话隐藏仍保持流式请求、消息、输入、审批状态和滚动位置；生成、新回复、待审批有提示。

## 模块与接口

| 模块 | 职责 |
| --- | --- |
| src/App.tsx | 登录、会话、工作区关联、聊天、审批与 SSE 文件事件 |
| src/components/Workbench.tsx | 稳定面板、响应式视图、布局保存、隐藏对话状态 |
| src/components/FileBrowser.tsx | 目录请求、面包屑、键盘操作、分页、创建与错误恢复 |
| src/components/FileEditor.tsx | Monaco、标签、模型 / 视图状态、关闭提示、差异比较 |
| src/lib/useWorkspaceFiles.ts | 按工作区缓存文件、草稿、版本、冲突与异步请求保护 |
| src/lib/api.ts | Bearer 认证、结构化 JSON 文件 API 与流式聊天 |

文件接口使用 /api/workspaces、/api/workspaces/{wid}/files、/file 和 /entries，不传用户 ID 或服务器绝对路径。会话创建提交 workspace_id。SSE 兼容 token、tool_start、tool_result、approval_required、done、error，并处理 file_changed、workspace_changed。

登录凭证仅存于当前标签页 sessionStorage，401 返回登录页。文件 API 与 AI 展示输出完全独立；原文不带行号且不截断。非 UTF-8、二进制和超过默认 2 MiB 的文件显示明确错误，不创建空文件标签。

## 测试、构建与预览

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

默认运行 17 个受控浏览器测试，并跳过真实后端验收。真实联调需要已启动后端：

```powershell
$env:CODELIN_LIVE = '1'
$env:CODELIN_BACKEND = 'http://127.0.0.1:8000'
$env:VITE_BACKEND_URL = 'http://127.0.0.1:8000'
npm run test:e2e
```

若现有端口运行旧版服务，可以另开后端 8001，再设置上述两个后端地址为 8001，并设置 CODELIN_FRONTEND=http://127.0.0.1:5174。测试会启动独立前端。不要在测试运行时修改应用代码，开发服务器热更新会影响状态验证。

live-files.spec.ts 通过真实接口创建独立验收用户、工作区和文件，检查保存、外部更新冲突、跨用户隔离、路径安全和手机操作，不请求真实模型。截图在 preview/workspace-files-light.png、workspace-files-dark.png、workspace-files-mobile.png，这些截图来自真实接口。其他演示截图保留明确的演示标识。

构建输出在 dist/。Monaco 和 TypeScript worker 较大，构建有包大小提示；文件编辑器被拆为按需模块。生产部署建议静态压缩 / 缓存及同源 /api 反向代理，聊天接口关闭代理响应缓冲。跨域部署 VITE_API_BASE_URL 需要后端配置 CORS。

## 当前范围

没有文件删除、移动、上传或本地项目目录导入。文件草稿仅在页面内存中保留，关闭 / 刷新有浏览器离开提示；尚无跨刷新草稿恢复。UTF-8 BOM、常规 CRLF/LF 保留；Monaco 统一同一文件内混合行尾。

外部进程修改通过刷新 / 保存冲突发现，尚无独立文件监听。命令返回事件触发重查，不代表命令成功。停止接收不保证停止服务端。后端已保存审批恢复后的回复，但未提供刷新后恢复待审批卡片的接口。

“体验演示”不请求文件接口、模型或执行命令，文件面板明确要求连接真实服务。
