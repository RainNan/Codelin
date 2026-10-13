import { useEffect, useMemo, useRef, useState } from 'react'
import { useStream } from '@langchain/react'
import { api } from './api'
import { agentState, CodelinTransport, type AgentState, type BackendStream, type StreamRequest } from './agentTransport'
import type { Approval, Message, StreamEvent } from './types'

const empty = new CodelinTransport({ sessionId: 'idle', messageId: '', history: [] }, async () => {})

/** The SDK owns live message assembly, tool lifecycle, and interrupt handling.
 * App keeps completed conversations in its cache for fast sidebar navigation.
 */
export function useAgentStream(onMessages: (sid: string, messages: Message[]) => void) {
  const [transport, setTransport] = useState(empty)
  const dispatched = useRef<CodelinTransport | null>(null)
  const callbacks = useRef(onMessages); callbacks.current = onMessages
  const initialValues = useMemo(() => agentState(transport.request.history), [transport])
  const stream = useStream<AgentState, Approval>({ transport, threadId: transport.threadId, initialValues, optimistic: false, onCompleted: () => transport.completeProjection() })

  useEffect(() => {
    if (transport === empty || dispatched.current === transport) return
    dispatched.current = transport
    void (async () => {
      try {
        await stream.hydrationPromise
        if (transport.request.approved === undefined) await stream.submit({})
        else await stream.respond(transport.request.approved, { interruptId: `approval:${transport.request.messageId}` })
      } catch (error) { transport.error = error; await transport.close() }
    })()
  }, [transport, stream])

  useEffect(() => {
    if (transport === empty) return
    const projected: Message[] = stream.messages.map(message => {
      const mid = message.id || ''
      const metadata = stream.values.presentation?.[mid] || {}
      const liveTools = stream.toolCalls.filter(tool => stream.values.toolOwners?.[tool.id] === mid).map(tool => ({
        id: tool.id, name: tool.name || metadata.tools?.find(previous => previous.id === tool.id)?.name || '工具',
        args: (tool.input && typeof tool.input === 'object' ? tool.input : metadata.tools?.find(previous => previous.id === tool.id)?.args || {}) as Record<string, unknown>,
        status: tool.status, error: tool.error,
        ...(tool.status === 'finished' ? { preview: typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output) } : {}),
      }))
      const tools = [...(metadata.tools || []).filter(tool => !liveTools.some(live => live.id === tool.id)), ...liveTools]
      return { id: mid, role: message.type === 'human' ? 'user' : 'assistant', content: message.text, ...metadata,
        ...(mid === transport.request.messageId && stream.interrupt ? { approval: stream.interrupt.value } : {}), ...(tools.length ? { tools } : {}) }
    })
    if (projected.length) callbacks.current(transport.threadId, projected)
  }, [transport, stream.messages, stream.toolCalls, stream.values, stream.interrupt])

  async function run(request: StreamRequest, token: string | undefined, demo: boolean, onCustom: (event: StreamEvent) => void) {
    const backend: BackendStream = demo ? async (body, emit) => {
      if ('approved' in body) {
        emit({ event: 'token', data: { content: body.approved ? '\n\n**已批准示例命令。** 演示流程已完成，没有实际执行命令。' : '\n\n**已拒绝示例命令。** 你始终可以决定哪些操作可以继续。' } })
        emit({ event: 'done', data: { elapsed_ms: 900 } })
      } else {
        emit({ event: 'token', data: { content: '这是演示回复，用于预览工作流。连接后端后，Codelin 会根据你的工作区与问题生成真实回答。\n\n下面是一条示例命令审批，你可以体验批准或拒绝。' } })
        emit({ event: 'approval_required', data: { thread_id: body.session_id, reason: '示例命令，需要你确认后继续。演示中不会执行任何命令。', tools: [{ name: 'run_command', commands: ['npm install'] }] } })
      }
    } : (body, emit, signal) => api.stream(token!, body, emit, signal)
    const next = new CodelinTransport(request, backend, onCustom)
    setTransport(next)
    await next.finished
    // Wait for the SDK to apply the terminal event before allowing another turn.
    await next.projected
    if (next.error) throw next.error
    return next.received
  }
  async function stop() {
    // The SDK stops its run consumer; the adapter also owns the underlying
    // Codelin HTTP request, which must be explicitly disconnected.
    await transport.close()
    await stream.stop({ cancel: false })
  }
  return { run, stop, isLoading: stream.isLoading }
}
