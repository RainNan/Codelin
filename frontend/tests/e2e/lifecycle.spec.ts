import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function fixture(page: Page, emitCreation = true) {
  let sequence = 0, failDelete = false
  const workspaces = [{ id: 'w1', name: '项目甲', created_at: '', deleting: false }, { id: 'w2', name: '空项目', created_at: '', deleting: false }]
  const sessions = [{ id: 'outside', title: '独立讨论', workspace_id: null as string | null }, { id: 'inside', title: '项目讨论', workspace_id: 'w1' as string | null }]
  const calls: { path: string; method: string; body: any }[] = []
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method(), body = req.postDataJSON()
    calls.push({ path, method, body })
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
    if (path.startsWith('/api/auth/')) return json({ token: 'management-token', username: 'tester' })
    if (path === '/api/workspaces') {
      if (method === 'GET') return json(workspaces)
      const workspace = { id: `w-new-${++sequence}`, name: body.name, created_at: '', deleting: false }
      workspaces.push(workspace); return json(workspace, 201)
    }
    if (path === '/api/sessions') {
      if (method === 'GET') return json(sessions)
      const session = { id: `s-new-${++sequence}`, title: '新会话', workspace_id: body?.workspace_id || null }
      sessions.push(session); return json(session)
    }
    const sessionId = path.match(/^\/api\/sessions\/([^/]+)$/)?.[1]
    if (sessionId) {
      const session = sessions.find(item => item.id === sessionId)
      if (!session) return json({ detail: '对话不存在' }, 404)
      if (method === 'PATCH') Object.assign(session, body)
      if (method === 'DELETE') { sessions.splice(sessions.indexOf(session), 1); return json({ ok: true }) }
      return json(session)
    }
    if (path.endsWith('/messages')) return json([{ role: 'user', content: '以前的消息' }, { role: 'assistant', content: '以前的回复' }])
    const wid = path.match(/^\/api\/workspaces\/([^/]+)$/)?.[1]
    if (wid) {
      const workspace = workspaces.find(item => item.id === wid)
      if (!workspace) return json({ detail: '工作区不存在' }, 404)
      if (method === 'PATCH') workspace.name = body.name
      if (method === 'DELETE') {
        if (failDelete) { workspace.deleting = true; return json({ detail: '工作区清理未完成，请重试删除' }, 500) }
        workspaces.splice(workspaces.indexOf(workspace), 1)
        for (let i = sessions.length - 1; i >= 0; i--) if (sessions[i].workspace_id === wid) sessions.splice(i, 1)
        return json({ ok: true })
      }
      return json(workspace)
    }
    if (path.endsWith('/files')) return json({ path: '.', entries: [], total: 0, next_offset: null })
    if (path === '/api/chat') {
      const session = sessions.find(item => item.id === body.session_id)!
      const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
      let stream = ''
      if (body.message === 'build' && !session.workspace_id) {
        const workspace = { id: 'auto-workspace', name: '新工作区', created_at: '', deleting: false }
        workspaces.push(workspace); session.workspace_id = workspace.id
        if (emitCreation) stream += sse('workspace_created', { session_id: session.id, workspace })
        stream += sse('tool_start', { id: 'write-1', name: 'write_file', args: { path: 'main.py' } })
        stream += sse('tool_result', { id: 'write-1', name: 'write_file', preview: '已写入' })
      }
      return route.fulfill({ contentType: 'text/event-stream', body: stream + sse('token', { content: '本次回复' }) + sse('done', { elapsed_ms: 1 }) })
    }
    return json({ detail: 'Not found' }, 404)
  })
  await page.goto('/')
  await page.getByLabel('用户名', { exact: true }).fill('tester')
  await page.getByLabel('密码', { exact: true }).fill('password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.workspace-header')).toContainText('独立讨论')
  return { calls, workspaces, sessions, failDelete: (value: boolean) => { failDelete = value } }
}

test('create, rename, join and grouped navigation preserve the one-way association', async ({ page }) => {
  const state = await fixture(page)
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  expect(state.calls.filter(call => call.path === '/api/sessions' && call.method === 'POST').at(-1)?.body).toEqual({})
  await expect(page.locator('.membership-bar')).toContainText('独立对话')
  await page.getByRole('button', { name: '重命名会话：新会话' }).click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('新讨论')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('button', { name: '加入工作区：新讨论' }).click()
  await page.getByLabel('目标工作区').selectOption('w1')
  await page.getByRole('button', { name: '确认加入' }).click()
  await expect(page.getByRole('region', { name: '项目甲', exact: true }).getByRole('button', { name: /^新讨论/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '加入工作区：新讨论' })).toHaveCount(0)
  await expect(page.locator('.membership-bar')).toContainText('对话工作区：项目甲')
  await page.getByRole('button', { name: '在工作区新建会话：项目甲' }).click()
  expect(state.calls.filter(call => call.path === '/api/sessions' && call.method === 'POST').at(-1)?.body).toEqual({ workspace_id: 'w1' })
  await page.getByRole('button', { name: '重命名工作区：项目甲' }).click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('重命名项目')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('region', { name: '重命名项目', exact: true })).toBeVisible()
  const createdCount = state.sessions.length
  await page.getByRole('button', { name: '新建工作区', exact: true }).click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('新空工作区')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.membership-bar')).toContainText('新空工作区 · 尚未选择对话')
  expect(state.sessions).toHaveLength(createdCount)
  await page.reload()
  await expect(page.getByRole('region', { name: '重命名项目', exact: true }).getByRole('button', { name: /^新讨论/ })).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
})

test('a retried title updates a workspace conversation without losing its reply or draft', async ({ page }) => {
  const state = await fixture(page)
  const session = state.sessions.find(item => item.id === 'inside')!
  session.title = '新会话'
  await page.reload()
  await page.getByRole('region', { name: '项目甲', exact: true }).getByRole('button', { name: /^新会话/ }).click()
  let release!: () => void
  const ready = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/sessions/inside', async route => {
    await ready
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(session) })
  })
  await page.route('**/api/chat', route => route.fulfill({ contentType: 'text/event-stream', body:
    'event: session_title_pending\ndata: {"session_id":"inside","title":"新会话"}\n\n' +
    'event: token\ndata: {"content":"继续开发游戏"}\n\n' +
    'event: done\ndata: {}\n\n' }))
  await page.getByLabel('给 Codelin 发送消息').fill('继续开发')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('继续开发游戏', { exact: true })).toBeVisible()
  await expect(page.getByRole('status', { name: '正在生成会话标题', exact: true })).toHaveCount(2)
  await page.getByLabel('给 Codelin 发送消息').fill('下一步的草稿')
  session.title = 'Python 飞机大战'
  release()
  await expect(page.getByRole('region', { name: '项目甲', exact: true }).getByRole('button', { name: /^Python 飞机大战/ })).toBeVisible()
  await expect(page.locator('.workspace-header')).toContainText('Python 飞机大战')
  await expect(page.locator('.membership-bar')).toContainText('对话工作区：项目甲')
  await expect(page.getByLabel('给 Codelin 发送消息')).toHaveValue('下一步的草稿')
  await expect(page.getByText('以前的回复', { exact: true })).toBeVisible()
})

for (const emitCreation of [true, false]) {
  test(`automatic association preserves session and history, creation event ${emitCreation ? 'received' : 'missed'}`, async ({ page }) => {
    const state = await fixture(page, emitCreation)
    await page.getByLabel('给 Codelin 发送消息').fill('plain question')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect(page.getByText('本次回复', { exact: true })).toBeVisible()
    expect(state.workspaces).toHaveLength(2)
    await expect(page.getByLabel('给 Codelin 发送消息')).toBeEnabled()
    await page.getByLabel('给 Codelin 发送消息').fill('build')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect(page.getByRole('region', { name: '新工作区', exact: true }).getByRole('button', { name: /^独立讨论/ })).toBeVisible()
    await expect(page.locator('.membership-bar')).toContainText('对话工作区：新工作区')
    await expect(page.getByText('以前的回复', { exact: true })).toBeVisible()
    expect(state.calls.filter(call => call.path === '/api/chat').every(call => call.body.session_id === 'outside')).toBe(true)
    expect(state.sessions.find(item => item.id === 'outside')?.workspace_id).toBe('auto-workspace')
    await page.reload()
    await expect(page.getByRole('region', { name: '新工作区', exact: true }).getByRole('button', { name: /^独立讨论/ })).toBeVisible()
    expect(state.workspaces).toHaveLength(3)
  })
}

test('workspace deletion shows consequences, preserves state on failure and supports retry', async ({ page }) => {
  const state = await fixture(page)
  await page.getByRole('button', { name: '项目甲', exact: true }).click()
  await page.getByRole('button', { name: '删除工作区：项目甲' }).click()
  await expect(page.getByRole('alertdialog')).toContainText('1 个对话、所有项目文件和未保存的文件草稿')
  expect(state.calls.filter(call => call.path === '/api/workspaces/w1' && call.method === 'DELETE')).toHaveLength(0)
  state.failDelete(true)
  await page.getByRole('button', { name: '删除工作区及其内容' }).click()
  await expect(page.getByRole('alertdialog').getByRole('alert')).toContainText('重试删除')
  expect(state.sessions.some(item => item.id === 'inside')).toBe(true)
  state.failDelete(false)
  await page.getByRole('button', { name: '删除工作区及其内容' }).click()
  await expect(page.getByRole('region', { name: '项目甲', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^项目讨论/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^独立讨论/ })).toBeVisible()
  await expect(page.getByRole('region', { name: '空项目', exact: true })).toBeVisible()
  expect(state.sessions.some(item => item.id === 'inside')).toBe(false)
})

test('mobile grouped navigation creates a workspace chat and fits the screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await fixture(page)
  await page.getByRole('button', { name: '打开会话导航' }).click()
  await page.getByRole('button', { name: '在工作区新建会话：项目甲' }).click()
  await expect(page.locator('.membership-bar')).toContainText('项目甲')
  expect(state.calls.filter(call => call.path === '/api/sessions' && call.method === 'POST').at(-1)?.body).toEqual({ workspace_id: 'w1' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
})
