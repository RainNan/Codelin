import type { ChatSession, Identity, Message, StreamEvent, Workspace, DirectoryPage, FileContent, FileSaved } from './types'
import { readSSE } from './sse'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
const origin = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function request(path: string, token?: string, init: RequestInit = {}) {
  let response: Response
  try {
    response = await fetch(`${origin}/api${path}`, { ...init, headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers,
    } })
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new ApiError(0, '无法连接 Codelin 服务，请确认后端已启动。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : undefined
    const fallback: Record<number, string> = {
      401: '登录已过期，请重新登录。', 409: '内容已变化或目标已存在，请刷新后重试。',
      403: '没有访问权限或路径超出工作区。', 404: '工作区或文件不存在。',
      413: '文件超过编辑上限。', 415: '二进制或非 UTF-8 文件无法作为文本编辑。', 423: '文件正在写入，请稍后重试。',
      422: '提交的信息不符合要求，请检查后重试。', 429: '请求过于频繁，请稍后重试。',
      500: '服务暂时无法完成请求，请检查后端状态。', 502: '无法连接 Codelin 服务，请确认后端已启动。',
    }
    throw new ApiError(response.status, detail || fallback[response.status] || `请求失败（${response.status}）。`)
  }
  return response
}
export const api = {
  async auth(mode: 'login' | 'register', username: string, password: string): Promise<Identity> {
    return (await request(`/auth/${mode}`, undefined, { method: 'POST', body: JSON.stringify({ username, password }) })).json()
  },
  async sessions(token: string, signal?: AbortSignal): Promise<ChatSession[]> {
    return (await request('/sessions', token, { signal })).json()
  },
  async create(token: string, workspace_id?: string): Promise<ChatSession> {
    return (await request('/sessions', token, { method: 'POST', body: JSON.stringify(workspace_id ? { workspace_id } : {}) })).json()
  },
  async session(token: string, sid: string, signal?: AbortSignal): Promise<ChatSession> {
    return (await request(`/sessions/${encodeURIComponent(sid)}`, token, { signal, cache: 'no-store' })).json()
  },
  async workspaces(token: string, signal?: AbortSignal): Promise<Workspace[]> {
    return (await request('/workspaces', token, { signal, cache: 'no-store' })).json()
  },
  async createWorkspace(token: string, name: string): Promise<Workspace> {
    return (await request('/workspaces', token, { method: 'POST', body: JSON.stringify({ name }) })).json()
  },
  async directory(token: string, wid: string, path: string, offset = 0, signal?: AbortSignal): Promise<DirectoryPage> {
    return (await request(`/workspaces/${encodeURIComponent(wid)}/files?${new URLSearchParams({ path, offset: String(offset), limit: '200' })}`, token, { signal, cache: 'no-store' })).json()
  },
  async file(token: string, wid: string, path: string, signal?: AbortSignal): Promise<FileContent> {
    return (await request(`/workspaces/${encodeURIComponent(wid)}/file?${new URLSearchParams({ path })}`, token, { signal, cache: 'no-store' })).json()
  },
  async saveFile(token: string, wid: string, path: string, content: string, version: string): Promise<FileSaved> {
    return (await request(`/workspaces/${encodeURIComponent(wid)}/file`, token, { method: 'PUT', body: JSON.stringify({ path, content, version }) })).json()
  },
  async createEntry(token: string, wid: string, path: string, type: 'file' | 'directory'): Promise<FileSaved> {
    return (await request(`/workspaces/${encodeURIComponent(wid)}/entries`, token, { method: 'POST', body: JSON.stringify({ path, type }) })).json()
  },
  async remove(token: string, sid: string) {
    await request(`/sessions/${encodeURIComponent(sid)}`, token, { method: 'DELETE' })
  },
  async messages(token: string, sid: string, signal?: AbortSignal): Promise<Omit<Message, 'id'>[]> {
    return (await request(`/sessions/${encodeURIComponent(sid)}/messages`, token, { signal })).json()
  },
  async stream(token: string, body: { session_id: string; message: string } | { session_id: string; approved: boolean }, onEvent: (e: StreamEvent) => void, signal: AbortSignal) {
    const path = 'approved' in body ? '/chat/approve' : '/chat'
    const response = await request(path, token, { method: 'POST', body: JSON.stringify(body), signal })
    await readSSE(response, onEvent, signal)
  },
}
