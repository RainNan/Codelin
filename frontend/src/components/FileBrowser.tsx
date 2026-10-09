import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUp, ChevronRight, File, FilePlus2, Folder, FolderPlus, RefreshCw, X } from 'lucide-react'
import { api } from '../lib/api'
import type { DirectoryPage, FileEntry, Workspace } from '../lib/types'
import type { WorkspaceFiles } from '../lib/useWorkspaceFiles'
import { errorText } from '../lib/utils'
import { Button, Modal } from './ui'

export default function FileBrowser({ token, workspace, workspaces, files, busy, demo, workspaceError, onSwitch, onCreate, onRetryWorkspaces, onClose, onOpen, onError }: {
  token?: string; workspace?: Workspace; workspaces: Workspace[]; files: WorkspaceFiles; busy: boolean; demo: boolean
  workspaceError: string; onSwitch: (wid: string) => void; onCreate: (name: string) => Promise<void>
  onRetryWorkspaces: () => void; onClose: () => void; onOpen: (path: string) => void; onError: (error: unknown) => void
}) {
  const [paths, setPaths] = useState<Record<string, string>>({})
  const path = workspace ? paths[workspace.id] || '.' : '.'
  const [listing, setListing] = useState<DirectoryPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')
  const [creation, setCreation] = useState<'file' | 'directory' | 'workspace' | null>(null)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [creationError, setCreationError] = useState('')
  const [pageLoading, setPageLoading] = useState(false)
  const pageEpoch = useRef(0)
  const rows = useRef<(HTMLButtonElement | null)[]>([])
  const wid = workspace?.id
  useEffect(() => {
    pageEpoch.current++; setListing(null); setSelected(''); setError(''); setPageLoading(false)
    if (!wid || !token) { setLoading(false); return }
    const abort = new AbortController()
    setLoading(true)
    api.directory(token, wid, path, 0, abort.signal).then(setListing).catch(e => {
      if (!abort.signal.aborted) { setError(errorText(e)); onError(e) }
    }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [wid, token, path, files.revision]) // Request lifetime follows the directory and workspace.

  function navigate(next: string) { if (wid) setPaths(prev => ({ ...prev, [wid]: next })); setSelected('') }
  const crumbs = path === '.' ? [] : path.split('/')
  const parent = crumbs.slice(0, -1).join('/') || '.'
  function open(entry: FileEntry) { if (entry.type === 'directory') navigate(entry.path); else onOpen(entry.path) }
  function startCreate(type: typeof creation) { setCreation(type); setName(''); setCreationError('') }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || creating) return
    if (creation !== 'workspace' && (/[\\/]/.test(name) || name === '.' || name === '..')) { setCreationError('请输入单个文件或文件夹名称，不包含路径。'); return }
    setCreating(true); setCreationError('')
    try {
      if (creation === 'workspace') await onCreate(name.trim())
      else if (token && wid && creation) {
        const target = path === '.' ? name : `${path}/${name}`
        const result = await api.createEntry(token, wid, target, creation)
        files.refresh(wid)
        if (creation === 'file') onOpen(result.path)
      }
      setCreation(null)
    } catch (e) { setCreationError(errorText(e)); onError(e) }
    finally { setCreating(false) }
  }
  async function loadMore() {
    if (!token || !wid || listing?.next_offset == null || pageLoading) return
    const stamp = pageEpoch.current
    setPageLoading(true); setError('')
    try {
      const next = await api.directory(token, wid, path, listing.next_offset)
      if (stamp === pageEpoch.current) setListing(prev => prev ? { ...next, entries: [...prev.entries, ...next.entries] } : next)
    } catch (e) { if (stamp === pageEpoch.current) { setError(errorText(e)); onError(e) } }
    finally { if (stamp === pageEpoch.current) setPageLoading(false) }
  }
  return <aside className="file-browser" id="workspace-files" aria-label="工作空间文件">
    <div className="file-browser-heading"><h2><Folder size={18} />工作空间</h2><Button variant="ghost" className="icon-button" aria-label="收起文件栏" onClick={onClose}><X size={17} /></Button></div>
    {demo ? <div className="file-empty"><Folder size={30} /><p>演示模式不提供文件。</p><span>连接真实服务后，可以浏览和编辑自己的工作区。</span></div> : <>
      <div className="workspace-picker"><label htmlFor="workspace-picker">当前工作区</label><select id="workspace-picker" value={wid || ''} disabled={busy || !workspaces.length} onChange={e => onSwitch(e.target.value)}><option value="" disabled>选择工作区</option>{workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <Button variant="ghost" onClick={() => startCreate('workspace')} disabled={busy}>创建工作空间</Button>
        <p>{busy ? 'AI 处理期间可浏览文件；完成后可切换工作区。' : '切换工作区会同时切换关联会话。'}</p>
      </div>
      {workspaceError && <div className="file-feedback" role="alert">{workspaceError}<Button onClick={onRetryWorkspaces}>重试工作区列表</Button></div>}
      {!workspace && !workspaceError && <div className="file-empty"><FolderPlus size={30} /><p>{workspaces.length ? '请选择一个工作区' : '还没有工作空间'}</p><span>创建后，文件与 AI 对话会共享同一个项目。</span><Button onClick={() => startCreate('workspace')} disabled={busy}>创建工作空间</Button></div>}
      {workspace && <>
        <nav className="file-breadcrumbs" aria-label="当前目录"><button onClick={() => navigate('.')} title={workspace.name}>根目录</button>{crumbs.map((crumb, index) => <span key={index}><ChevronRight size={12} /><button onClick={() => navigate(crumbs.slice(0, index + 1).join('/'))} title={crumb} aria-current={index === crumbs.length - 1 ? 'page' : undefined}>{crumb}</button></span>)}</nav>
        <div className="file-actions"><Button variant="ghost" className="icon-button" aria-label="返回上一级目录" disabled={path === '.'} onClick={() => navigate(parent)}><ArrowUp size={17} /></Button><Button variant="ghost" className="icon-button" aria-label="刷新目录与文件" onClick={() => files.refresh(workspace.id)}><RefreshCw size={16} /></Button><Button variant="ghost" className="icon-button" aria-label="新建文件" onClick={() => startCreate('file')}><FilePlus2 size={17} /></Button><Button variant="ghost" className="icon-button" aria-label="新建文件夹" onClick={() => startCreate('directory')}><FolderPlus size={17} /></Button></div>
        <div className="file-list-scroll" aria-busy={loading}>
          {loading ? <p className="file-feedback" role="status">正在加载目录…</p> : <>
            {error && <div className="file-feedback" role="alert">{error}<Button onClick={() => files.refresh(workspace.id)}>重试目录</Button>{path !== '.' && <Button onClick={() => navigate(parent)}>返回上一级</Button>}</div>}
            {listing && !listing.entries.length && <div className="file-empty"><Folder size={28} /><p>这个目录还是空的</p><span>从新建文件或文件夹开始。</span></div>}
            <ul className="file-list" aria-label="目录项目">{listing?.entries.map((entry, index) => <li key={entry.path} className={selected === entry.path ? 'file-selected' : ''}>
              <button ref={el => { rows.current[index] = el }} className="file-row" aria-pressed={selected === entry.path} aria-label={`${entry.type === 'directory' ? '文件夹' : '文件'}：${entry.name}`} title={`${entry.name}\n${entry.size == null ? '文件夹' : `${entry.size.toLocaleString()} 字节`} · ${new Date(entry.modified_at).toLocaleString()}`} onClick={() => setSelected(entry.path)} onDoubleClick={() => open(entry)} onKeyDown={e => {
                if (e.key === 'Enter') { e.preventDefault(); open(entry) }
                if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
                  e.preventDefault(); const target = e.key === 'Home' ? 0 : e.key === 'End' ? listing.entries.length - 1 : Math.max(0, Math.min(listing.entries.length - 1, index + (e.key === 'ArrowDown' ? 1 : -1)))
                  rows.current[target]?.focus(); setSelected(listing.entries[target].path)
                }
              }}>{entry.type === 'directory' ? <Folder size={17} className="folder-icon" /> : <File size={17} />}<span>{entry.name}</span>{entry.type === 'file' && <small>{formatSize(entry.size || 0)}</small>}</button>
              <button className="file-open" onClick={() => open(entry)} aria-label={`打开${entry.type === 'directory' ? '文件夹' : '文件'}：${entry.name}`}><ChevronRight size={16} /></button>
            </li>)}</ul>
            {listing?.next_offset != null && <Button className="load-more" disabled={pageLoading} onClick={loadMore}>{pageLoading ? '正在加载…' : '加载更多'}</Button>}
          </>}
        </div>
        <footer className="file-browser-footer"><span>{listing ? `${listing.total} 个项目` : '目录浏览'}</span><span>AI 始终在工作区根目录执行</span></footer>
      </>}
    </>}
    <Modal open={creation !== null} onOpenChange={open => { if (!open && !creating) setCreation(null) }} title={creation === 'workspace' ? '创建工作空间' : creation === 'directory' ? '新建文件夹' : '新建文件'} description={creation === 'workspace' ? '为新项目命名，随后自动建立关联会话。' : `创建于 ${path === '.' ? '根目录' : path}。`}>
      <form onSubmit={create}><label htmlFor="entry-name" className="field-label mt-5">名称</label><input className="input" id="entry-name" autoFocus required value={name} maxLength={creation === 'workspace' ? 128 : 255} aria-invalid={Boolean(creationError)} aria-describedby={creationError ? 'entry-error' : undefined} onChange={e => setName(e.target.value)} />{creationError && <p className="inline-error mt-3" id="entry-error" role="alert">{creationError}</p>}<div className="mt-6 flex justify-end gap-3"><Button onClick={() => setCreation(null)} disabled={creating}>取消</Button><Button type="submit" variant="primary" disabled={creating || !name.trim()}>{creating ? '正在创建…' : '创建'}</Button></div></form>
    </Modal>
  </aside>
}
function formatSize(size: number) { return size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB` }
