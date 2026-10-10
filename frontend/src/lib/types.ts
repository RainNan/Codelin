export interface Identity { token: string; username: string }
export interface ChatSession { id: string; title: string; workspace_id?: string | null; created_at?: string; deleting?: boolean }
export interface Workspace { id: string; name: string; created_at: string; deleting?: boolean }
export interface FileEntry { name: string; path: string; type: 'file' | 'directory'; size: number | null; modified_at: string }
export interface DirectoryPage { path: string; entries: FileEntry[]; total: number; next_offset: number | null }
export interface FileContent extends FileEntry { content: string; version: string }
export interface FileSaved extends FileEntry { version: string; operation: string }
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
