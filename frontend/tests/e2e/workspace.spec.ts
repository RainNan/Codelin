import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdir } from 'node:fs/promises'

async function demo(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '体验演示' }).click()
}

async function mockBackend(page: Page, chat: 'done' | 'approval' | 'broken' | 'title' = 'done') {
  const calls: { path: string; method: string; body: unknown; authorization: string | undefined }[] = []
  let removed = false
  let titleReads = 0
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    calls.push({ path, method, body: request.postDataJSON(), authorization: request.headers().authorization })
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (path.startsWith('/api/auth/')) return json({ token: 'test-token', username: 'tester' })
    if (path === '/api/sessions' && method === 'GET') return json(removed ? [] : [{ id: 'existing', title: '已有项目讨论', created_at: '2026-10-09T00:00:00Z' }])
    if (path === '/api/sessions' && method === 'POST') return json({ id: 'new-session', title: '新会话' })
    if (path === '/api/sessions/new-session' && method === 'GET') return json({ id: 'new-session', title: ++titleReads > 1 ? '实现登录功能' : '新会话' })
    if (path === '/api/sessions/existing/messages') return json([{ role: 'user', content: '历史问题' }, { role: 'assistant', content: '历史回复' }])
    if (method === 'DELETE') { removed = true; return json({ ok: true }) }
    if (path === '/api/chat' || path === '/api/chat/approve') {
      const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
      const body = path.endsWith('/approve') ? sse('token', { content: '审批后继续完成。' }) + sse('done', { elapsed_ms: 45 }) :
        (chat === 'title' ? sse('session_title_pending', { session_id: 'new-session', title: '新会话' }) : '') +
        sse('tool_start', { id: 'tool-1', name: 'read_file', args: { path: 'main.py' } }) +
        sse('tool_result', { id: 'tool-1', name: 'read_file', preview: 'print("你好")' }) +
        sse('token', { content: '你好，这是来自接口的回复。' }) +
        (chat === 'done' || chat === 'title' ? sse('done', { elapsed_ms: 120 }) : chat === 'approval' ? sse('approval_required', { thread_id: 'new-session', reason: '命令需要审批', tools: [{ name: 'run_command', commands: ['npm install'] }] }) : '')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
    }
    return json({ detail: 'Not found' }, 404)
  })
  await page.goto('/')
  await page.getByLabel('用户名', { exact: true }).fill('tester')
  await page.getByLabel('密码', { exact: true }).fill('password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: /^已有项目讨论/ })).toBeVisible()
  return calls
}

test('demo has an explicit label, working suggestions and approval choices', async ({ page }) => {
  await demo(page)
  await expect(page.getByText('演示模式', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /读懂项目/ }).click()
  await expect(page.getByLabel('给 Codelin 发送消息')).toHaveValue(/项目结构/)
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('button', { name: '批准执行' })).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).toBeDisabled()
  await page.getByRole('button', { name: '拒绝执行' }).click()
  await expect(page.getByText('已拒绝执行', { exact: true })).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).toBeEnabled()
})

test('login, persisted history, chat stream and tool results follow the backend contract', async ({ page }) => {
  const calls = await mockBackend(page)
  await page.getByRole('button', { name: /^已有项目讨论/ }).click()
  await expect(page.getByText('历史回复', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新建会话' }).click()
  await page.getByLabel('给 Codelin 发送消息').fill('检查一下代码')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('你好，这是来自接口的回复。', { exact: true })).toBeVisible()
  await expect(page.getByText('已返回', { exact: true })).toBeVisible()
  await page.getByText('阅读文件', { exact: true }).click()
  await expect(page.getByText('print("你好")', { exact: true })).toBeVisible()
  expect(calls.find(call => call.path === '/api/chat')?.body).toEqual({ session_id: 'new-session', message: '检查一下代码' })
  expect(calls.filter(call => !call.path.includes('/auth/')).every(call => call.authorization === 'Bearer test-token')).toBe(true)
  await page.reload()
  await expect(page.getByRole('button', { name: /^已有项目讨论/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '欢迎回来。' })).not.toBeVisible()
})

test('an asynchronous title updates the sidebar and preserves the reply and draft', async ({ page }) => {
  const calls = await mockBackend(page, 'title')
  await page.getByLabel('给 Codelin 发送消息').fill('帮我实现登录功能')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('你好，这是来自接口的回复。', { exact: true })).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).toBeEnabled()
  await page.getByLabel('给 Codelin 发送消息').fill('下一条消息的草稿')
  await expect(page.getByRole('button', { name: /^实现登录功能/ })).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).toHaveValue('下一条消息的草稿')
  expect(calls.filter(call => call.path === '/api/sessions/new-session').length).toBe(2)
})

test('real approval posts the boolean and resumes the same session', async ({ page }) => {
  const calls = await mockBackend(page, 'approval')
  await page.getByLabel('给 Codelin 发送消息').fill('安装依赖')
  await page.getByRole('button', { name: '发送消息' }).click()
  await page.getByRole('button', { name: '批准执行' }).click()
  await expect(page.getByText(/审批后继续完成/)).toBeVisible()
  expect(calls.find(call => call.path === '/api/chat/approve')?.body).toEqual({ session_id: 'new-session', approved: true })
})

test('an incomplete stream keeps the partial reply and shows a recoverable error', async ({ page }) => {
  await mockBackend(page, 'broken')
  await page.getByLabel('给 Codelin 发送消息').fill('检查代码')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('alert')).toContainText('连接提前结束')
  await expect(page.getByText('你好，这是来自接口的回复。', { exact: true })).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).toBeEnabled()
})

test('deletion requires confirmation and sends DELETE only on confirmation', async ({ page }) => {
  const calls = await mockBackend(page)
  await page.getByRole('button', { name: '删除会话：已有项目讨论' }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
  expect(calls.some(call => call.method === 'DELETE')).toBe(false)
  await page.getByRole('button', { name: '保留会话' }).click()
  await expect(page.getByRole('button', { name: '删除会话：已有项目讨论' })).toBeFocused()
  await page.getByRole('button', { name: '删除会话：已有项目讨论' }).click()
  await page.getByRole('button', { name: '删除会话', exact: true }).click()
  await expect(page.getByRole('alertdialog')).not.toBeVisible()
  await expect(page.getByRole('button', { name: /^已有项目讨论/ })).not.toBeVisible()
  expect(calls.filter(call => call.method === 'DELETE').map(call => call.path)).toEqual(['/api/sessions/existing'])
})

test('registration uses the username API and displays backend errors beside the form', async ({ page }) => {
  await page.route('**/api/auth/register', route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '用户名已存在' }) }))
  await page.goto('/')
  await page.getByRole('button', { name: '立即注册' }).click()
  await page.getByLabel('用户名', { exact: true }).fill('existing-user')
  await page.getByLabel('密码', { exact: true }).fill('password')
  await page.getByRole('button', { name: '创建账户', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('用户名已存在')
})

test('expired credentials return to login and clear the session token', async ({ page }) => {
  await mockBackend(page)
  await page.route('**/api/chat', route => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: '无效凭证' }) }))
  await page.getByLabel('给 Codelin 发送消息').fill('你好')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来。' })).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('codelin.auth'))).toBeNull()
})

test('desktop, dark theme and mobile views pass automated accessibility and fit the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/')
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await mkdir('preview', { recursive: true })
  await page.screenshot({ path: 'preview/login.png', fullPage: true })
  await page.getByRole('button', { name: '体验演示' }).click()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: 'preview/workspace.png', fullPage: true })
  await page.getByRole('button', { name: '切换到深色模式' }).click()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: 'preview/dark.png', fullPage: true })
  await page.getByRole('button', { name: '切换到浅色模式' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: '打开会话导航' })).toBeVisible()
  await page.getByRole('button', { name: '打开会话导航' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(page.getByRole('button', { name: '打开会话导航' })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'preview/mobile.png', fullPage: true })
})
