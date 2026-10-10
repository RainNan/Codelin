import { useState } from 'react'
import { ChevronRight, Folder, FolderInput, MessageSquare, Pencil, Plus, Trash2 } from 'lucide-react'
import type { ChatSession, Workspace } from '../lib/types'
import { cn, dateLabel } from '../lib/utils'
import { Button } from './ui'
import SessionTitle from './SessionTitle'

export default function ConversationNav({ sessions, workspaces, filter, activeId, busy, loading, pendingTitles, onSelect, onWorkspace, onCreate, onCreateWorkspace, onRenameSession, onJoin, onDeleteSession, onRenameWorkspace, onDeleteWorkspace }: {
  sessions: ChatSession[]; workspaces: Workspace[]; filter: string; activeId: string | null; busy: boolean; loading: boolean; pendingTitles: Set<string>
  onSelect: (sid: string) => void; onWorkspace: (wid: string) => void; onCreate: (wid: string) => void; onCreateWorkspace: () => void
  onRenameSession: (session: ChatSession) => void; onJoin: (session: ChatSession) => void; onDeleteSession: (session: ChatSession) => void
  onRenameWorkspace: (workspace: Workspace) => void; onDeleteWorkspace: (workspace: Workspace) => void
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const matches = (session: ChatSession) => session.title.toLowerCase().includes(filter.toLowerCase())
  const independent = sessions.filter(session => !session.workspace_id && matches(session))
  const row = (session: ChatSession) => <li className={cn('session-row', session.id === activeId && 'session-selected')} key={session.id}>
    <button className="session-select" disabled={busy || session.deleting} onClick={() => onSelect(session.id)} aria-current={session.id === activeId ? 'page' : undefined}><MessageSquare size={16} /><span className="min-w-0"><SessionTitle title={session.title} pending={pendingTitles.has(session.id)} /><span className="session-date">{session.deleting ? '删除未完成' : dateLabel(session.created_at)}</span></span></button>
    <div className="conversation-actions">
      {!session.workspace_id && <Button variant="ghost" className="icon-button" aria-label={`加入工作区：${session.title}`} disabled={busy || session.deleting || !workspaces.some(item => !item.deleting)} onClick={() => onJoin(session)}><FolderInput size={14} /></Button>}
      <Button variant="ghost" className="icon-button" aria-label={`重命名会话：${session.title}`} disabled={busy || session.deleting} onClick={() => onRenameSession(session)}><Pencil size={14} /></Button>
      <Button variant="ghost" className="icon-button" aria-label={`删除会话：${session.title}`} disabled={busy} onClick={() => onDeleteSession(session)}><Trash2 size={14} /></Button>
    </div>
  </li>
  return <nav className="session-nav" aria-label="会话列表" aria-busy={loading}>
    <div className="sidebar-section-label"><span>工作区</span><Button variant="ghost" className="icon-button" aria-label="新建工作区" disabled={busy} onClick={onCreateWorkspace}><Plus size={15} /></Button></div>
    {workspaces.filter(workspace => workspace.name.toLowerCase().includes(filter.toLowerCase()) || sessions.some(session => session.workspace_id === workspace.id && matches(session))).map(workspace => {
      const children = sessions.filter(session => session.workspace_id === workspace.id && matches(session))
      const expanded = Boolean(filter) || !collapsed[workspace.id]
      return <section className="workspace-group" key={workspace.id} aria-label={workspace.name}>
        <div className="workspace-group-heading">
          <Button variant="ghost" className="icon-button" aria-label={`展开或收起工作区：${workspace.name}`} aria-expanded={expanded} onClick={() => setCollapsed(prev => ({ ...prev, [workspace.id]: !collapsed[workspace.id] }))}><ChevronRight className={cn(expanded && 'rotate-90')} size={14} /></Button>
          <button className="workspace-group-name" disabled={busy || workspace.deleting} onClick={() => onWorkspace(workspace.id)}><Folder size={15} /><span>{workspace.name}{workspace.deleting ? '（删除未完成）' : ''}</span></button>
          <div className="conversation-actions">
            <Button variant="ghost" className="icon-button" aria-label={`在工作区新建会话：${workspace.name}`} disabled={busy || workspace.deleting} onClick={() => onCreate(workspace.id)}><Plus size={14} /></Button>
            <Button variant="ghost" className="icon-button" aria-label={`重命名工作区：${workspace.name}`} disabled={busy || workspace.deleting} onClick={() => onRenameWorkspace(workspace)}><Pencil size={14} /></Button>
            <Button variant="ghost" className="icon-button" aria-label={`删除工作区：${workspace.name}`} disabled={busy} onClick={() => onDeleteWorkspace(workspace)}><Trash2 size={14} /></Button>
          </div>
        </div>
        {expanded && (children.length ? <ul>{children.map(row)}</ul> : <p className="group-empty">{filter ? '没有匹配的对话' : '还没有对话'}</p>)}
      </section>
    })}
    {!workspaces.length && <p className="group-empty">创建工作区来管理项目和对话。</p>}
    <div className="sidebar-section-label independent-heading"><span>独立对话</span><span>{independent.length}</span></div>
    {loading ? <p className="group-empty" role="status">正在加载会话…</p> : independent.length ? <ul>{independent.map(row)}</ul> : <p className="group-empty">{filter ? '没有匹配的对话。' : '从顶部新建一个独立对话。'}</p>}
  </nav>
}
