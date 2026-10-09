import { isValidElement, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, ChevronDown, Copy, Code2, ShieldCheck, Terminal, X } from 'lucide-react'
import type { Message } from '../lib/types'
import { Button } from './ui'
import { cn } from '../lib/utils'

export const toolLabels: Record<string, string> = { list_dir: '查看目录', read_file: '阅读文件', write_file: '写入文件', grep: '搜索代码', run_command: '执行命令', index_codebase: '建立代码索引', search_code: '检索代码' }

function CopyButton({ content, label = '复制' }: { content: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  async function copy() {
    try { await navigator.clipboard.writeText(content); setCopied(true); setError('') }
    catch { setError('复制失败，请手动选择文本。') }
  }
  return <span className="flex items-center gap-2"><Button variant="ghost" className="copy-button" aria-label={copied ? '已复制' : label} onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}<span>{copied ? '已复制' : label}</span></Button>{error && <span role="status" className="text-xs text-muted">{error}</span>}</span>
}

export default function MessageView({ message, streaming, busy, onApprove }: { message: Message; streaming: boolean; busy: boolean; onApprove: (approved: boolean) => void }) {
  if (message.role === 'user') return <article className="user-message"><span className="sr-only">你：</span><p>{message.content}</p></article>
  return <article className="assistant-message" aria-busy={streaming}>
    <div className="assistant-label"><span className="assistant-icon"><Code2 size={16} /></span><span>Codelin</span>{streaming && <span className="text-xs font-normal text-muted">正在思考与执行…</span>}</div>
    {message.tools?.length ? <div className="tool-list">{message.tools.map(tool => <details key={tool.id} className="tool-card"><summary><Terminal size={14} /><span>{toolLabels[tool.name] || tool.name}</span><span className="tool-path">{String(tool.args.path || tool.args.command || tool.args.pattern || '')}</span><span className="ml-auto text-xs text-muted">{tool.preview !== undefined ? '已返回' : streaming ? '执行中' : '未完成'}</span><ChevronDown size={14} className="details-chevron" /></summary><div className="tool-detail"><p className="mb-2 text-xs text-muted">调用参数</p><pre>{JSON.stringify(tool.args, null, 2)}</pre>{tool.preview !== undefined && <><p className="mb-2 mt-4 text-xs text-muted">执行结果预览</p><pre>{tool.preview}</pre></>}</div></details>)}</div> : null}
    {message.content && <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{
      pre({ children }) {
        const child = isValidElement<{ className?: string; children?: React.ReactNode }>(children) ? children : null
        const language = child?.props.className?.replace('language-', '') || '代码'
        return <div className="code-block"><div className="code-toolbar"><span>{language}</span><CopyButton content={String(child?.props.children || '').replace(/\n$/, '')} label="复制代码" /></div><pre>{children}</pre></div>
      },
      a({ children, href }) { return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> },
    }}>{message.content}</Markdown></div>}
    {!message.content && !message.approval && streaming && <p className="mt-4 text-sm text-muted" role="status">正在准备回复…</p>}
    {message.approval && <section className={cn('approval-card', message.decision && 'approval-resolved')} aria-label="命令审批">
      <div className="flex items-center gap-2 font-medium"><ShieldCheck size={18} /><span>{message.decision ? (message.decision === 'approved' ? '已批准执行' : '已拒绝执行') : '这一步，需要你确认。'}</span></div>
      <p className="mt-2 text-sm text-muted text-pretty">{message.approval.reason}</p>
      {message.approval.tools?.map((tool, index) => <pre key={index} className="approval-command">{(tool.commands || []).join('\n')}</pre>)}
      {!message.decision && <div className="mt-4 flex flex-wrap gap-2"><Button variant="primary" disabled={busy} onClick={() => onApprove(true)}><Check size={15} />批准执行</Button><Button disabled={busy} onClick={() => onApprove(false)}><X size={15} />拒绝执行</Button></div>}
    </section>}
    {message.notice && <p role="status" className="message-notice">{message.notice}</p>}
    {!streaming && message.content && <div className="message-footer"><CopyButton content={message.content} label="复制回复" />{message.elapsed_ms !== undefined && <span className="tabular-nums">用时 {(message.elapsed_ms / 1000).toFixed(1)} 秒</span>}</div>}
  </article>
}
