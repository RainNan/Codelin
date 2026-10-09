# 工作空间与文件接口

所有接口均需要 `Authorization: Bearer <token>`，继续使用现有 JSON 注册 / 登录接口。前端仅传工作区 ID 与相对路径；用户归属和服务器根目录由后端确定。

## 启动与迁移

在 `D:\P\Codelin\backend` 执行：

```powershell
uv sync --group dev
.\.venv\Scripts\python.exe scripts\migrate.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

新增依赖是 Alembic 和 filelock，同时补齐现有 RAG 模块使用的 numpy / rank-bm25 依赖声明。

应用启动也会执行相同的迁移。空数据库创建完整业务表并记录版本；现有数据库通过 Alembic 添加工作区表和会话关联。PostgreSQL 迁移使用事务和迁移锁。

旧会话的目录原地保留，同一用户指向相同目录的会话归入同一个工作区。迁移不移动、覆写或删除项目文件。新目录默认位于 `backend/workspaces/{user_id}/{workspace_id}`，不随服务器启动目录变化。

已有的 `ChatSession.workspace_path` 保留作兼容字段；实际聊天读取 `Workspace.root_path`。工作区不随会话删除而删除。自动降级未开放，避免丢失已经独立于会话的工作区关联。

## 工作区

### GET /api/workspaces

返回当前用户的工作区列表，按创建时间倒序：

```json
[{"id":"工作区ID","name":"项目 A","created_at":"创建时间"}]
```

### POST /api/workspaces

```json
{"name":"项目 A"}
```

成功返回 `201` 和工作区对象。名称不能为空，最长 128 字符。服务器绝对路径不对外返回。

### GET /api/workspaces/{wid}

返回指定工作区对象。不存在或属于其他用户时均返回 `404`。

## 会话

### POST /api/sessions

```json
{"workspace_id":"工作区ID","title":"分析项目"}
```

多个会话可以绑定同一个工作区。响应增加 `workspace_id`：

```json
{"id":"会话ID","title":"分析项目","workspace_id":"工作区ID","created_at":"创建时间"}
```

为兼容原有前端，空请求体仍可创建会话，此时同时创建一个新工作区。

### GET /api/sessions?workspace_id={wid}

按工作区过滤当前用户的会话；省略参数时返回当前用户全部会话。

`POST /api/chat` 和 `POST /api/chat/approve` 的请求格式保持不变。聊天根目录来自会话关联的工作区；浏览器切换目录不修改聊天根目录。审批恢复生成的文本也会保存到消息历史。

`DELETE /api/sessions/{sid}` 删除会话及关联的消息、工具审计和检索记录，保留工作区和文件。LangGraph checkpoint 暂保留，后续可通过单独的维护任务清理；删除后的会话无法通过 API 再访问。

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

测试覆盖当前用户隔离、目录导航、原文保存、错误状态、跨进程版本竞争、写入失败保护、迁移保留旧文件、会话与工作区绑定、删除会话保留文件，以及 AI SSE 更新事件。使用临时文件和测试数据库，不调用真实模型。
