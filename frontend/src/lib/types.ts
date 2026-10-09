export interface Identity { token: string; username: string }
export interface ChatSession { id: string; title: string; created_at?: string }
export interface ToolRun { id: string; name: string; args: Record<string, unknown>; preview?: string }
export interface Approval { thread_id: string; reason: string; tools: { name: string; commands: string[] }[] }
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at?: string
  tools?: ToolRun[]
  approval?: Approval
  decision?: 'approved' | 'rejected'
  elapsed_ms?: number
  notice?: string
}
export interface StreamEvent { event: string; data: Record<string, unknown> }
