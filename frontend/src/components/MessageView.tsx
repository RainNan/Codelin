import { isValidElement, memo, useEffect, useMemo, useState, type ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import sql from 'highlight.js/lib/languages/sql'
import { Check, ChevronDown, Copy, Code2, ShieldCheck, Terminal, X, CircleAlert, FileCode2, Folder, Search, LoaderCircle, Clock3 } from 'lucide-react'
import type { Message, ToolRun } from '../lib/types'
import { Button } from './ui'
import { cn } from '../lib/utils'

for (const [name, language] of Object.entries({ javascript, typescript, python, bash, json, css, xml, sql })) hljs.registerLanguage(name, language)
hljs.registerAliases(['tsx', 'ts'], { languageName: 'typescript' })
hljs.registerAliases(['jsx', 'js'], { languageName: 'javascript' })
hljs.registerAliases(['html', 'vue'], { languageName: 'xml' })
hljs.registerAliases(['shell', 'sh', 'zsh'], { languageName: 'bash' })

export const toolLabels: Record<string, string> = { list_dir: '查看目录', read_file: '阅读文件', write_file: '写入文件', grep: '搜索代码', run_command: '执行命令', index_codebase: '建立代码索引', search_code: '检索代码' }
const toolIcons = { list_dir: Folder, read_file: FileCode2, write_file: FileCode2, grep: Search, search_code: Search, run_command: Terminal, index_codebase: Code2 }

function CopyButton({ content, label = '复制' }: { content: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (copied) { const timer = window.setTimeout(() => setCopied(false), 1800); return () => window.clearTimeout(timer) } }, [copied])
  async function copy() {
    try { await navigator.clipboard.writeText(content); setCopied(true); setError('') }
    catch { setError('复制失败，请手动选择文本。') }
  }
  return <span className="copy-control"><Button variant="ghost" className="copy-button" aria-label={copied ? '已复制' : label} onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}<span>{copied ? '已复制' : label}</span></Button>{error && <span role="status" className="text-xs text-muted">{error}</span>}</span>
}

const CodeBlock = memo(function CodeBlock({ children }: { children?: ReactNode }) {
  const [expanded, setExpanded] = useState(false)
  const child = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children : null
  const language = child?.props.className?.replace('language-', '') || ''
  const content = String(child?.props.children || '').replace(/\n$/, '')
  // highlight.js escapes source text; never inject model-provided HTML directly.
  const highlighted = useMemo(() => language && hljs.getLanguage(language) ? hljs.highlight(content, { language, ignoreIllegals: true }).value : null, [content, language])
  const long = content.split('\n').length > 18
  return <div className={cn('code-block', long && !expanded && 'code-collapsed')}><div className="code-toolbar"><span><Code2 size={14} />{language || '代码'}</span><CopyButton content={content} label="复制代码" /></div><pre>{highlighted === null ? children : <code className={`hljs language-${language}`} dangerouslySetInnerHTML={{ __html: highlighted }} />}</pre>{long && <button className="code-expand" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? '收起代码' : `展开全部 ${content.split('\n').length} 行`}<ChevronDown size={14} /></button>}</div>
})

const MessageMarkdown = memo(function MessageMarkdown({ content }: { content: string }) {
  return <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{
    pre: CodeBlock,
    // Each assistant turn is a level-2 section. Model headings describe sections
    // inside that turn, regardless of the markdown level the model chose.
    h1: ({ children }) => <h3 className="markdown-h1">{children}</h3>,
    h2: ({ children }) => <h3 className="markdown-h2">{children}</h3>,
    h3: ({ children }) => <h3>{children}</h3>,
    h4: ({ children }) => <h3>{children}</h3>,
    h5: ({ children }) => <h3>{children}</h3>,
    h6: ({ children }) => <h3>{children}</h3>,
    a({ children, href }) { return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> },
  }}>{content}</Markdown></div>
})

function ToolCard({ tool, streaming, waiting }: { tool: ToolRun; streaming: boolean; waiting: boolean }) {
  const Icon = toolIcons[tool.name as keyof typeof toolIcons] || Terminal
  const failed = tool.status === 'error'
  const finished = tool.status === 'finished' || tool.preview !== undefined
  const running = !finished && !failed && streaming
  const label = failed ? '执行失败' : finished ? '已返回' : waiting ? '等待确认' : running ? '执行中' : '未完成'
  const context = String(tool.args.path || tool.args.command || tool.args.pattern || tool.args.query || '')
  return <details className={cn('tool-card', failed && 'tool-failed')} data-status={failed ? 'error' : finished ? 'finished' : running ? 'running' : 'pending'}><summary><span className="tool-icon"><Icon size={15} /></span><span className="tool-name">{toolLabels[tool.name] || tool.name}</span><span className="tool-path" title={context}>{context}</span><span className="tool-state">{failed ? <CircleAlert size={13} /> : finished ? <Check size={13} /> : running ? <LoaderCircle size={13} className="agent-spinner" /> : <Clock3 size={13} />}{label}</span><ChevronDown size={14} className="details-chevron" /></summary><div className="tool-detail"><p className="detail-label">调用参数</p><pre>{JSON.stringify(tool.args, null, 2)}</pre>{failed ? <p className="tool-error" role="status">{tool.error || '工具执行失败，请检查后重试。'}</p> : tool.preview !== undefined && <><p className="detail-label result-label">执行结果预览</p><pre>{tool.preview || '工具执行完成，没有文本输出。'}</pre></>}</div></details>
}

const MessageView = memo(function MessageView({ message, streaming, busy, onApprove }: { message: Message; streaming: boolean; busy: boolean; onApprove: (approved: boolean) => void }) {
  if (message.role === 'user') return <article className="user-message"><span className="sr-only">你：</span><p>{message.content}</p></article>
  const tools = message.tools || []
  const completed = tools.filter(tool => tool.preview !== undefined || tool.status === 'finished').length
  const failed = tools.filter(tool => tool.status === 'error').length
  const waiting = Boolean(message.approval && !message.decision)
  const runningTool = tools.findLast(tool => tool.preview === undefined && tool.status !== 'finished' && tool.status !== 'error')
  return <article className="assistant-message" aria-busy={streaming}>
    <h2 className="assistant-label"><span className="assistant-icon"><Code2 size={16} /></span><span>Codelin</span>{streaming && <span className="assistant-state"><span className="activity-dot" />{runningTool ? `正在${toolLabels[runningTool.name] || '执行工具'}` : '正在生成回复'}</span>}</h2>
    {tools.length > 0 && <div className="tool-activity"><div className="tool-activity-heading"><span>执行记录</span><span className="tabular-nums">{completed} / {tools.length} 已完成{failed > 0 && ` · ${failed} 失败`}</span></div><div className="tool-list">{tools.map(tool => <ToolCard key={tool.id} tool={tool} streaming={streaming} waiting={waiting} />)}</div></div>}
    {message.content && <MessageMarkdown content={message.content} />}
    {!message.content && !message.approval && streaming && <p className="preparing-reply" role="status"><LoaderCircle size={15} className="agent-spinner" />{runningTool ? '正在处理项目，完成后继续回复…' : '正在准备回复…'}</p>}
    {message.approval && <section className={cn('approval-card', message.decision && 'approval-resolved')} aria-label="命令审批">
      <div className="approval-heading"><span className="approval-icon"><ShieldCheck size={20} /></span><div><span className="approval-eyebrow">{message.decision ? '操作确认' : '等待你的确认'}</span><h3>{message.decision ? (message.decision === 'approved' ? '已批准执行' : '已拒绝执行') : '这一步，需要你确认。'}</h3></div></div>
      <p className="approval-reason">{message.approval.reason}</p>
      {message.approval.tools?.map((tool, index) => <div key={index} className="approval-operation"><span><Terminal size={13} />{toolLabels[tool.name] || tool.name}</span><pre className="approval-command">{(tool.commands || []).join('\n')}</pre></div>)}
      {!message.decision && <div className="approval-actions"><Button variant="primary" disabled={busy} onClick={() => onApprove(true)}><Check size={15} />批准执行</Button><Button disabled={busy} onClick={() => onApprove(false)}><X size={15} />拒绝执行</Button></div>}
    </section>}
    {message.notice && <p role="status" className="message-notice"><CircleAlert size={15} />{message.notice}</p>}
    {!streaming && message.content && <div className="message-footer"><CopyButton content={message.content} label="复制回复" />{message.elapsed_ms !== undefined && <span className="elapsed-time"><Clock3 size={12} />用时 {(message.elapsed_ms / 1000).toFixed(1)} 秒</span>}</div>}
  </article>
})
export default MessageView
