import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { Group, Panel, Separator, usePanelRef, type Layout } from 'react-resizable-panels'
import { ArrowLeft, Columns2, FileCode2, MessageSquare } from 'lucide-react'
import { Button } from './ui'
import type { WorkspaceFiles } from '../lib/useWorkspaceFiles'
const FileEditor = lazy(() => import('./FileEditor'))

function readLayout(key: string): Layout | undefined {
  try {
    const data = JSON.parse(localStorage.getItem(key) || 'null')
    return data && typeof data === 'object' && Object.values(data).every(value => typeof value === 'number' && value >= 0 && value <= 100) ? data : undefined
  } catch { return undefined }
}
function store(key: string, value: unknown) { try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* Layout remains usable without storage. */ } }
export default function Workbench({ sidebar, header, browser, chat, sidebarVisible, filesVisible, setFilesVisible, files, theme, openSequence, status, replyRevision, onAttach }: {
  sidebar: ReactNode; header: ReactNode; browser: ReactNode; chat: ReactNode; sidebarVisible: boolean; filesVisible: boolean
  setFilesVisible: (open: boolean) => void; files: WorkspaceFiles; theme: string; openSequence: number
  status: string; replyRevision: string; onAttach: (path: string) => void
}) {
  const navPanel = usePanelRef(), browserPanel = usePanelRef(), editorPanel = usePanelRef(), chatPanel = usePanelRef()
  const [width, setWidth] = useState(window.innerWidth)
  const [mode, setMode] = useState<'split' | 'file' | 'chat'>(() => {
    try { const saved = JSON.parse(localStorage.getItem('codelin.view') || 'null'); return ['split', 'file', 'chat'].includes(saved) ? saved : 'split' } catch { return 'split' }
  })
  const [tab, setTab] = useState('chat')
  const [unread, setUnread] = useState(false)
  const [outerLayout] = useState(() => readLayout('codelin.columns'))
  const [innerLayout] = useState(() => readLayout('codelin.split'))
  const splitLayout = useRef(innerLayout)
  const [editorLoaded, setEditorLoaded] = useState(false)
  const hasFile = Boolean(files.active || files.opening || files.openError)
  const phone = width < 768, wide = width >= 1200
  const chatVisible = !hasFile || (wide ? mode !== 'file' : tab === 'chat')
  useEffect(() => { if (hasFile) setEditorLoaded(true) }, [hasFile])
  useEffect(() => { const resize = () => setWidth(window.innerWidth); window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize) }, [])
  useEffect(() => { if (openSequence) { setTab('file'); if (window.innerWidth < 768) setFilesVisible(false) } }, [openSequence])
  useEffect(() => { if (phone && hasFile) setFilesVisible(false) }, [phone, hasFile])
  useEffect(() => { if (chatVisible) setUnread(false); else if (replyRevision) setUnread(true) }, [replyRevision, chatVisible])
  useEffect(() => {
    if (phone || !sidebarVisible) navPanel.current?.collapse(); else navPanel.current?.expand()
    if (phone || !filesVisible) browserPanel.current?.collapse(); else browserPanel.current?.expand()
  }, [phone, sidebarVisible, filesVisible])
  useEffect(() => {
    if (!wide) return
    if (!hasFile || mode === 'chat') { editorPanel.current?.collapse(); chatPanel.current?.resize('100%') }
    else if (mode === 'file') { chatPanel.current?.collapse(); editorPanel.current?.resize('100%') }
    else { editorPanel.current?.expand(); chatPanel.current?.expand(); editorPanel.current?.resize(`${splitLayout.current?.editor || 62}%`) }
  }, [wide, hasFile, mode])
  function choose(value: 'split' | 'file' | 'chat') { setMode(value); store('codelin.view', value) }
  const hiddenStatus = status || (unread ? '有新回复' : '对话已保留')
  return <Group role="main" aria-label="编程工作台" className={`workbench-columns ${phone && filesVisible ? 'mobile-files-open' : ''}`} defaultLayout={outerLayout} onLayoutChanged={(layout, meta) => { if (!phone && meta.isUserInteraction) store('codelin.columns', meta.requestedLayout || layout) }}>
    <h1 className="sr-only">Codelin 编程工作台</h1>
    <Panel id="navigation" className={`navigation-panel ${!sidebarVisible ? 'panel-hidden' : ''}`} panelRef={navPanel} defaultSize="240px" minSize="190px" maxSize="320px" collapsible>{sidebar}</Panel>
    {sidebarVisible && !phone && <Separator className="column-separator" aria-label="调整导航栏宽度" />}
    <Panel id="browser" className={`browser-panel ${!filesVisible ? 'panel-hidden' : ''}`} panelRef={browserPanel} defaultSize="260px" minSize="210px" maxSize="380px" collapsible>{browser}</Panel>
    {filesVisible && !phone && <Separator className="column-separator" aria-label="调整文件栏宽度" />}
    <Panel id="main" className="main-panel" minSize="300px">
      <div className="workspace-main">{header}
        {hasFile && <div className="view-toolbar">
          {wide ? <div className="view-switch" aria-label="工作区域布局"><Button variant="ghost" aria-pressed={mode === 'split'} onClick={() => choose('split')}><Columns2 size={15} />分栏</Button><Button variant="ghost" aria-pressed={mode === 'file'} onClick={() => choose('file')}><FileCode2 size={15} />专注文件</Button><Button variant="ghost" aria-pressed={mode === 'chat'} onClick={() => choose('chat')}><MessageSquare size={15} />专注对话</Button></div> : <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="view-switch" aria-label="文件与对话"><Tabs.Trigger value="file" className="button button-ghost">文件</Tabs.Trigger><Tabs.Trigger value="chat" className="button button-ghost">对话</Tabs.Trigger></Tabs.List><Tabs.Content value={tab} className="sr-only">{tab === 'file' ? '当前显示文件编辑器' : '当前显示 AI 对话'}</Tabs.Content></Tabs.Root>}
          {!chatVisible && <button className="hidden-chat-status" aria-live="polite" onClick={() => wide ? choose('chat') : setTab('chat')}><MessageSquare size={14} />{hiddenStatus}</button>}
          {phone && <Button variant="ghost" onClick={() => setFilesVisible(true)}><ArrowLeft size={15} />返回文件</Button>}
        </div>}
        <Group className={`workbench-content ${hasFile ? 'has-file' : 'chat-only'} mode-${mode} tab-${tab}`} defaultLayout={innerLayout} disabled={!wide} onLayoutChanged={(layout, meta) => { if (wide && hasFile && mode === 'split' && meta.isUserInteraction) { splitLayout.current = meta.requestedLayout || layout; store('codelin.split', splitLayout.current) } }}>
          <Panel id="editor" className="editor-panel" panelRef={editorPanel} defaultSize="62%" minSize="25%" collapsible>{editorLoaded && <Suspense fallback={<p role="status" className="file-feedback">正在加载编辑器…</p>}><FileEditor files={files} theme={theme} onAttach={path => { onAttach(path); setTab('chat'); if (mode === 'file') choose('chat') }} /></Suspense>}</Panel>
          {wide && hasFile && mode === 'split' && <Separator className="column-separator" aria-label="调整文件与对话宽度" />}
          <Panel id="chat" className="chat-panel" panelRef={chatPanel} defaultSize="38%" minSize="25%" collapsible><div className="chat-region">{chat}</div></Panel>
        </Group>
      </div>
    </Panel>
  </Group>
}
