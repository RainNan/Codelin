import type { StreamEvent } from './types.ts'

/** Decode complete SSE frames; unfinished frames remain buffered across network chunks. */
export class SSEParser {
  private buffer = ''
  push(chunk: string): StreamEvent[] {
    this.buffer += chunk
    const frames = this.buffer.split(/\r?\n\r?\n/)
    this.buffer = frames.pop() || ''
    return frames.flatMap(frame => {
      let event = 'message'
      const data: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (!data.length) return []
      const value: unknown = JSON.parse(data.join('\n'))
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('服务端返回了无效的事件数据。')
      return [{ event, data: value as Record<string, unknown> }]
    })
  }
}

export async function readSSE(response: Response, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  if (!response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('服务端没有返回流式响应，请检查聊天接口。')
  if (!response.body) throw new Error('浏览器无法读取流式回复。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SSEParser()
  let terminal = false
  try {
    while (true) {
      signal?.throwIfAborted()
      const { value, done } = await reader.read()
      for (const event of parser.push(decoder.decode(value, { stream: !done }))) {
        onEvent(event)
        if (event.event === 'error') throw new Error(String(event.data.message || '生成回复失败。'))
        if (event.event === 'done' || event.event === 'approval_required') terminal = true
      }
      if (done) break
    }
    if (!terminal) throw new Error('连接提前结束，回复可能不完整。请检查后端状态。')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
