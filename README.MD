# Codelin

React + TypeScript 的 AI 编程工作台，支持工作区目录浏览、Monaco 文件编辑与 AI 对话协作。用户拥有多个工作区和多个对话；对话可独立存在，也可属于一个工作区。

## 启动

准备 PostgreSQL（含 pgvector）、Redis，在 `backend/.env` 中配置 `DATABASE_URL`、`CHECKPOINT_DB_URL`、`REDIS_URL`、`JWT_SECRET` 和所用模型的配置。沿用已有配置即可，密钥不要放入前端。

后端，PowerShell：

```powershell
cd D:\P\Codelin\backend
uv sync --group dev
.\.venv\Scripts\python.exe scripts\init_database.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

应用启动只初始化空数据库，不执行旧结构迁移，也不清空已有数据。新版不兼容旧库；首次切换到新版时，停止后端并运行 `.\.venv\Scripts\python.exe scripts\reset_database.py --execute`，清空旧账号、业务数据、agent 状态和配置中的工作区文件，再重新注册。不传 `--execute` 只展示目标。保留源码、配置和已有备份。

前端，另一个 PowerShell 窗口（建议 Node.js 24）：

```powershell
cd D:\P\Codelin\frontend
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173`，注册或登录后使用“工作空间”。默认代理后端 8000；其他端口可在 `frontend/.env` 设置 `VITE_BACKEND_URL`。如果已有后端进程，新增路由需要重启进程后才生效。

## 工作方式

- 顶部新建会话创建独立对话；工作区分组内可以新建关联对话。创建工作区只建立空工作区，选择空工作区不会隐式创建对话。
- 独立对话可以加入自己的工作区，加入后不能移出或转入其他工作区。普通问答保持独立，agent 首次请求项目工具时自动创建工作区并关联原对话，保留聊天历史。
- 侧栏工作区入口选择对应对话；文件栏的工作区选择只改变浏览范围，不改变对话归属。AI 处理期间可浏览和编辑，工作区与对话切换暂时禁用。
- 删除对话会清理消息、工具记录和 checkpoint，保留项目文件与共享索引。删除工作区会删除其中所有对话、状态、索引和项目文件；清理失败可重试，期间暂停访问该工作区。
- 单击目录项目选择，双击或 Enter 打开；右侧箭头提供点击打开。方向键、Home、End 移动选择；面包屑和上一级按钮返回。每次请求只加载当前目录的直接子项，按需加载更多。
- 宽屏支持分栏、专注文件、专注对话；中等屏幕使用文件 / 对话标签；手机使用独立文件列表、编辑器与对话视图。分隔条可拖动，也可聚焦后用方向键调整；尺寸、主题和宽屏布局保存在本地。
- 文件标签保留草稿，重复打开激活已有标签。保存按钮和 Ctrl/Cmd + S 使用原文文件 API。标签圆点表示未保存，关闭当前文件的按钮在编辑工具栏右侧；未保存时选择保存并关闭、放弃修改或取消。
- 收到 AI 文件变更事件后刷新目录，并检查打开的文件。无手动修改时刷新内容；有草稿时提供重新载入、保留草稿、比较差异。保留草稿采用外部版本作为下一次保存的基线，之后仍需主动保存。
- 文件与对话组件保持挂载，隐藏时保留状态和滚动位置；对话隐藏时提示正在生成、等待审批或新回复。添加文件到对话只插入相对路径，不自动发送内容。

## 验证

```powershell
cd D:\P\Codelin\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

默认浏览器测试使用接口替身，真实 API 测试按需启用：

后端真实 PostgreSQL / Redis 测试需使用可创建临时 schema 的独立测试数据库。设置 `CODELIN_INFRA=1` 和 `CODELIN_TEST_DATABASE_URL` 后运行 `python -m pytest tests/test_infrastructure.py -q`；测试只创建并清理自身的临时 schema 和带随机标识的 Redis 锁，不调用付费模型。

```powershell
$env:CODELIN_LIVE = '1'
$env:CODELIN_BACKEND = 'http://127.0.0.1:8000'
$env:VITE_BACKEND_URL = 'http://127.0.0.1:8000'
npm run test:e2e
```

该测试通过真实认证与文件接口创建独立验收用户、工作区和文件，不调用付费模型，不修改已有用户的项目。验收数据保留用于检查。若开发服务器已启动，务必使用相同后端地址；也可设置 `CODELIN_FRONTEND=http://127.0.0.1:5174` 让测试启动另一个前端端口。真实预览输出在 `frontend/preview/workspace-files-light.png`、`workspace-files-dark.png`、`workspace-files-mobile.png`；其他演示预览带明确的演示标识。

## 范围与限制

首版支持浏览、读取、编辑保存、新建文件和文件夹；不提供文件删除、移动、上传或服务器目录导入。文本默认上限 2 MiB，仅 UTF-8；BOM 和常规 CRLF/LF 保留。Monaco 将同一文件中混合的行尾规范化为该模型的行尾格式。二进制、其他编码和过大文件显示说明与重试入口，不生成空编辑文档。

文件草稿仅保留在当前页面内存中。刷新或关闭页面有浏览器离开提示；没有跨刷新草稿恢复。切换会话和工作区保留页面内的文件草稿与聊天草稿。

AI `write_file`、命令返回时的更新由 SSE 通知；其他进程修改通过手动刷新或保存冲突发现，暂未实现独立文件监听。文件 API 与 AI 文件工具共用跨进程锁；外部编辑器与 shell 不参与锁，shell 工具仍是现有命令审批机制，不是操作系统沙箱。

后端会保存审批恢复后的文本，但未提供跨刷新恢复审批卡片的状态接口。停止接收不会保证取消服务端执行。真实模型和命令的端到端运行仍依赖有效的模型与基础设施配置；本次通过受控 SSE 和后端测试验证相关流程。

Monaco 已本地打包并按需加载，无 CDN 依赖。编辑器和 TypeScript worker 体积较大，生产构建会出现包大小提示。生产部署请为静态资源启用压缩和缓存，并通过同源反向代理转发 `/api`，对聊天 SSE 关闭代理缓冲。