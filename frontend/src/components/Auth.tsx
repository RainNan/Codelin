import { useState, type FormEvent } from 'react'
import { ArrowRight, Braces, Check, Eye, EyeOff, ShieldCheck, Terminal } from 'lucide-react'
import { api } from '../lib/api'
import type { Identity } from '../lib/types'
import { errorText } from '../lib/utils'
import { Brand, Button } from './ui'

export default function Auth({ onAuth, onDemo, notice }: { onAuth: (identity: Identity) => void; onDemo: () => void; notice: string }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (new TextEncoder().encode(password).length > 72) { setError('密码不能超过 72 个字节，请缩短后重试。'); return }
    setBusy(true)
    try { onAuth(await api.auth(mode, username.trim(), password)) }
    catch (e) { setError(errorText(e)) }
    finally { setBusy(false) }
  }
  return <div className="auth-page">
    <header className="auth-header"><Brand /><span className="text-sm text-muted">你的 AI 编程伙伴</span></header>
    <main className="auth-main">
      <section className="auth-story">
        <span className="eyebrow"><span className="size-1.5 rounded-full bg-blue-600" />为专注创造而设计</span>
        <h1 className="auth-headline">清晰的思路。<br /><span className="text-muted">出色的代码。</span></h1>
        <p className="auth-intro">从理解项目到解决问题，Codelin 与你一起，<br className="hidden sm:block" />把下一步想法变成现实。</p>
        <div className="auth-preview" aria-label="Codelin 工作流示意">
          <div className="flex items-center justify-between border-b border-line px-5 py-4"><span className="flex items-center gap-2 text-sm font-medium"><Terminal size={16} />一个更专注的工作空间</span><span className="text-xs text-muted">工作流示意</span></div>
          <div className="space-y-5 p-6">
            <p className="text-sm">帮我理解这个项目，并找到可以改进的地方。</p>
            <div className="flex items-center gap-3 text-sm text-muted"><span className="preview-check"><Check size={13} /></span>阅读项目结构与代码</div>
            <div className="flex items-center gap-3 text-sm text-muted"><span className="preview-check"><Check size={13} /></span>梳理思路，给出可执行的建议</div>
            <div className="flex items-center gap-3 text-sm text-muted"><span className="preview-check"><ShieldCheck size={13} /></span>关键命令，由你确认</div>
          </div>
        </div>
        <div className="auth-benefits"><span><Braces size={16} />理解代码</span><span><Terminal size={16} />协作执行</span><span><ShieldCheck size={16} />掌握主动权</span></div>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card-mark"><Braces size={26} /></div>
        <h2 id="auth-title" className="text-2xl font-semibold text-balance">{mode === 'login' ? '欢迎回来。' : '从这里开始。'}</h2>
        <p className="mt-2 text-sm text-muted text-pretty">{mode === 'login' ? '登录 Codelin，继续你的下一次创造。' : '创建账户，开启你的专属编程工作空间。'}</p>
        <form onSubmit={submit} className="mt-8 space-y-5" aria-busy={busy}>
          <div><label htmlFor="username" className="field-label">用户名</label><input id="username" value={username} onChange={e => setUsername(e.target.value)} className="input" autoComplete="username" required maxLength={64} disabled={busy} placeholder="输入你的用户名" aria-describedby={error ? 'auth-error' : undefined} aria-invalid={Boolean(error)} /></div>
          <div><label htmlFor="password" className="field-label">密码</label><div className="relative"><input id="password" type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} className="input pr-12" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required disabled={busy} placeholder="输入你的密码" aria-describedby={error ? 'auth-error' : undefined} aria-invalid={Boolean(error)} /><Button variant="ghost" className="password-toggle icon-button" aria-label={showPassword ? '隐藏密码' : '显示密码'} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</Button></div></div>
          {(error || notice) && <p id="auth-error" role="alert" className="inline-error">{error || notice}</p>}
          <Button variant="primary" type="submit" className="w-full justify-center" disabled={busy}>{busy ? '正在连接…' : mode === 'login' ? '登录' : '创建账户'}<ArrowRight size={16} /></Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted">{mode === 'login' ? '还没有账户？' : '已经有账户？'} <button className="text-link" disabled={busy} onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>{mode === 'login' ? '立即注册' : '前往登录'}</button></p>
        <div className="auth-demo"><span>先看看它的样子</span><Button variant="ghost" onClick={onDemo} disabled={busy}>体验演示<ArrowRight size={15} /></Button></div>
        <p className="mt-3 text-center text-xs text-muted">演示模式使用示例内容，不连接后端。</p>
      </section>
    </main>
    <footer className="auth-footer"><span>Codelin · 让想法成为代码</span><span>少一些干扰，多一些创造。</span></footer>
  </div>
}
