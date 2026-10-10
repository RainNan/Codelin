import { useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'

export default function SessionTitle({ title, pending }: { title: string; pending: boolean }) {
  const root = useRef<HTMLSpanElement>(null)
  const [visible, setVisible] = useState(false)
  const [pageVisible, setPageVisible] = useState(!document.hidden)

  useEffect(() => {
    if (!pending || !root.current) return
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting))
    observer.observe(root.current)
    const onVisibility = () => setPageVisible(!document.hidden)
    onVisibility()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [pending])

  return <span ref={root} className="session-title" aria-busy={pending}>
    <span className="truncate">{title}</span>
    {pending && <span role="status" aria-label="正在生成会话标题" className="session-title-loading" title="正在生成标题">
      <LoaderCircle size={14} aria-hidden="true" className="animate-spin" style={{ animationPlayState: visible && pageVisible ? 'running' : 'paused' }} />
      <span className="sr-only">正在生成会话标题</span>
    </span>}
  </span>
}
