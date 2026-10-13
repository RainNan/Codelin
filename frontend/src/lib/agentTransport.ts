import type { AgentServerAdapter, Event } from '@langchain/react'
import type { Command, CommandResponse, Message as ProtocolMessage, SubscribeParams } from '@langchain/protocol'
import type { Approval, Message, StreamEvent } from './types.ts'

export interface AgentState {
  messages: { id: string; type: 'human' | 'ai'; content: string }[]
  presentation: Record<string, Omit<Message, 'id' | 'role' | 'content'>>
  toolOwners: Record<string, string>
}
export type StreamRequest = {
  sessionId: string; messageId: string; history: Message[]; message?: string; approved?: boolean
}
export type BackendStream = (body: { session_id: string; message: string } | { session_id: string; approved: boolean }, onEvent: (event: StreamEvent) => void, signal: AbortSignal) => Promise<void>

export function agentState(history: Message[]): AgentState {
  return {
    messages: history.map(message => ({ id: message.id, type: message.role === 'user' ? 'human' : 'ai', content: message.content })),
    presentation: Object.fromEntries(history.map(({ id, role: _role, content: _content, ...metadata }) => [id, metadata])),
    toolOwners: Object.fromEntries(history.flatMap(message => (message.tools || []).map(tool => [tool.id, message.id]))),
  }
}

/** Adapt Codelin's authenticated SSE endpoints to the official v2 stream protocol.
 * Each run has its own replay log. Independent SDK subscriptions can open late
 * or rotate their filters without losing events or making another chat request.
 */
export class CodelinTransport implements AgentServerAdapter {
  readonly threadId: string
  readonly request: StreamRequest
  readonly state: AgentState
  error: unknown
  received = false
  private log: Event[] = []
  private listeners = new Set<() => void>()
  private abort = new AbortController()
  private closed = false
  private started = false
  private backendFinished = false
  private toolStarts = new Set<string>()
  private text: string
  private interruptId: string
  private backend: BackendStream
  private onCustom: (event: StreamEvent) => void
  private settle!: () => void
  private settleProjection!: () => void
  readonly finished = new Promise<void>(resolve => { this.settle = resolve })
  readonly projected = new Promise<void>(resolve => { this.settleProjection = resolve })
  completeProjection() { this.settleProjection() }

  constructor(request: StreamRequest, backend: BackendStream, onCustom: (event: StreamEvent) => void = () => {}) {
    this.backend = backend
    this.onCustom = onCustom
    this.request = request
    this.threadId = request.sessionId
    this.state = agentState(request.history)
    this.text = request.history.find(message => message.id === request.messageId)?.content || ''
    this.interruptId = `approval:${request.messageId}`
  }
  async open() {}
  // Codelin exposes saved chat rows, not LangGraph checkpoint state. Seed the
  // local history through initialValues; do not advertise checkpoint hydration
  // or seal the current assistant prefix as a completed server message.
  async getState() { return null }
  async getHistory<T = unknown>() { return [] as { values: T }[] }

  private emit(event: Omit<Event, 'type' | 'seq' | 'event_id'>) {
    if (this.closed) return
    const seq = this.log.length + 1
    this.log.push({ ...event, type: 'event', seq, event_id: `${this.request.messageId}:${seq}` } as Event)
    this.listeners.forEach(wake => wake())
  }
  private lifecycle(event: 'running' | 'completed' | 'interrupted' | 'failed', error?: string) {
    this.emit({ method: 'lifecycle', params: { namespace: [], timestamp: new Date().toISOString(), data: { event, error } } })
  }
  private message(data: Extract<Event, { method: 'messages' }>['params']['data']) {
    this.emit({ method: 'messages', params: { namespace: [], timestamp: new Date().toISOString(), node: 'agent', data } })
  }
  private snapshot() {
    this.state.messages = this.state.messages.map(message => message.id === this.request.messageId ? { ...message, content: this.text } : message)
    this.emit({ method: 'values', params: { namespace: [], timestamp: new Date().toISOString(), data: structuredClone(this.state) } })
  }
  private consume = ({ event, data }: StreamEvent) => {
    if (this.closed) return
    this.received = true
    const metadata = this.state.presentation[this.request.messageId] ||= {}
    if (event === 'token') {
      const text = typeof data.content === 'string' ? data.content : Array.isArray(data.content) ? data.content.map(part => typeof part === 'string' ? part : part?.text || '').join('') : ''
      this.text += text
      this.message({ event: 'content-block-delta', index: 0, delta: { type: 'text-delta', text } })
    } else if (event === 'tool_start' || event === 'tool_result' || event === 'tool_error') {
      const toolId = String(data.id)
      this.state.toolOwners[toolId] = this.request.messageId
      this.snapshot()
      if (event !== 'tool_start' && !this.toolStarts.has(toolId)) {
        const previous = metadata.tools?.find(tool => tool.id === toolId)
        this.emit({ method: 'tools', params: { namespace: [], timestamp: new Date().toISOString(), node: 'execute', data: { event: 'tool-started', tool_call_id: toolId, tool_name: String(data.name || previous?.name || '工具'), input: previous?.args || {} } } })
      }
      this.toolStarts.add(toolId)
      this.emit({ method: 'tools', params: { namespace: [], timestamp: new Date().toISOString(), node: 'execute', data: event === 'tool_start'
        ? { event: 'tool-started', tool_call_id: toolId, tool_name: String(data.name), input: data.args || {} }
        : event === 'tool_error' ? { event: 'tool-error', tool_call_id: toolId, message: String(data.message || '工具执行失败') }
        : { event: 'tool-finished', tool_call_id: toolId, output: String(data.preview ?? '') } } })
    } else if (event === 'approval_required') {
      metadata.approval = data as unknown as Approval
      metadata.decision = undefined
      this.snapshot()
      this.emit({ method: 'input.requested', params: { namespace: [], timestamp: new Date().toISOString(), data: { interrupt_id: this.interruptId, payload: metadata.approval } } })
    } else if (event === 'done') {
      if (typeof data.elapsed_ms === 'number' && Number.isFinite(data.elapsed_ms)) metadata.elapsed_ms = data.elapsed_ms
      this.snapshot()
    } else if (event === 'error') {
      // readSSE throws after delivering this event; finish the lifecycle in catch.
    } else this.onCustom({ event, data })
  }
  async send(command: Command): Promise<CommandResponse> {
    this.abort.signal.throwIfAborted()
    if (command.method !== 'run.start' && command.method !== 'input.respond') return { type: 'success', id: command.id, result: {} }
    if (this.started) throw new Error('当前回复仍在处理。')
    this.started = true
    // Return the command acknowledgement before delivering any live events.
    // This lets the SDK install its resume barrier and open replay subscriptions.
    queueMicrotask(() => { void this.execute() })
    return { type: 'success', id: command.id, result: { run_id: this.request.messageId }, meta: { applied_through_seq: 0 } }
  }
  private async execute() {
    const { sessionId, messageId, message, approved } = this.request
    const metadata = this.state.presentation[messageId] ||= {}
    try {
      this.abort.signal.throwIfAborted()
      if (approved !== undefined) metadata.decision = approved ? 'approved' : 'rejected'
      this.lifecycle('running')
      this.message({ event: 'message-start', role: 'ai', id: messageId })
      this.message({ event: 'content-block-start', index: 0, content: { type: 'text', text: this.text } })
      this.snapshot()
      await this.backend(approved === undefined ? { session_id: sessionId, message: message || '' } : { session_id: sessionId, approved }, this.consume, this.abort.signal)
      this.message({ event: 'content-block-finish', index: 0, content: { type: 'text', text: this.text } })
      this.message({ event: 'message-finish' })
      this.snapshot()
      this.lifecycle(metadata.approval && !metadata.decision ? 'interrupted' : 'completed')
    } catch (error) {
      this.error = error
      if (approved !== undefined && !this.received) metadata.decision = undefined
      // Keep partial text. Never label unfinished tools as successful.
      this.snapshot()
      if (!this.abort.signal.aborted) this.lifecycle('failed', error instanceof Error ? error.message : String(error))
    } finally { this.backendFinished = true; this.settle() }
  }
  events(): AsyncIterable<ProtocolMessage> { return this.openEventStream({ channels: ['values', 'messages', 'tools', 'input', 'lifecycle'] }).events }
  openEventStream(params: SubscribeParams) {
    const transport = this
    let stopped = false
    let wake: (() => void) | undefined
    const close = () => { stopped = true; wake?.() }
    return { ready: Promise.resolve(), close, events: (async function* () {
      let cursor = 0
      try {
        while (!stopped && !transport.closed) {
          while (cursor < transport.log.length) {
            const event = transport.log[cursor++]
            const channel = event.method === 'input.requested' ? 'input' : event.method
            if (params.channels.includes(channel as SubscribeParams['channels'][number])) yield event
          }
          if (stopped || transport.closed) break
          await new Promise<void>(resolve => {
            wake = resolve
            transport.listeners.add(resolve)
            // Recheck after installing the waiter to avoid missing a fast event.
            if (cursor < transport.log.length || stopped || transport.closed) resolve()
          })
          if (wake) transport.listeners.delete(wake)
        }
      } finally { if (wake) transport.listeners.delete(wake) }
    })() }
  }
  async close() {
    if (!this.backendFinished && !this.error) this.error = new DOMException('已停止接收回复。', 'AbortError')
    this.closed = true
    this.abort.abort()
    this.listeners.forEach(wake => wake())
    this.listeners.clear()
    this.settle()
    this.settleProjection()
  }
}
