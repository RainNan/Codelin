import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { FileContent } from './types'
import { errorText } from './utils'

export interface OpenFile extends FileContent {
  wid: string; base: string; draft: string; saving?: boolean; error?: string
  external?: FileContent; comparing?: boolean; saved?: boolean
}
const keyFor = (wid: string, path: string) => `${wid}/${path}`

export function useWorkspaceFiles(token: string | undefined, wid: string | undefined, onAuthError: () => void) {
  const [files, setFiles] = useState<OpenFile[]>([])
  const [activePaths, setActivePaths] = useState<Record<string, string>>({})
  const [opening, setOpening] = useState('')
  const [openError, setOpenError] = useState('')
  const [revision, setRevision] = useState(0)
  const filesRef = useRef(files); filesRef.current = files
  const workspaceRef = useRef(wid); workspaceRef.current = wid
  const pathsRef = useRef(activePaths); pathsRef.current = activePaths
  const epoch = useRef(0)
  const openingRequests = useRef(new Set<string>())
  const syncRequests = useRef(new Map<string, number>())
  const saveRequests = useRef(new Set<string>())
  const deferredChecks = useRef(new Set<string>())
  useEffect(() => {
    epoch.current++; setFiles([]); setActivePaths({}); setOpenError(''); setOpening('')
    openingRequests.current.clear(); saveRequests.current.clear(); syncRequests.current.clear(); deferredChecks.current.clear()
  }, [token])
  useEffect(() => { setOpenError(''); setOpening('') }, [wid])
  const patch = useCallback((workspace: string, path: string, update: (file: OpenFile) => OpenFile) => {
    setFiles(prev => prev.map(file => file.wid === workspace && file.path === path ? update(file) : file))
  }, [])
  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onAuthError()
    return errorText(error)
  }, [onAuthError])

  async function open(path: string) {
    if (!wid || !token) return
    const workspace = wid, stamp = epoch.current, key = keyFor(workspace, path)
    setActivePaths(prev => ({ ...prev, [workspace]: path })); setOpenError('')
    if (filesRef.current.some(file => file.wid === workspace && file.path === path)) return
    if (openingRequests.current.has(key)) return
    openingRequests.current.add(key); setOpening(path)
    try {
      const file = await api.file(token, workspace, path)
      if (epoch.current !== stamp) return
      setFiles(prev => prev.some(item => item.wid === workspace && item.path === file.path) ? prev : [...prev, { ...file, wid: workspace, base: file.content, draft: file.content }])
      setActivePaths(prev => prev[workspace] === path ? { ...prev, [workspace]: file.path } : prev)
    } catch (e) { if (epoch.current === stamp && workspaceRef.current === workspace && pathsRef.current[workspace] === path) setOpenError(fail(e)) }
    finally { if (epoch.current === stamp) { openingRequests.current.delete(key); if (workspaceRef.current === workspace) setOpening(current => current === path ? '' : current) } }
  }

  const check = useCallback(async (workspace: string, path: string) => {
    if (!token) return
    const snapshot = filesRef.current.find(file => file.wid === workspace && file.path === path)
    const stamp = epoch.current, key = keyFor(workspace, path)
    if (!snapshot) return
    if (snapshot.saving || saveRequests.current.has(key)) { deferredChecks.current.add(key); return }
    const sequence = (syncRequests.current.get(key) || 0) + 1
    syncRequests.current.set(key, sequence)
    try {
      const latest = await api.file(token, workspace, path)
      if (epoch.current !== stamp || syncRequests.current.get(key) !== sequence) return
      patch(workspace, path, current => {
        if (current.version !== snapshot.version || current.saving) return current
        if (latest.version === current.version) return { ...current, external: undefined, error: undefined }
        if (current.draft !== current.base) return { ...current, external: latest, saved: false, error: undefined }
        return { ...current, ...latest, base: latest.content, draft: latest.content, external: undefined, error: undefined, saved: false }
      })
    } catch (e) { if (epoch.current === stamp) patch(workspace, path, current => ({ ...current, error: fail(e) })) }
  }, [token, patch, fail])
  useEffect(() => {
    for (const file of files) {
      const key = keyFor(file.wid, file.path)
      if (!file.saving && !saveRequests.current.has(key) && deferredChecks.current.delete(key)) void check(file.wid, file.path)
    }
  }, [files, check])

  const refresh = useCallback((workspace: string, path?: string) => {
    setRevision(value => value + 1)
    filesRef.current.filter(file => file.wid === workspace && (!path || file.path === path)).forEach(file => { void check(workspace, file.path) })
  }, [check])

  async function save(file: OpenFile): Promise<boolean> {
    const key = keyFor(file.wid, file.path)
    if (!token || file.external || saveRequests.current.has(key)) return false
    if (file.base === file.draft) return true
    saveRequests.current.add(key)
    const stamp = epoch.current, submitted = file.draft
    patch(file.wid, file.path, current => ({ ...current, saving: true, error: undefined, saved: false }))
    try {
      const result = await api.saveFile(token, file.wid, file.path, submitted, file.version)
      if (epoch.current !== stamp) return false
      patch(file.wid, file.path, current => ({ ...current, ...result, base: submitted, content: submitted, saving: false, saved: current.draft === submitted, external: undefined }))
      setRevision(value => value + 1)
      return filesRef.current.find(item => keyFor(item.wid, item.path) === key)?.draft === submitted
    } catch (e) {
      if (epoch.current !== stamp) return false
      patch(file.wid, file.path, current => ({ ...current, saving: false, error: fail(e) }))
      if (e instanceof ApiError && e.status === 409) {
        // The current draft survives even if fetching the conflicting version fails.
        try {
          const latest = await api.file(token, file.wid, file.path)
          if (epoch.current === stamp) patch(file.wid, file.path, current => ({ ...current, external: latest }))
        } catch { /* Keep the save error and allow a manual retry. */ }
      }
      return false
    } finally { if (epoch.current === stamp) saveRequests.current.delete(key) }
  }
  function close(file: OpenFile) {
    setFiles(prev => prev.filter(item => keyFor(item.wid, item.path) !== keyFor(file.wid, file.path)))
    setActivePaths(prev => {
      if (prev[file.wid] !== file.path) return prev
      const remaining = filesRef.current.filter(item => item.wid === file.wid && item.path !== file.path)
      return { ...prev, [file.wid]: remaining.at(-1)?.path || '' }
    })
  }
  function resolve(file: OpenFile, reload: boolean) {
    patch(file.wid, file.path, current => current.external ? {
      ...current, ...current.external, base: current.external.content,
      draft: reload ? current.external.content : current.draft,
      external: undefined, comparing: false, error: undefined, saved: false,
    } : current)
  }
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (filesRef.current.some(file => file.draft !== file.base)) event.preventDefault()
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])
  const tabs = files.filter(file => file.wid === wid)
  const active = tabs.find(file => file.path === (wid ? activePaths[wid] : '')) || tabs.at(-1)
  return { tabs, active, files, opening, openError, revision, open, save, close, resolve, patch, refresh, check,
    activate: (path: string) => wid && setActivePaths(prev => ({ ...prev, [wid]: path })), retryOpen: () => wid && activePaths[wid] && open(activePaths[wid]) }
}
export type WorkspaceFiles = ReturnType<typeof useWorkspaceFiles>
