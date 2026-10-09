import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
export const cn = (...values: ClassValue[]) => twMerge(clsx(values))
export const id = () => crypto.randomUUID()
export function readIdentity() {
  try {
    const value = JSON.parse(sessionStorage.getItem('codelin.auth') || 'null')
    return value && typeof value.token === 'string' && typeof value.username === 'string' ? value : null
  } catch { return null }
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请重试。'
}
export function dateLabel(value?: string) {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
