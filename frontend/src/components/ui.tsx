import { useLayoutEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Code2, X } from 'lucide-react'
import * as Dialog from '@radix-ui/react-dialog'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { cn } from '../lib/utils'

function useRestoreFocus(open: boolean) {
  const trigger = useRef<HTMLElement | null>(null)
  useLayoutEffect(() => {
    if (open && document.activeElement instanceof HTMLElement) trigger.current = document.activeElement
  }, [open])
  return (event: Event) => {
    event.preventDefault()
    if (trigger.current?.isConnected) trigger.current.focus()
    else document.getElementById('composer')?.focus()
  }
}

export function Brand({ small = false }: { small?: boolean }) {
  return <span className={cn('brand', small && 'brand-small')}><span className="brand-mark"><Code2 aria-hidden="true" /></span><span>Codelin<span className="brand-dot">.</span></span></span>
}

export function Button({ className, variant = 'secondary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button type="button" className={cn('button', `button-${variant}`, className)} {...props} />
}

export function Modal({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; children: ReactNode }) {
  const restoreFocus = useRestoreFocus(open)
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="modal-overlay" />
    <Dialog.Content className="modal-content" onCloseAutoFocus={restoreFocus}>
      <Dialog.Title className="text-xl font-semibold text-balance">{title}</Dialog.Title>
      <Dialog.Description className="mt-2 text-sm text-pretty text-muted">{description}</Dialog.Description>
      <Dialog.Close asChild><Button variant="ghost" className="modal-close icon-button" aria-label="关闭对话框"><X size={18} /></Button></Dialog.Close>
      {children}
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>
}

export function DeleteDialog({ title, open, onOpenChange, onDelete, busy, error }: { title: string; open: boolean; onOpenChange: (open: boolean) => void; onDelete: () => void; busy: boolean; error: string }) {
  const restoreFocus = useRestoreFocus(open)
  return <AlertDialog.Root open={open} onOpenChange={value => { if (!busy) onOpenChange(value) }}><AlertDialog.Portal>
    <AlertDialog.Overlay className="modal-overlay" />
    <AlertDialog.Content className="modal-content" onCloseAutoFocus={restoreFocus}>
      <AlertDialog.Title className="text-xl font-semibold text-balance">删除这个会话？</AlertDialog.Title>
      <AlertDialog.Description className="mt-3 text-sm text-muted text-pretty">“{title}”将从会话列表中删除。此操作无法撤销。</AlertDialog.Description>
      {error && <p role="alert" className="inline-error mt-4">{error}</p>}
      <div className="mt-6 flex justify-end gap-3">
        <AlertDialog.Cancel asChild><Button disabled={busy}>保留会话</Button></AlertDialog.Cancel>
        <Button variant="danger" disabled={busy} onClick={onDelete}>{busy ? '正在删除…' : '删除会话'}</Button>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal></AlertDialog.Root>
}
