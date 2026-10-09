import type { ChatSession, Message } from './types'

export const demoSessions: ChatSession[] = [
  { id: 'demo-overview', title: '理解一个 React 项目', created_at: new Date().toISOString() },
  { id: 'demo-review', title: '让代码更容易维护', created_at: new Date().toISOString() },
]
export const demoMessages: Record<string, Message[]> = {
  'demo-overview': [
    { id: 'demo-user-1', role: 'user', content: '帮我理解这个 React 项目的结构。' },
    { id: 'demo-assistant-1', role: 'assistant', content: '这是一个示例项目，职责分得很清楚。\n\n### 从这里开始\n\n- **`components/`** 存放可复用的界面组件。\n- **`lib/`** 处理接口请求与公共逻辑。\n- **`App.tsx`** 将各个部分连接成完整的工作台。\n\n```tsx\nfunction Welcome() {\n  return <h1>让好想法，成为好代码。</h1>\n}\n```\n\n建议先阅读入口文件，再沿着一个具体交互了解数据如何流动。', tools: [{ id: 'demo-tool-1', name: 'list_dir', args: { path: 'src' }, preview: 'App.tsx\ncomponents/\nlib/\nstyles.css' }], elapsed_ms: 1600 },
  ],
  'demo-review': [
    { id: 'demo-user-2', role: 'user', content: '怎样让代码更容易维护？' },
    { id: 'demo-assistant-2', role: 'assistant', content: '先从最容易验证的小改动开始。\n\n1. 将接口访问集中到一个模块。\n2. 为消息和会话定义明确的类型。\n3. 把错误状态放在触发操作的位置。\n4. 为流式事件解析补充边界测试。\n\n每次只改一个明确的问题，再验证原来的流程仍然可用。', elapsed_ms: 900 },
  ],
}
