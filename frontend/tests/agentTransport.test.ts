import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Client } from '@langchain/langgraph-sdk'
import { StreamController } from '@langchain/langgraph-sdk/stream'
import { CodelinTransport, agentState } from '../src/lib/agentTransport.ts'
import type { BackendStream } from '../src/lib/agentTransport.ts'

async function sdkRun(transport: CodelinTransport, action: (controller: StreamController) => Promise<void>) {
  const controller = new StreamController({ assistantId: '_', client: new Client({ apiUrl: 'http://127.0.0.1:1' }), transport, threadId: transport.threadId, initialValues: agentState(transport.request.history), optimistic: false })
  const deactivate = controller.activate()
  try {
    await controller.hydrationPromise
    await action(controller)
    await transport.finished
    await new Promise(resolve => setTimeout(resolve, 10))
    return controller.rootStore.getSnapshot()
  } finally { deactivate(); await controller.dispose(); await transport.close() }
}

test('official SDK assembles streamed text, tool results and metadata through Codelin transport', async () => {
  const history = [{ id: 'user', role: 'user' as const, content: '你好' }, { id: 'ai', role: 'assistant' as const, content: '' }]
  const transport = new CodelinTransport({ sessionId: 'test', messageId: 'ai', history, message: '你好' }, async (_body, emit) => {
    emit({ event: 'tool_start', data: { id: 'read', name: 'read_file', args: { path: 'main.py' } } })
    emit({ event: 'tool_result', data: { id: 'read', name: 'read_file', preview: 'print(1)' } })
    emit({ event: 'token', data: { content: '你好，' } })
    emit({ event: 'token', data: { content: '世界！' } })
    emit({ event: 'done', data: { elapsed_ms: 20 } })
  })
  const snapshot = await sdkRun(transport, controller => controller.submit({}))
  assert.deepEqual(snapshot.messages.map(message => [message.id, message.content, message.text]), [['user', '你好', '你好'], ['ai', [{ type: 'text', text: '你好，世界！' }], '你好，世界！']])
  assert.equal(snapshot.toolCalls[0].status, 'finished')
  assert.equal(snapshot.toolCalls[0].output, 'print(1)')
})

test('SDK interrupts pause a run; responding keeps the prefix and resolves resumed tools', async () => {
  const approval = { thread_id: 'test', reason: '确认命令', tools: [{ name: 'run_command', commands: ['npm test'] }] }
  const history = [{ id: 'ai', role: 'assistant' as const, content: '' }]
  const paused = await sdkRun(new CodelinTransport({ sessionId: 'test', messageId: 'ai', history, message: '测试' }, async (_body, emit) => {
    emit({ event: 'token', data: { content: '开始检查。' } })
    emit({ event: 'tool_start', data: { id: 'command', name: 'run_command', args: { command: 'npm test' } } })
    emit({ event: 'approval_required', data: approval })
  }), controller => controller.submit({}))
  assert.equal(paused.isLoading, false)
  assert.deepEqual(paused.interrupt?.value, approval)
  const resumed = await sdkRun(new CodelinTransport({ sessionId: 'test', messageId: 'ai', approved: false, history: [{ id: 'ai', role: 'assistant', content: '开始检查。', approval, tools: [{ id: 'command', name: 'run_command', args: { command: 'npm test' } }] }] }, async (body, emit) => {
    assert.deepEqual(body, { session_id: 'test', approved: false })
    emit({ event: 'tool_result', data: { id: 'command', name: 'run_command', preview: '用户拒绝' } })
    emit({ event: 'token', data: { content: '已拒绝。' } })
    emit({ event: 'done', data: { elapsed_ms: 5 } })
  }), controller => controller.respond(false, { interruptId: 'approval:ai' }))
  assert.equal(resumed.messages[0].text, '开始检查。已拒绝。')
  assert.equal(resumed.toolCalls[0].name, 'run_command')
  assert.deepEqual(resumed.toolCalls[0].input, { command: 'npm test' })
  assert.equal(resumed.toolCalls[0].status, 'finished')
  assert.equal((resumed.values as ReturnType<typeof agentState>).presentation.ai.decision, 'rejected')
})

test('late or rotated subscriptions replay filtered events without resubmitting the backend request', async () => {
  let calls = 0
  const backend: BackendStream = async (_body, emit) => { calls++; emit({ event: 'token', data: { content: '你好' } }); emit({ event: 'done', data: {} }) }
  const transport = new CodelinTransport({ sessionId: 'replay', messageId: 'ai', history: [{ id: 'ai', role: 'assistant', content: '' }], message: '你好' }, backend)
  await transport.send({ id: 1, method: 'run.start', params: { assistant_id: '_', input: {} } })
  await transport.finished
  const readMessages = async () => {
    const handle = transport.openEventStream({ channels: ['messages'] })
    const events = []
    try {
      for await (const event of handle.events) { events.push(event); if (event.method === 'messages' && event.params.data.event === 'message-finish') { handle.close(); break } }
      return events
    } finally { handle.close() }
  }
  assert.deepEqual(await readMessages(), await readMessages())
  assert.equal(calls, 1)
  await transport.close()
})
