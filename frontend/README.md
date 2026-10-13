# Codelin 前端

React 19 + TypeScript + Vite 编程工作台。聊天运行时采用官方 `@langchain/react` v1 SDK，文件浏览、Monaco 编辑、工作区及认证继续使用现有 Codelin API。

## 运行

```powershell
npm ci
npm run dev
```

默认地址为 `http://127.0.0.1:5173`，`/api` 代理到后端 8000 端口。通过 `VITE_BACKEND_URL` 修改代理目标；跨源部署可以配置 `VITE_API_BASE_URL`，同时在后端配置对应 CORS。模型密钥只放后端。

## SDK 接入

- `src/lib/agentTransport.ts` 实现官方 `AgentServerAdapter`，将 `/api/chat` 和 `/api/chat/approve` 的事件转换为 SDK v2 的消息、工具、状态、输入中断和生命周期事件。
- `src/lib/useAgentStream.ts` 使用 `useStream`。流式正文来自 `stream.messages`，工具状态来自 `stream.toolCalls`，审批使用 `stream.interrupt` 和 `stream.respond()`，停止接收使用 `stream.stop({ cancel: false })`。
- SDK 独立订阅共享每次请求的事件回放记录，支持延迟订阅和订阅过滤器变化，避免重复提交聊天请求。SSE 字节解码和终止帧校验仍在底层传输中进行。
- `App` 管理认证、工作区和会话缓存；自定义文件变更及会话标题事件交由原有工作台处理。审批续跑保留原消息、工具参数和已有正文。
- 演示模式使用同一 SDK 事件管线，并明确标注演示。它不会连接模型或执行命令。

## 界面

工具卡片展示执行进度、运行中、已返回、失败、等待确认及未完成状态；展开可查看参数和结果。审批卡片集中显示原因、命令及批准/拒绝操作。Markdown 支持常用语言代码高亮、代码复制及长代码折叠。输入框随内容增高，向上阅读时暂停自动滚动，并提供“最新回复”入口。所有新界面遵循已有浅色/深色主题，旋转状态图标遵循减少动态效果设置。

## 验证

```powershell
npm test
npm run build
npm run test:e2e
```

单元测试直接使用官方 SDK 控制器验证文本组装、工具结果、审批续写和订阅回放；浏览器测试使用接口替身及可控流验证逐步到达的事件、停止接收、审批失败重试、代码展示、文件联动、主题和移动端无障碍。真实服务测试仍按项目根目录 README 配置启用。

本次验收：8 项单元测试、28 项浏览器测试通过，1 项真实服务测试未启用，生产构建成功。构建仍提示 SDK 主入口和 Monaco 编辑器包较大；Monaco 保持按需加载，部署时应为静态资源启用压缩与缓存。

## 后端能力边界

现有后端不提供 LangGraph Agent Server 的持久运行、checkpoint 历史或流重连接口。因此本次只接入已有接口能支持的 SDK 能力；不提供时间旅行、分支对话或跨刷新重新加入正在执行的任务。刷新后仍通过消息接口加载已保存正文，待审批状态与工具记录的跨刷新恢复需要后端额外提供状态接口。

“停止接收”仅断开浏览器接收，不保证服务端任务取消。异常中断保留已到达的正文，并提示重新载入已保存消息。后端当前只返回工具输出预览，前端无法恢复未传输的完整结果。

## 官方参考

- [LangChain 前端概览](https://docs.langchain.com/oss/python/langchain/frontend/overview)
- [React SDK 与自定义传输](https://github.com/langchain-ai/langgraphjs/tree/main/libs/sdk-react)
- [工具调用界面](https://docs.langchain.com/oss/python/langchain/frontend/tool-calling)
- [Markdown 消息](https://docs.langchain.com/oss/python/langchain/frontend/markdown-messages)
