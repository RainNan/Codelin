# 工作区、对话与文件接口

所有接口均需要 `Authorization: Bearer <token>`。工作区和对话由当前用户拥有，跨用户访问统一返回 404。客户端不能指定服务器绝对路径。

## 初始化与清空重建

正常启动运行 `scripts/init_database.py`，也会自动初始化空数据库。已有新版数据库保留数据，旧结构直接拒绝启动。本项目不再使用 Alembic 或业务迁移脚本。

切换新版前停止后端，执行 `python scripts/reset_database.py --execute`，清空账号、业务表、旧 agent 状态和配置中的工作区目录，再初始化新版。省略 `--execute` 只展示脱敏的目标，不做修改。源代码、配置、已有备份及其他数据库表不受影响。LangGraph 官方存储组件仍负责初始化自己的状态表。

## 工作区

- `GET /api/workspaces`：当前用户工作区列表。
- `POST /api/workspaces`，请求 `{"name":"项目 A"}`：创建空工作区，返回 201；不会自动创建对话。
- `GET /api/workspaces/{wid}`：工作区详情。
- `PATCH /api/workspaces/{wid}`，请求 `{"name":"新名字"}`：重命名。
- `DELETE /api/workspaces/{wid}`：删除工作区、其中所有对话、消息、工具记录、checkpoint、检索索引及项目文件，成功返回 `{"ok":true}`。

工作区对象：`{"id":"...","name":"项目 A","created_at":"...","deleting":false}`。名称去除首尾空白，不能为空，最长 128 字符。根目录在 `WORKSPACE_ROOT/{user_id}/{workspace_id}`，不对外返回。

## 对话

- `POST /api/sessions`：不传请求体、传 `{}` 或 `{"workspace_id":null}` 时创建独立对话。传 `{"workspace_id":"...","title":"讨论项目"}` 时在自己的工作区内创建。默认标题是“新会话”。
- `GET /api/sessions`：全部对话；`?standalone=true` 仅返回独立对话；`?workspace_id=...` 仅返回该工作区的对话。两种筛选同时使用返回 422。
- `GET /api/sessions/{sid}`：对话详情，响应设定 `Cache-Control: no-store`。
- `PATCH /api/sessions/{sid}`：可传 `title` 修改标题，或传 `workspace_id` 将独立对话加入工作区。聊天记录保留；重复加入同一工作区成功；已经加入后传 null 或其他工作区返回 409。手动改标题会关闭自动命名。
- `DELETE /api/sessions/{sid}`：删除对话、消息、工具记录及 checkpoint，保留工作区、项目文件及共享索引。
- `GET /api/sessions/{sid}/messages`：消息历史，保留原有响应格式。

对话对象：`{"id":"...","title":"新会话","workspace_id":null,"created_at":"...","deleting":false}`。一个对话最多属于一个工作区，不能移出或转入另一个工作区。

## 聊天与自动创建

`POST /api/chat` 仍接收 `{"session_id":"...","message":"..."}`；`POST /api/chat/approve` 仍接收 `{"session_id":"...","approved":true}`。

独立对话普通问答不创建工作区。agent 首次请求有效项目工具时，后端事务性地创建“新工作区”，关联原对话，再进入工具审批和执行。保留原对话 ID、消息和标题；工具失败或审批拒绝后工作区仍保留。每轮根目录以数据库归属为准。

新增 SSE：

```text
event: workspace_created
data: {"session_id":"对话ID","workspace":{"id":"工作区ID","name":"新工作区","created_at":"...","deleting":false}}
```

此事件在实际执行工具或发出审批提示前出现；`tool_start` 表示模型请求调用，可能更早出现。前端更新分组、归属和文件上下文，流结束时重新查询对话，补偿遗漏的事件。文件栏的浏览工作区不改变对话归属。

同一对话不能并行执行多轮。运行中加入或删除返回 409，工作区删除与其聊天及文件操作互斥。等待审批时允许删除对话或工作区；没有待审批操作时调用审批接口返回 409。

删除失败返回 500 并保留 `deleting:true`，可重试同一个 DELETE。删除中的对象禁止新聊天、加入和文件访问；只读详情和列表仍可用于展示删除进度。删除成功才清理前端缓存。不通过整个 Redis 数据库清空来释放锁。

## 文件与目录

### GET /api/workspaces/{wid}/files?path=src&offset=0&limit=200

只列出该目录的直接子项，目录优先、名称自然排序。`path` 默认 `.`，`limit` 为 1–500，`offset` 从 0 开始。

```json
{
  "path":"src",
  "entries":[
    {"name":"components","path":"src/components","type":"directory","size":null,"modified_at":"UTC时间"},
    {"name":"main.py","path":"src/main.py","type":"file","size":1024,"modified_at":"UTC时间"}
  ],
  "total":2,
  "next_offset":null
}
```

双击目录时用该项目的 `path` 重新请求；面包屑和当前目录由前端维护。分页过程中目录可能变化，需要时从第一页刷新。

### GET /api/workspaces/{wid}/file?path=src/main.py

返回 UTF-8 文件原文，不加行号、不截断，保留 CRLF、BOM 和末尾换行：

```json
{
  "name":"main.py",
  "path":"src/main.py",
  "type":"file",
  "size":15,
  "modified_at":"UTC时间",
  "content":"print('hello')\n",
  "version":"64位小写SHA-256摘要"
}
```

响应同时包含 `ETag: "摘要"` 和 `Cache-Control: no-store`。目前默认最大 2 MiB。二进制和非 UTF-8 文件返回 `415`，超大文件返回 `413`，不能将它们作为空文件编辑。

目录列表和保存响应也带 `Cache-Control: no-store`，避免文件变更后沿用浏览器缓存。路径校验拒绝控制字符、路径穿越、绝对路径和越界符号链接；工作区目录创建的权限 / IO 错误也通过结构化文件错误返回。

### PUT /api/workspaces/{wid}/file

```json
{"path":"src/main.py","content":"print('updated')\n","version":"读取时获得的摘要"}
```

必须提供原版本。后端在文件锁内完成检查和写入，成功返回最新元数据、版本与 `operation: updated`。若版本不一致返回 `409`，原文件保持不变；前端应保留草稿，让用户重新载入或比较差异。

保存使用同目录临时文件、刷盘和原子替换。HTTP 编辑器与 AI 文件工具使用相同的跨进程锁。锁文件放在工作区之外，不展示在文件列表中。

### POST /api/workspaces/{wid}/entries

```json
{"path":"src","type":"directory"}
```

或：

```json
{"path":"src/new.py","type":"file","content":""}
```

成功返回 `201` 和元数据。父目录必须已存在；目标已存在返回 `409`，不会覆写。文件和目录不能通过该接口混淆创建。

## AI 文件更新事件

原来的 `token`、`tool_start`、`tool_result`、`approval_required`、`done`、`error` 保持兼容。

AI 的 `write_file` 成功完成后增加事件：

```text
event: file_changed
data: {"workspace_id":"工作区ID","path":"src/main.py","operation":"updated","version":"最新摘要"}
```

写入失败不发送此事件。前端收到后刷新相关目录；编辑器存在未保存内容时，提示外部更新并保留草稿。

命令工具执行返回后发送：

```text
event: workspace_changed
data: {"workspace_id":"工作区ID"}
```

命令可能修改多个文件，这个事件表示需要重新检查文件目录，不表示命令一定成功。前端可以刷新当前目录并检查已打开文件的版本。

第一版不包含独立文件监听或 WebSocket；其他进程修改文件时，通过手动刷新与保存版本检查发现变化。

## 错误与配置

错误响应为 `{"detail":"说明"}`：

| 状态码 | 含义 |
| --- | --- |
| 401 | 未登录或登录过期 |
| 403 | 路径越界、无效名称或没有文件访问权限 |
| 404 | 工作区、文件或父目录不存在 |
| 409 | 版本冲突、目标已存在或文件类型不匹配 |
| 413 | 文件或保存内容超过大小限制 |
| 415 | 二进制或不支持的文本编码 |
| 422 | 参数格式错误 |
| 423 | 文件锁等待超时，可以稍后重试 |
| 500 | 文件系统操作失败 |

可在 `backend/.env` 配置：

```dotenv
WORKSPACE_ROOT=D:/P/Codelin/backend/workspaces
FILE_LOCK_ROOT=D:/P/Codelin/backend/.file-locks
MAX_FILE_BYTES=2097152
FILE_LOCK_TIMEOUT=10
```

同一主机的所有后端进程必须使用相同的 `FILE_LOCK_ROOT`。外部编辑器和 shell 命令不参与这把写锁，前端仍需处理外部更新；此文件接口也不把现有 shell 工具变成操作系统沙箱。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖独立对话、单向加入、用户隔离、自动建工作区与审批恢复、共享索引、checkpoint 清理、删除失败重试、并发保护、空库初始化与限定范围重建，以及文件编辑和 AI SSE 更新事件。默认使用临时文件与隔离数据库；真实 PostgreSQL / Redis 测试设置 `CODELIN_INFRA=1` 和独立的 `CODELIN_TEST_DATABASE_URL` 后启用，不调用真实模型。
