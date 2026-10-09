import { test } from 'node:test'
import assert from 'node:assert/strict'
import { SSEParser, readSSE } from '../src/lib/sse.ts'

test('buffers partial frames, CRLF and multi-line JSON; ignores keep-alive comments', () => {
  const parser = new SSEParser()
  assert.deepEqual(parser.push(': keepalive\r\n\r\nevent: token\r\ndata: {"content":'), [])
  assert.deepEqual(parser.push('"你好"}\r\n\r'), [])
  assert.deepEqual(parser.push('\nevent: done\ndata: {\ndata: "elapsed_ms": 10}\n\n'), [
    { event: 'token', data: { content: '你好' } }, { event: 'done', data: { elapsed_ms: 10 } },
  ])
})

function response(text: string, fragmentSize = 1) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({ start(controller) {
    for (let offset = 0; offset < bytes.length; offset += fragmentSize) controller.enqueue(bytes.slice(offset, offset + fragmentSize))
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
}

test('preserves Chinese UTF-8 characters even when each byte arrives separately', async () => {
  const events: unknown[] = []
  await readSSE(response('event: token\ndata: {"content":"你好，世界 🌏"}\n\nevent: done\ndata: {"elapsed_ms":12}\n\n'), event => events.push(event))
  assert.deepEqual(events, [{ event: 'token', data: { content: '你好，世界 🌏' } }, { event: 'done', data: { elapsed_ms: 12 } }])
})

test('approval_required is a terminal pause, without requiring done', async () => {
  await readSSE(response('event: approval_required\ndata: {"tools":[],"reason":"审批"}\n\n'), () => {})
})

test('does not report success on a broken stream or server error', async () => {
  await assert.rejects(readSSE(response('event: token\ndata: {"content":"部分回复"}\n\n'), () => {}), /连接提前结束/)
  await assert.rejects(readSSE(response('event: error\ndata: {"message":"模型不可用"}\n\n'), () => {}), /模型不可用/)
  await assert.rejects(readSSE(new Response('<html>Error</html>'), () => {}), /没有返回流式响应/)
})

test('rejects malformed event payloads and honors cancellation', async () => {
  assert.throws(() => new SSEParser().push('event: token\ndata: null\n\n'), /无效的事件数据/)
  const abort = new AbortController(); abort.abort()
  await assert.rejects(readSSE(response('event: done\ndata: {}\n\n'), () => {}, abort.signal), { name: 'AbortError' })
})
