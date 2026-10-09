import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import Editor, { DiffEditor, loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'
import JsonWorker from 'monaco-editor/languages/features/json/json.worker.js?worker'
import CssWorker from 'monaco-editor/languages/features/css/css.worker.js?worker'
import HtmlWorker from 'monaco-editor/languages/features/html/html.worker.js?worker'
import TsWorker from 'monaco-editor/languages/features/typescript/ts.worker.js?worker'
import * as Tabs from '@radix-ui/react-tabs'
import { FileCode2, MessageSquarePlus, Save, X } from 'lucide-react'
import type { OpenFile, WorkspaceFiles } from '../lib/useWorkspaceFiles'
import { Button, Modal } from './ui'

// Bundle Monaco and its workers locally: no CDN or third party file-content requests.
self.MonacoEnvironment = { getWorker: (_id, label) => label === 'json' ? new JsonWorker() : ['css', 'scss', 'less'].includes(label) ? new CssWorker() : ['html', 'handlebars', 'razor'].includes(label) ? new HtmlWorker() : ['typescript', 'javascript'].includes(label) ? new TsWorker() : new EditorWorker() }
loader.config({ monaco })
const modelPath = (file: OpenFile) => monaco.Uri.from({ scheme: 'codelin', authority: 'workspace', path: `/${file.wid}/${file.path}` }).toString()
function language(path: string) {
  const extension = path.split('.').at(-1)?.toLowerCase() || ''
  return ({ ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', py: 'python', json: 'json', md: 'markdown', html: 'html', css: 'css', scss: 'scss', sh: 'shell', ps1: 'powershell', yaml: 'yaml', yml: 'yaml', toml: 'ini', sql: 'sql', rs: 'rust', go: 'go', java: 'java', c: 'c', cpp: 'cpp', xml: 'xml', svg: 'xml' } as Record<string, string>)[extension] || 'plaintext'
}
export default function FileEditor({ files, theme, onAttach }: { files: WorkspaceFiles; theme: string; onAttach: (path: string) => void }) {
  const active = files.active
  const [closeTarget, setCloseTarget] = useState<OpenFile | null>(null)
  const [closeBusy, setCloseBusy] = useState(false)
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const viewStates = useRef(new Map<string, monaco.editor.ICodeEditorViewState>())
  const latest = useRef({ files, active }); latest.current = { files, active }
  const ownedModels = useRef(new Set<string>())
  useEffect(() => {
    const retained = new Set(files.files.map(modelPath))
    for (const path of ownedModels.current) if (!retained.has(path)) { monaco.editor.getModel(monaco.Uri.parse(path))?.dispose(); ownedModels.current.delete(path); viewStates.current.delete(path) }
    retained.forEach(path => ownedModels.current.add(path))
  }, [files.files])
  useEffect(() => () => { ownedModels.current.forEach(path => monaco.editor.getModel(monaco.Uri.parse(path))?.dispose()) }, [])
  useLayoutEffect(() => {
    const instance = editor.current
    if (!instance || !active || instance.getModel()?.uri.toString() !== monaco.Uri.parse(modelPath(active)).toString()) return
    const content = active.draft.replace(/^\uFEFF/, '')
    if (instance.getValue() !== content) {
      const state = instance.saveViewState(); instance.setValue(content)
      if (state) instance.restoreViewState(state)
    }
  }, [active?.draft, active?.path, active?.wid])
  useEffect(() => {
    const save = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); const file = latest.current.active
        if (file) void latest.current.files.save(file)
      }
    }
    window.addEventListener('keydown', save)
    return () => window.removeEventListener('keydown', save)
  }, [])
  function activate(path: string) {
    if (active && editor.current) { const state = editor.current.saveViewState(); if (state) viewStates.current.set(modelPath(active), state) }
    files.activate(path)
  }
  async function saveAndClose() {
    if (!closeTarget) return
    const current = files.files.find(file => file.wid === closeTarget.wid && file.path === closeTarget.path)
    if (!current) { setCloseTarget(null); return }
    setCloseBusy(true)
    if (await files.save(current)) { files.close(current); setCloseTarget(null) }
    setCloseBusy(false)
  }
  const closing = files.files.find(file => file.wid === closeTarget?.wid && file.path === closeTarget.path)
  return <section className="file-editor" aria-label="文件编辑器">
    {files.opening && <p className="editor-notice" role="status">正在打开 {files.opening}…</p>}
    {files.openError && <div className="file-feedback" role="alert">{files.openError}<p>无法编辑的内容不会被显示为空文件。</p><Button onClick={files.retryOpen}>重试打开文件</Button></div>}
    {!active ? <div className="editor-empty"><FileCode2 size={34} /><h2>打开文件，开始创造。</h2><p>在工作空间选择文件，双击或点击打开。<br />文件与对话始终关联同一个工作区。</p></div> : <Tabs.Root className="editor-tabs" value={active.path} onValueChange={activate}>
      <Tabs.List className="file-tabs" aria-label="已打开的文件">{files.tabs.map(file => <div className="file-tab-wrap" key={file.path} data-active={active.path === file.path}><Tabs.Trigger className="file-tab" value={file.path} title={file.path}><FileCode2 size={14} /><span>{file.name}</span>{file.draft !== file.base && <span className="dirty-dot" aria-label="未保存">●</span>}{file.external && <span aria-label="外部更新">!</span>}</Tabs.Trigger></div>)}</Tabs.List>
      <Tabs.Content value={active.path} className="editor-content" forceMount>
        <div className="editor-toolbar"><span title={active.path}>{active.path}</span><Button variant="ghost" className="icon-button" aria-label="将当前文件路径添加到对话" onClick={() => onAttach(active.path)}><MessageSquarePlus size={17} /></Button><Button onClick={() => void files.save(active)} disabled={active.saving || Boolean(active.external) || active.base === active.draft}><Save size={15} />{active.saving ? '保存中…' : '保存'}</Button><Button variant="ghost" className="icon-button" aria-label={`关闭文件：${active.name}`} disabled={active.saving} onClick={() => active.draft !== active.base ? setCloseTarget(active) : files.close(active)}><X size={15} /></Button></div>
        {active.external && <div className="external-update" role="status"><p>文件已在外部更新，你的修改已保留。</p><div><Button onClick={() => files.resolve(active, true)}>重新载入</Button><Button onClick={() => files.resolve(active, false)} title="采用外部文件的版本，保留草稿；下次保存会用草稿替换该版本。">保留草稿</Button><Button onClick={() => files.patch(active.wid, active.path, file => ({ ...file, comparing: !file.comparing }))}>{active.comparing ? '返回编辑' : '比较差异'}</Button></div></div>}
        {active.error && <div className="editor-notice" role="alert">{active.error}<Button variant="ghost" onClick={() => void files.check(active.wid, active.path)}>重新检查文件</Button></div>}
        <div className="monaco-region">{active.comparing && active.external ? <><p className="diff-label">左：外部文件 · 右：你的草稿（只读比较）</p><DiffEditor original={active.external.content} modified={active.draft} language={language(active.path)} theme={theme === 'dark' ? 'vs-dark' : 'light'} options={{ readOnly: true, originalEditable: false, automaticLayout: true, renderSideBySide: true, minimap: { enabled: false } }} /></> : <Editor path={modelPath(active)} defaultValue={active.draft.replace(/^\uFEFF/, '')} language={language(active.path)} theme={theme === 'dark' ? 'vs-dark' : 'light'} keepCurrentModel saveViewState loading={<p className="file-feedback" role="status">正在加载编辑器…</p>} options={{ automaticLayout: true, minimap: { enabled: false }, fontSize: 14, lineHeight: 23, padding: { top: 16 }, scrollBeyondLastLine: false, wordWrap: 'on', ariaLabel: `编辑文件：${active.path}`, tabSize: 2 }} onMount={instance => {
          editor.current = instance
          const file = latest.current.active
          if (file) { const state = viewStates.current.get(modelPath(file)); if (state) instance.restoreViewState(state) }
          instance.onDidChangeModel(() => {
            const current = latest.current.active
            if (!current || instance.getModel()?.uri.toString() !== modelPath(current)) return
            const content = current.draft.replace(/^\uFEFF/, '')
            if (instance.getValue() !== content) instance.setValue(content)
            const state = viewStates.current.get(modelPath(current)); if (state) instance.restoreViewState(state)
          })
          instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => { const current = latest.current.active; if (current) void latest.current.files.save(current) })
        }} onChange={value => {
          const file = latest.current.active
          if (file) files.patch(file.wid, file.path, current => ({ ...current, draft: (current.base.startsWith('\uFEFF') ? '\uFEFF' : '') + (value || ''), saved: false }))
        }} />}</div>
        <footer className="editor-footer"><span>{language(active.path)} · UTF-8{active.base.startsWith('\uFEFF') ? ' BOM' : ''} · {active.draft.includes('\r\n') ? 'CRLF' : 'LF'}</span><span role="status">{active.saving ? '正在保存' : active.draft !== active.base ? '未保存修改' : active.saved ? '已保存' : '与文件同步'}</span><span>⌘ / Ctrl + S</span></footer>
      </Tabs.Content>
    </Tabs.Root>}
    <Modal open={Boolean(closeTarget)} onOpenChange={open => { if (!open && !closeBusy) setCloseTarget(null) }} title="保存修改后关闭？" description={`“${closeTarget?.name || ''}”有未保存的修改。`}>
      {closing?.error && <p role="alert" className="inline-error mt-4">{closing.error}</p>}{closing?.external && <p role="alert" className="inline-error mt-4">文件已在外部更新。请取消关闭，在编辑器中处理冲突。</p>}
      <div className="close-file-actions"><Button disabled={closeBusy} onClick={() => setCloseTarget(null)}>取消</Button><Button disabled={closeBusy} onClick={() => { if (closing) files.close(closing); setCloseTarget(null) }}>放弃修改</Button><Button variant="primary" disabled={closeBusy || Boolean(closing?.external)} onClick={saveAndClose}>{closeBusy ? '正在保存…' : '保存并关闭'}</Button></div>
    </Modal>
  </section>
}
