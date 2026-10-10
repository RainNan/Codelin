import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowRight, ArrowUp, Braces, ChevronRight, Code2, FileCode2, Folder, HelpCircle, History, LogOut, Menu, Moon, PanelLeftClose, Plus, Search, Settings2, ShieldCheck, Square, Sun, Terminal, X } from 'lucide-react'
import Auth from './components/Auth'
import MessageView, { toolLabels } from './components/MessageView'
import { Brand, Button, DeleteDialog, Modal } from './components/ui'
import { api, ApiError } from './lib/api'
import { demoMessages, demoSessions } from './lib/demo'
import type { Approval, ChatSession, Identity, Message, StreamEvent } from './lib/types'
import { cn, errorText, id, readIdentity } from './lib/utils'
import Workbench from './components/Workbench'
import FileBrowser from './components/FileBrowser'
import SessionTitle from './components/SessionTitle'
import { useWorkspaceFiles } from './lib/useWorkspaceFiles'
import type { Workspace } from './lib/types'
import ConversationNav from './components/ConversationNav'

type Management = { kind: 'session' | 'join'; item: ChatSession } | { kind: 'workspace'; item: Workspace } | { kind: 'createWorkspace' }

const starters = [
  { icon: FileCode2, title: '读懂项目', description: '理清结构，找到关键逻辑', prompt: '请查看当前工作区的项目结构，解释各个部分的职责和主要执行流程。' },
  { icon: Braces, title: '实现想法', description: '把一个想法变成可运行的代码', prompt: '我想在当前工作区实现一个新功能。请先了解现有代码，再和我确认实现思路。' },
  { icon: Search, title: '解决问题', description: '定位原因，找到清晰的解法', prompt: '请检查当前工作区的代码，帮助我发现潜在的问题，并给出修复建议。' },
  { icon: Terminal, title: '检查代码', description: '审查实现，让每一步更扎实', prompt: '请审查当前工作区的代码质量，关注可维护性、错误处理和测试覆盖。' },
]

export default function App() {
  const [identity, setIdentity] = useState<Identity | null>(readIdentity)
  const [demo, setDemo] = useState(false)
  const [authNotice, setAuthNotice] = useState('')
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [chats, setChats] = useState<Record<string, Message[]>>({})
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [pendingTitles, setPendingTitles] = useState<Set<string>>(() => new Set())
  const [listRevision, setListRevision] = useState(0)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [streamingId, setStreamingId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [draft, setDraft] = useState('')
  const [filter, setFilter] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [sidebarVisible, setSidebarVisible] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [deleteWorkspaceTarget, setDeleteWorkspaceTarget] = useState<Workspace | null>(null)
  const [management, setManagement] = useState<Management | null>(null)
  const [managementValue, setManagementValue] = useState('')
  const [managementError, setManagementError] = useState('')
  const [managementBusy, setManagementBusy] = useState(false)
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('codelin.theme') === 'dark' ? 'dark' : 'light' } catch { return 'light' } })
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>()
  const [workspaceError, setWorkspaceError] = useState('')
  const [workspaceRevision, setWorkspaceRevision] = useState(0)
  const [filesVisible, setFilesVisible] = useState(false)
  const [openSequence, setOpenSequence] = useState(0)
  const [logoutConfirm, setLogoutConfirm] = useState(false)
  const sessionDrafts = useRef<Record<string, string>>({})
  const controller = useRef<AbortController | null>(null)
  const titleRequests = useRef(new Map<string, AbortController>())
  const membershipRequests = useRef(new Map<string, AbortController>())
  const activeRef = useRef(activeId); activeRef.current = activeId
  const composer = useRef<HTMLTextAreaElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const followScroll = useRef(true)
  const streamLock = useRef(false)
  const chatsRef = useRef(chats)
  chatsRef.current = chats
  const busy = streamingId !== null || creating || deleting || managementBusy
  const active = sessions.find(session => session.id === activeId)
  const workspaceId = demo ? undefined : selectedWorkspaceId
  const workspace = workspaces.find(item => item.id === workspaceId)
  const chatWorkspace = workspaces.find(item => item.id === active?.workspace_id)
  const messages = activeId ? chats[activeId] || [] : []
  const pendingApproval = messages.findLast(message => message.approval && !message.decision)
  const canSend = !busy && !loadingSessions && !loadingMessages && !pendingApproval && !historyError && !active?.deleting && !chatWorkspace?.deleting && !(activeId === null && workspace?.deleting)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('codelin.theme', theme) } catch { /* Theme still applies without storage. */ }
  }, [theme])
  useEffect(() => {
    if (identity && activeId && !demo) {
      try { sessionStorage.setItem(`codelin.activeSession.${identity.username}`, activeId) } catch { /* Session selection still works without storage. */ }
    }
  }, [identity, activeId, demo])

  const logout = useCallback((notice = '') => {
    controller.current?.abort()
    titleRequests.current.forEach(request => request.abort())
    titleRequests.current.clear()
    membershipRequests.current.forEach(request => request.abort()); membershipRequests.current.clear()
    setPendingTitles(new Set())
    sessionStorage.removeItem('codelin.auth')
    setIdentity(null); setDemo(false); setSessions([]); setActiveId(null); setChats({}); setDraft('')
    setError(''); setHistoryError(''); setAuthNotice(notice); setSettingsOpen(false); setMobileOpen(false)
    setWorkspaces([]); setSelectedWorkspaceId(undefined); setWorkspaceError(''); setFilesVisible(false); sessionDrafts.current = {}; setLogoutConfirm(false)
    setManagement(null); setDeleteWorkspaceTarget(null); setDeleteTarget(null)
  }, [])
  const authError = useCallback(() => logout('登录已过期，请重新登录。'), [logout])
  const files = useWorkspaceFiles(identity?.token, workspaceId, authError)
  const fileError = useCallback((e: unknown) => { if (e instanceof ApiError && e.status === 401) authError() }, [authError])
  useEffect(() => {
    if (!identity || demo) return
    const abort = new AbortController()
    api.workspaces(identity.token, abort.signal).then(rows => { setWorkspaces(rows); setWorkspaceError('') }).catch(e => {
      if (!abort.signal.aborted) { setWorkspaceError(errorText(e)); fileError(e) }
    })
    return () => abort.abort()
  }, [identity, demo, workspaceRevision, fileError])

  function handleError(e: unknown) {
    if (!demo && e instanceof ApiError && e.status === 401) logout('登录已过期，请重新登录。')
    else setError(errorText(e))
  }

  useEffect(() => {
    if (!identity || demo) return
    const abort = new AbortController()
    setLoadingSessions(true); setError('')
    api.sessions(identity.token, abort.signal).then(rows => {
      if (abort.signal.aborted) return
      let previous: string | null = null
      try { previous = sessionStorage.getItem(`codelin.activeSession.${identity.username}`) } catch { /* Fall back to the most recent session. */ }
      const selected = rows.find(row => row.id === activeRef.current) || rows.find(row => row.id === previous) || rows[0]
      setSessions(rows); setActiveId(selected?.id || null); setSelectedWorkspaceId(selected?.workspace_id || undefined)
    }).catch(e => {
      if (abort.signal.aborted) return
      if (e instanceof ApiError && e.status === 401) logout('登录已过期，请重新登录。')
      else setError(errorText(e))
    }).finally(() => { if (!abort.signal.aborted) setLoadingSessions(false) })
    return () => abort.abort()
  }, [identity, demo, listRevision, logout])

  useEffect(() => {
    setHistoryError('')
    if (!activeId || demo || !identity || chatsRef.current[activeId]) { setLoadingMessages(false); return }
    const abort = new AbortController()
    setLoadingMessages(true)
    api.messages(identity.token, activeId, abort.signal).then(rows => {
      if (!abort.signal.aborted) setChats(prev => ({ ...prev, [activeId]: rows.map(row => ({ ...row, id: id() })) }))
    }).catch(e => {
      if (abort.signal.aborted) return
      if (e instanceof ApiError && e.status === 401) logout('登录已过期，请重新登录。')
      else setHistoryError(errorText(e))
    }).finally(() => { if (!abort.signal.aborted) setLoadingMessages(false) })
    return () => abort.abort()
  }, [activeId, identity, demo, historyRevision, logout])

  useEffect(() => { if (followScroll.current) bottom.current?.scrollIntoView({ block: 'end' }) }, [messages, loadingMessages])
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => () => {
    titleRequests.current.forEach(request => request.abort())
    titleRequests.current.clear()
    membershipRequests.current.forEach(request => request.abort()); membershipRequests.current.clear()
    setPendingTitles(new Set())
  }, [identity?.token])

  function authenticate(value: Identity) {
    sessionStorage.setItem('codelin.auth', JSON.stringify(value))
    setIdentity(value); setDemo(false); setAuthNotice('')
  }
  function enterDemo() {
    setDemo(true); setSessions(demoSessions); setChats(demoMessages); setActiveId(null); setError('')
  }
  function selectSession(sid: string | null) {
    if (busy) return
    sessionDrafts.current[activeId || 'new'] = draft
    setActiveId(sid); setDraft(sessionDrafts.current[sid || 'new'] || ''); setError(''); setHistoryError(''); setMobileOpen(false); followScroll.current = true
    setSelectedWorkspaceId(sessions.find(session => session.id === sid)?.workspace_id || undefined)
  }
  async function switchWorkspace(wid: string) {
    if (busy || streamLock.current || demo) return
    const existing = sessions.find(session => session.workspace_id === wid)
    if (existing) { selectSession(existing.id); setSelectedWorkspaceId(wid); return }
    sessionDrafts.current[activeId || 'new'] = draft
    setActiveId(null); setSelectedWorkspaceId(wid); setDraft(''); setHistoryError(''); setMobileOpen(false)
  }
  async function createWorkspace(name: string) {
    if (!identity || busy) return
    setCreating(true)
    try {
      const created = await api.createWorkspace(identity.token, name)
      setWorkspaces(prev => [created, ...prev])
      sessionDrafts.current[activeId || 'new'] = draft
      setActiveId(null); setSelectedWorkspaceId(created.id); setDraft(''); setHistoryError(''); setFilesVisible(true)
    } finally { setCreating(false) }
  }
  function openFile(path: string) { void files.open(path); setOpenSequence(value => value + 1) }
  function attachFile(path: string) {
    if (active && active.workspace_id !== workspaceId) { setError('此文件不属于当前对话工作区。请先切换对话，或将独立对话加入该工作区。'); return }
    setDraft(value => `${value}${value ? '\n' : ''}请查看文件：\`${path}\``); composer.current?.focus()
  }
  function requestLogout() { if (files.files.some(file => file.draft !== file.base)) setLogoutConfirm(true); else logout() }
  async function createSession(wid?: string) {
    if (busy || streamLock.current) return
    setCreating(true); setError('')
    try {
      const session = demo ? { id: `demo-${id()}`, title: '新会话', created_at: new Date().toISOString() } : await api.create(identity!.token, wid)
      sessionDrafts.current[activeId || 'new'] = draft
      setSessions(prev => [session, ...prev]); setChats(prev => ({ ...prev, [session.id]: [] })); setActiveId(session.id)
      setDraft(''); setHistoryError(''); setMobileOpen(false); followScroll.current = true
      setSelectedWorkspaceId(wid)
      composer.current?.focus()
      return session.id
    } catch (e) { handleError(e) }
    finally { setCreating(false) }
  }
  function updateMessage(sid: string, mid: string, update: (message: Message) => Message) {
    setChats(prev => ({ ...prev, [sid]: (prev[sid] || []).map(message => message.id === mid ? update(message) : message) }))
  }
  function refreshTitle(sid: string, initialTitle: string) {
    if (!identity || titleRequests.current.has(sid)) return
    const abort = new AbortController()
    titleRequests.current.set(sid, abort)
    setPendingTitles(previous => new Set(previous).add(sid))
    const timeout = window.setTimeout(() => abort.abort(), 20000)
    const token = identity.token
    void (async () => {
      try {
        while (!abort.signal.aborted) {
          const session = await api.session(token, sid, abort.signal)
          if (abort.signal.aborted) return
          if (session.title !== initialTitle) {
            setSessions(previous => previous.map(row => row.id === sid ? { ...row, title: session.title } : row))
            return
          }
          await new Promise<void>(resolve => {
            const done = () => { window.clearTimeout(timer); abort.signal.removeEventListener('abort', done); resolve() }
            const timer = window.setTimeout(done, 1000)
            abort.signal.addEventListener('abort', done, { once: true })
          })
        }
      } catch { /* Title failure must not affect the chat or its approval state. */ }
      finally {
        window.clearTimeout(timeout)
        if (titleRequests.current.get(sid) === abort) {
          titleRequests.current.delete(sid)
          setPendingTitles(previous => { const next = new Set(previous); next.delete(sid); return next })
        }
      }
    })()
  }
  function eventHandler(sid: string, mid: string) {
    return ({ event, data }: StreamEvent) => {
      if (event === 'workspace_created' && data.session_id === sid && data.workspace && typeof data.workspace === 'object') {
        const created = data.workspace as Workspace
        if (typeof created.id !== 'string' || typeof created.name !== 'string') return
        setWorkspaces(prev => [created, ...prev.filter(item => item.id !== created.id)])
        setSessions(prev => prev.map(session => session.id === sid ? { ...session, workspace_id: created.id } : session))
        setSelectedWorkspaceId(created.id)
        setFilesVisible(true)
        return
      }
      if (event === 'session_title_pending' && data.session_id === sid && typeof data.title === 'string') {
        refreshTitle(sid, data.title)
        return
      }
      if ((event === 'file_changed' || event === 'workspace_changed') && typeof data.workspace_id === 'string') {
        files.refresh(data.workspace_id, event === 'file_changed' && typeof data.path === 'string' ? data.path : undefined)
        return
      }
      updateMessage(sid, mid, message => {
      if (event === 'token') {
        const content = typeof data.content === 'string' ? data.content : Array.isArray(data.content) ? data.content.map(part => typeof part === 'string' ? part : part?.text || '').join('') : ''
        return { ...message, content: message.content + content }
      }
      if (event === 'tool_start') return { ...message, tools: [...(message.tools || []), { id: String(data.id), name: String(data.name), args: (data.args || {}) as Record<string, unknown> }] }
      if (event === 'tool_result') {
        const tools = message.tools || []
        return { ...message, tools: tools.some(tool => tool.id === data.id) ? tools.map(tool => tool.id === data.id ? { ...tool, preview: String(data.preview ?? '') } : tool) : [...tools, { id: String(data.id), name: String(data.name), args: {}, preview: String(data.preview ?? '') }] }
      }
      if (event === 'approval_required') return { ...message, approval: data as unknown as Approval, decision: undefined }
      if (event === 'done') return { ...message, elapsed_ms: Number(data.elapsed_ms) }
      return message
      })
    }
  }
  async function syncMembership(sid: string) {
    if (!identity || demo) return
    membershipRequests.current.get(sid)?.abort()
    const abort = new AbortController()
    membershipRequests.current.set(sid, abort)
    try {
      const latest = await api.session(identity.token, sid, abort.signal)
      if (abort.signal.aborted) return
      setSessions(prev => prev.map(session => session.id === sid ? latest : session))
      if (latest.workspace_id) {
        const rows = await api.workspaces(identity.token, abort.signal)
        if (abort.signal.aborted) return
        setWorkspaces(rows)
        if (activeRef.current === sid && !sessions.find(session => session.id === sid)?.workspace_id) {
          setSelectedWorkspaceId(latest.workspace_id); setFilesVisible(true)
        }
      }
    } catch (e) { if (!abort.signal.aborted) { if (e instanceof ApiError && e.status === 401) authError(); else setError(previous => previous || errorText(e)) } }
    finally { if (membershipRequests.current.get(sid) === abort) membershipRequests.current.delete(sid) }
  }
  async function send(event: FormEvent) {
    event.preventDefault()
    if (!canSend || !draft.trim() || streamLock.current) return
    const text = draft.trim()
    streamLock.current = true
    let sid = activeId
    setError('')
    if (!sid) {
      setCreating(true)
      try {
        const session = demo ? { id: `demo-${id()}`, title: text.slice(0, 24), created_at: new Date().toISOString() } : await api.create(identity!.token, selectedWorkspaceId)
        sid = session.id
        setSessions(prev => [session, ...prev]); setActiveId(sid)
      } catch (e) { handleError(e); streamLock.current = false; return }
      finally { setCreating(false) }
    }
    const mid = id()
    const assistant: Message = { id: mid, role: 'assistant', content: '' }
    setChats(prev => ({ ...prev, [sid!]: [...(prev[sid!] || []), { id: id(), role: 'user', content: text }, assistant] }))
    setDraft(''); setStreamingId(mid); followScroll.current = true
    const abort = new AbortController(); controller.current = abort
    try {
      if (demo) {
        updateMessage(sid, mid, message => ({ ...message, content: '这是演示回复，用于预览工作流。连接后端后，Codelin 会根据你的工作区与问题生成真实回答。\n\n下面是一条示例命令审批，你可以体验批准或拒绝。', approval: { thread_id: sid!, reason: '示例命令，需要你确认后继续。演示中不会执行任何命令。', tools: [{ name: 'run_command', commands: ['npm install'] }] } }))
      } else await api.stream(identity!.token, { session_id: sid, message: text }, eventHandler(sid, mid), abort.signal)
    } catch (e) {
      if (abort.signal.aborted) updateMessage(sid, mid, m => ({ ...m, notice: '已停止接收回复。服务端可能仍在执行，稍后可重新载入会话。' }))
      else { updateMessage(sid, mid, m => ({ ...m, notice: errorText(e) })); handleError(e) }
    } finally { void syncMembership(sid); setStreamingId(null); streamLock.current = false; controller.current = null }
  }
  async function approve(approved: boolean) {
    if (!activeId || !pendingApproval || busy || streamLock.current) return
    const sid = activeId, mid = pendingApproval.id
    const originalApproval = pendingApproval.approval
    streamLock.current = true; setStreamingId(mid); setError(''); followScroll.current = true
    updateMessage(sid, mid, m => ({ ...m, decision: approved ? 'approved' : 'rejected', notice: undefined }))
    const abort = new AbortController(); controller.current = abort
    let resumed = false
    try {
      if (demo) updateMessage(sid, mid, m => ({ ...m, content: m.content + (approved ? '\n\n**已批准示例命令。** 演示流程已完成，没有实际执行命令。' : '\n\n**已拒绝示例命令。** 你始终可以决定哪些操作可以继续。') }))
      else await api.stream(identity!.token, { session_id: sid, approved }, e => { resumed = true; eventHandler(sid, mid)(e) }, abort.signal)
    } catch (e) {
      const notice = abort.signal.aborted ? '已停止接收。审批请求可能已被处理，请检查后端状态后再继续。' : errorText(e)
      updateMessage(sid, mid, m => ({ ...m, notice, ...(resumed ? {} : { approval: originalApproval, decision: undefined }) }))
      if (!abort.signal.aborted) handleError(e)
    } finally { void syncMembership(sid); setStreamingId(null); streamLock.current = false; controller.current = null }
  }
  async function removeSession() {
    if (!deleteTarget || deleting) return
    setDeleting(true); setDeleteError('')
    try {
      if (!demo) await api.remove(identity!.token, deleteTarget.id)
      titleRequests.current.get(deleteTarget.id)?.abort()
      membershipRequests.current.get(deleteTarget.id)?.abort(); membershipRequests.current.delete(deleteTarget.id)
      titleRequests.current.delete(deleteTarget.id)
      setPendingTitles(previous => { const next = new Set(previous); next.delete(deleteTarget.id); return next })
      setSessions(prev => prev.filter(session => session.id !== deleteTarget.id))
      setChats(prev => { const next = { ...prev }; delete next[deleteTarget.id]; return next })
      delete sessionDrafts.current[deleteTarget.id]
      if (activeId === deleteTarget.id) setActiveId(null)
      setDeleteTarget(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setDeleteTarget(null); logout('登录已过期，请重新登录。') }
      else setDeleteError(errorText(e))
    } finally { setDeleting(false) }
  }
  function openManagement(target: Management) {
    setManagement(target); setManagementError('')
    setManagementValue(target.kind === 'createWorkspace' ? '' : target.kind === 'workspace' ? target.item.name : target.kind === 'session' ? target.item.title : workspaces.find(item => !item.deleting)?.id || '')
  }
  async function submitManagement(event: FormEvent) {
    event.preventDefault()
    if (!management || !managementValue.trim() || managementBusy) return
    setManagementBusy(true); setManagementError('')
    try {
      if (management.kind === 'createWorkspace') await createWorkspace(managementValue.trim())
      else if (management.kind === 'workspace') {
        const updated = await api.renameWorkspace(identity!.token, management.item.id, managementValue.trim())
        setWorkspaces(prev => prev.map(item => item.id === updated.id ? updated : item))
      } else {
        const target = management.item
        membershipRequests.current.get(target.id)?.abort(); membershipRequests.current.delete(target.id)
        const patch = management.kind === 'join' ? { workspace_id: managementValue } : { title: managementValue.trim() }
        const updated = demo ? { ...target, ...patch } : await api.updateSession(identity!.token, target.id, patch)
        setSessions(prev => prev.map(item => item.id === updated.id ? updated : item))
        if (management.kind === 'session') {
          titleRequests.current.get(target.id)?.abort(); titleRequests.current.delete(target.id)
          setPendingTitles(prev => { const next = new Set(prev); next.delete(target.id); return next })
        }
        if (management.kind === 'join' && activeId === updated.id) setSelectedWorkspaceId(updated.workspace_id || undefined)
      }
      setManagement(null)
    } catch (e) { setManagementError(errorText(e)); fileError(e) }
    finally { setManagementBusy(false) }
  }
  async function removeWorkspace() {
    if (!deleteWorkspaceTarget || deleting || !identity) return
    const wid = deleteWorkspaceTarget.id
    setDeleting(true); setDeleteError('')
    try {
      await api.removeWorkspace(identity.token, wid)
      const removed = new Set(sessions.filter(session => session.workspace_id === wid).map(session => session.id))
      removed.forEach(sid => { titleRequests.current.get(sid)?.abort(); titleRequests.current.delete(sid); membershipRequests.current.get(sid)?.abort(); membershipRequests.current.delete(sid); delete sessionDrafts.current[sid] })
      setPendingTitles(prev => new Set([...prev].filter(sid => !removed.has(sid))))
      setSessions(prev => prev.filter(session => !removed.has(session.id)))
      setChats(prev => Object.fromEntries(Object.entries(prev).filter(([sid]) => !removed.has(sid))))
      setWorkspaces(prev => prev.filter(item => item.id !== wid))
      files.dropWorkspace(wid)
      if (removed.has(activeId || '')) { setActiveId(null); setDraft(''); setHistoryError('') }
      if (selectedWorkspaceId === wid) setSelectedWorkspaceId(undefined)
      setDeleteWorkspaceTarget(null)
    } catch (e) { setDeleteError(errorText(e)); fileError(e); setWorkspaceRevision(value => value + 1) }
    finally { setDeleting(false) }
  }
  function refreshHistory() {
    if (!activeId || busy) return
    const next = { ...chatsRef.current }
    delete next[activeId]
    chatsRef.current = next
    setChats(next)
    setHistoryRevision(value => value + 1)
  }

  if (!identity && !demo) return <Auth onAuth={authenticate} onDemo={enterDemo} notice={authNotice} />

  const sidebar = <>
    <div className="sidebar-brand"><Brand small /><Button variant="ghost" className="icon-button hidden md:inline-flex" aria-label="收起侧栏" onClick={() => setSidebarVisible(false)}><PanelLeftClose size={17} /></Button></div>
    <Button className="new-session" onClick={() => createSession()} disabled={busy || loadingSessions}><Plus size={17} />新建会话<span className="ml-auto"><ArrowRight size={15} /></span></Button>
    <Button variant="ghost" className="workspace-nav-button" aria-expanded={filesVisible} aria-controls="workspace-files" onClick={() => { setFilesVisible(value => !value); setMobileOpen(false) }}><Folder size={17} />工作空间<ChevronRight className={cn('ml-auto', filesVisible && 'rotate-90')} size={15} /></Button>
    <div className="sidebar-search"><Search size={15} /><input aria-label="搜索会话" placeholder="搜索会话" value={filter} onChange={e => setFilter(e.target.value)} /></div>
    <ConversationNav sessions={sessions} workspaces={workspaces} filter={filter} activeId={activeId} busy={busy} loading={loadingSessions} pendingTitles={pendingTitles}
      onSelect={selectSession} onWorkspace={switchWorkspace} onCreate={wid => { void createSession(wid) }} onCreateWorkspace={() => openManagement({ kind: 'createWorkspace' })}
      onRenameSession={item => openManagement({ kind: 'session', item })} onJoin={item => openManagement({ kind: 'join', item })}
      onDeleteSession={item => { setDeleteTarget(item); setDeleteError('') }} onRenameWorkspace={item => openManagement({ kind: 'workspace', item })}
      onDeleteWorkspace={item => { setDeleteWorkspaceTarget(item); setDeleteError('') }} />
    <div className="sidebar-bottom"><div className="workspace-note"><ShieldCheck size={17} /><div><p>关联工作空间</p><span>文件与对话，共享项目。</span></div></div><Button variant="ghost" className="sidebar-bottom-button" onClick={() => setHelpOpen(true)}><HelpCircle size={17} />使用指南<ChevronRight className="ml-auto" size={15} /></Button><Button variant="ghost" className="account-button" onClick={() => setSettingsOpen(true)}><span className="avatar">{(demo ? 'D' : identity!.username.slice(0, 1)).toUpperCase()}</span><span className="min-w-0 text-left"><span className="block truncate font-medium">{demo ? '演示体验' : identity!.username}</span><span className="block text-xs text-muted">{demo ? '示例工作空间' : '个人工作空间'}</span></span><Settings2 className="ml-auto shrink-0" size={16} /></Button></div>
  </>

  return <div className="workspace">
    <a href="#composer" className="skip-link">跳转到消息输入</a>
    <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}><Dialog.Portal><Dialog.Overlay className="modal-overlay md:hidden" /><Dialog.Content className="mobile-sidebar" onCloseAutoFocus={event => { event.preventDefault(); document.getElementById('mobile-nav-trigger')?.focus() }}><Dialog.Title className="sr-only">会话导航</Dialog.Title><Dialog.Description className="sr-only">新建、搜索或切换你的会话。</Dialog.Description><Dialog.Close asChild><Button className="mobile-close icon-button" variant="ghost" aria-label="关闭导航"><X size={18} /></Button></Dialog.Close>{sidebar}</Dialog.Content></Dialog.Portal></Dialog.Root>
    <Workbench sidebar={<aside className="sidebar">{sidebar}</aside>} sidebarVisible={sidebarVisible} filesVisible={filesVisible} setFilesVisible={setFilesVisible} files={files} theme={theme} openSequence={openSequence} status={busy ? '正在生成' : pendingApproval ? '等待审批' : ''} replyRevision={messages.filter(message => message.role === 'assistant').map(message => message.content).join('')} onAttach={attachFile}
      browser={<FileBrowser token={identity?.token} workspace={workspace} workspaces={workspaces} files={files} busy={busy} demo={demo} workspaceError={workspaceError} onSwitch={wid => setSelectedWorkspaceId(wid)} onCreate={createWorkspace} onRetryWorkspaces={() => setWorkspaceRevision(value => value + 1)} onClose={() => setFilesVisible(false)} onOpen={openFile} onError={fileError} />}
      header={<>
      <header role="none" className="workspace-header"><div className="flex min-w-0 items-center gap-3"><Button variant="ghost" className="icon-button md:hidden" id="mobile-nav-trigger" aria-label="打开会话导航" onClick={() => setMobileOpen(true)}><Menu size={19} /></Button>{!sidebarVisible && <Button variant="ghost" className="icon-button hidden md:inline-flex" aria-label="展开侧栏" onClick={() => setSidebarVisible(true)}><Menu size={19} /></Button>}<Button variant="ghost" className="icon-button" aria-label="工作空间文件" aria-expanded={filesVisible} aria-controls="workspace-files" onClick={() => setFilesVisible(value => !value)}><Folder size={18} /></Button><span className="header-section">工作台</span><ChevronRight size={13} className="shrink-0 text-muted" /><span className="min-w-0 text-sm font-medium"><SessionTitle title={active?.title || '新的可能'} pending={Boolean(activeId && pendingTitles.has(activeId))} /></span></div><div className="flex items-center gap-3"><span className={cn('status-pill', demo && 'demo-pill')}>{demo ? '演示模式' : busy ? '正在处理' : pendingApproval ? '等待审批' : 'AI 编程助手'}</span><Button variant="ghost" className="icon-button" aria-label={theme === 'light' ? '切换到深色模式' : '切换到浅色模式'} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</Button></div></header>
      {demo && <section className="demo-banner" aria-label="演示提示"><span>你正在体验演示模式，回复和执行记录均为示例。</span><button onClick={() => logout()} disabled={busy}>连接真实服务<ArrowRight size={13} /></button></section>}
      {!demo && <div className="membership-bar"><span>{active ? chatWorkspace ? `对话工作区：${chatWorkspace.name}` : '独立对话' : workspace ? `工作区：${workspace.name} · 尚未选择对话` : '独立对话'}</span>{active && !active.workspace_id && <Button variant="ghost" disabled={busy || !workspaces.some(item => !item.deleting)} onClick={() => openManagement({ kind: 'join', item: active })}>加入工作区</Button>}{!active && workspace && <Button variant="ghost" disabled={busy || workspace.deleting} onClick={() => createSession(workspace.id)}>在此工作区新建对话</Button>}</div>}
      </>}
      chat={<>
      <section aria-label="对话消息" className="conversation-scroll" onScroll={event => { const el = event.currentTarget; followScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }}>
        {loadingMessages ? <div className="message-skeleton" role="status" aria-label="正在加载消息"><div className="skeleton ml-auto h-14 w-2/3" /><div className="skeleton mt-10 h-5 w-32" /><div className="skeleton mt-5 h-5 w-full" /><div className="skeleton mt-3 h-5 w-4/5" /><div className="skeleton mt-3 h-5 w-3/5" /></div> : historyError ? <div className="history-error"><History size={28} /><h1 className="mt-4 text-xl font-semibold text-balance">暂时无法载入会话</h1><p role="alert" className="mt-2 text-sm text-muted">{historyError}</p><Button className="mt-6" onClick={refreshHistory}>重新载入</Button></div> : messages.length ? <div className="conversation-messages">{messages.map(message => <MessageView key={message.id} message={message} streaming={streamingId === message.id} busy={busy} onApprove={approve} />)}<div ref={bottom} /></div> : <section className="welcome">
          <div className="welcome-symbol"><Code2 size={36} strokeWidth={1.6} /></div>
          <p className="welcome-eyebrow">好代码，从一个好问题开始。</p>
          <h1>让好想法，<br className="sm:hidden" /><span className="text-muted">成为好代码。</span></h1>
          <p className="welcome-description">一起探索、构建和改进。<br />说说你想做什么，剩下的我们一起完成。</p>
          <div className="starter-grid">{starters.map(starter => <button className="starter-card" key={starter.title} disabled={!canSend} onClick={() => { setDraft(starter.prompt); composer.current?.focus() }}><starter.icon size={21} strokeWidth={1.6} /><span className="starter-title">{starter.title}<ArrowRight size={14} /></span><span className="starter-description">{starter.description}</span></button>)}</div>
          <p className="welcome-note"><ShieldCheck size={14} />影响环境的命令，会先征求你的确认。</p>
        </section>}
      </section>
      <section className="composer-region" aria-label="消息输入">
        {error && <div className="action-error" role="alert"><p>{error}</p><div className="flex items-center gap-2">{!busy && <Button variant="ghost" onClick={() => { setListRevision(v => v + 1); setError('') }}>重新连接</Button>}<Button variant="ghost" className="icon-button" aria-label="关闭错误提示" onClick={() => setError('')}><X size={16} /></Button></div></div>}
        <form className="composer" onSubmit={send} aria-busy={busy}><label htmlFor="composer" className="sr-only">给 Codelin 发送消息</label><textarea ref={composer} id="composer" value={draft} onChange={e => setDraft(e.target.value)} placeholder={pendingApproval ? '请先批准或拒绝上方的命令。' : '有什么想法？从这里开始…'} disabled={!canSend} rows={3} maxLength={32000} aria-describedby="composer-hint" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} /><div className="composer-toolbar"><span><Code2 size={14} />{demo ? '示例工作空间' : active ? chatWorkspace?.name || '独立对话' : workspace?.name || '独立对话'}</span>{streamingId ? <Button className="send-button" aria-label="停止接收回复" onClick={() => controller.current?.abort()}><Square size={15} fill="currentColor" /></Button> : <Button className="send-button" variant="primary" aria-label="发送消息" type="submit" disabled={!canSend || !draft.trim()}><ArrowUp size={19} /></Button>}</div></form>
        <div className="composer-caption" id="composer-hint"><span>{pendingApproval ? '等待你的审批后继续。' : creating ? '正在创建会话…' : 'Codelin 可能会出错，请核查重要结果。'}</span><span className="hidden sm:inline">Enter 发送 · Shift + Enter 换行</span></div>
        {activeId && messages.length > 0 && !busy && !demo && <button className="reload-history" onClick={refreshHistory}>重新载入已保存的消息</button>}
      </section>      </>} />
    <Modal open={logoutConfirm} onOpenChange={setLogoutConfirm} title="退出前还有未保存的文件" description="取消退出并保存文件，或放弃本次草稿后退出。"><div className="close-file-actions"><Button onClick={() => setLogoutConfirm(false)}>取消退出</Button><Button variant="danger" onClick={() => logout()}>放弃草稿并退出</Button></div></Modal>
    <DeleteDialog title={deleteTarget?.title || ''} open={Boolean(deleteTarget)} onOpenChange={open => { if (!open) setDeleteTarget(null) }} onDelete={removeSession} busy={deleting} error={deleteError} />
    <DeleteDialog workspace title={deleteWorkspaceTarget?.name || ''} open={Boolean(deleteWorkspaceTarget)} onOpenChange={open => { if (!open) setDeleteWorkspaceTarget(null) }} onDelete={removeWorkspace} busy={deleting} error={deleteError}
      description={`“${deleteWorkspaceTarget?.name || ''}”及其中的 ${sessions.filter(session => session.workspace_id === deleteWorkspaceTarget?.id).length} 个对话、所有项目文件和未保存的文件草稿将被永久删除。此操作无法撤销。`} />
    <Modal open={Boolean(management)} onOpenChange={open => { if (!open && !managementBusy) setManagement(null) }}
      title={management?.kind === 'join' ? '加入工作区' : management?.kind === 'createWorkspace' ? '新建工作区' : management?.kind === 'workspace' ? '重命名工作区' : '重命名会话'}
      description={management?.kind === 'join' ? '聊天记录会保留。加入后，此对话不能移出或转入其他工作区。' : management?.kind === 'createWorkspace' ? '先建立空工作区，再按需在其中新建对话。' : '名称只用于展示，不会改变聊天记录或项目文件。'}>
      <form onSubmit={submitManagement}>
        <label htmlFor="management-value" className="field-label mt-5">{management?.kind === 'join' ? '目标工作区' : '名称'}</label>
        {management?.kind === 'join' ? <select className="input" id="management-value" value={managementValue} disabled={managementBusy} onChange={event => setManagementValue(event.target.value)}>{workspaces.filter(item => !item.deleting).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select> : <input className="input" id="management-value" autoFocus required maxLength={128} disabled={managementBusy} value={managementValue} onChange={event => setManagementValue(event.target.value)} />}
        {managementError && <p role="alert" className="inline-error mt-3">{managementError}</p>}
        <div className="mt-6 flex justify-end gap-3"><Button disabled={managementBusy} onClick={() => setManagement(null)}>取消</Button><Button type="submit" variant="primary" disabled={managementBusy || !managementValue.trim()}>{managementBusy ? '正在保存…' : management?.kind === 'join' ? '确认加入' : '保存'}</Button></div>
      </form>
    </Modal>
    <Modal open={settingsOpen} onOpenChange={setSettingsOpen} title="你的工作空间" description="保持专注，也保持自己的习惯。"><div className="settings-row"><span>外观</span><Button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}{theme === 'light' ? '深色模式' : '浅色模式'}</Button></div><div className="settings-row"><span>账户</span><span className="text-sm text-muted">{demo ? '演示模式' : identity?.username}</span></div><p className="mt-4 text-xs leading-6 text-muted">{demo ? '演示不会连接服务或执行命令。退出后可以登录真实账户。' : '登录信息仅保存在当前浏览器标签页。会话与文件共享工作区，浏览目录不会改变 AI 的执行根目录。'}</p><Button className="mt-6 w-full justify-center" disabled={busy} onClick={requestLogout}><LogOut size={16} />{demo ? '退出演示' : '退出登录'}</Button></Modal>
    <Modal open={helpOpen} onOpenChange={setHelpOpen} title="让协作自然发生。" description="从一个具体的问题开始，逐步完成你的目标。"><ol className="help-steps"><li><span>01</span><div><h3>开始一个对话</h3><p>顶部新建独立对话，也可在工作区内新建。独立对话加入工作区后不能移出或转入其他工作区。</p></div></li><li><span>02</span><div><h3>描述你的想法</h3><p>普通问题直接回答；需要项目工具时，独立对话会自动关联一个新工作区。浏览其他工作区不会改变当前对话归属。</p></div></li><li><span>03</span><div><h3>查看过程，确认操作</h3><p>回复实时呈现。展开执行记录查看细节，遇到命令审批时选择批准或拒绝。</p></div></li></ol><div className="help-tools"><p className="mb-3 text-xs text-muted">当前后端提供的工具</p><div className="flex flex-wrap gap-2">{['list_dir', 'read_file', 'write_file', 'grep', 'run_command'].map(tool => <span key={tool}>{toolLabels[tool]}</span>)}</div></div></Modal>
  </div>
}

