import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { randomUUID } from 'node:crypto'
import { mkdir } from 'node:fs/promises'

test('real API: file roundtrip, isolation, conflicts and light/dark/mobile previews', async ({ page, request }) => {
  test.skip(!process.env.CODELIN_LIVE, 'Set CODELIN_LIVE=1 with the backend running to run real API acceptance.')
  test.setTimeout(90000)
  const origin = process.env.CODELIN_BACKEND || 'http://127.0.0.1:8000'
  const suffix = randomUUID().replaceAll('-', '').slice(0, 12)
  const username = `verify_${suffix}`
  const registration = await request.post(`${origin}/api/auth/register`, { data: { username, password: randomUUID() } })
  expect(registration.status()).toBe(200)
  const identity = await registration.json()
  const headers = { Authorization: `Bearer ${identity.token}` }
  const created = await request.post(`${origin}/api/workspaces`, { headers, data: { name: '文件功能验收' } })
  expect(created.status()).toBe(201)
  const workspace = await created.json(), prefix = `${origin}/api/workspaces/${workspace.id}`
  const createEntry = async (path: string, type: string, content = '') => {
    expect((await request.post(`${prefix}/entries`, { headers, data: { path, type, content } })).status()).toBe(201)
  }
  await createEntry('src', 'directory')
  await createEntry('src/main.ts', 'file', '// 通过真实文件接口创建的验收文件\nexport function greet(name: string) {\n  return `你好，${name}`;\n}\n')
  await createEntry('README.md', 'file', '# 文件功能验收\n\n此工作区由联调测试通过真实接口创建。\n')
  await createEntry('binary.png', 'file')
  const session = await request.post(`${origin}/api/sessions`, { headers, data: { workspace_id: workspace.id } })
  expect(session.status()).toBe(200)
  await page.addInitScript(value => sessionStorage.setItem('codelin.auth', JSON.stringify(value)), { ...identity, username })
  await page.setViewportSize({ width: 1680, height: 1000 }); await page.goto('/')
  await page.getByRole('button', { name: '工作空间文件', exact: true }).click()
  await page.getByRole('button', { name: '文件夹：src', exact: true }).dblclick()
  await page.getByRole('button', { name: '文件：main.ts', exact: true }).dblclick()
  const editor = page.getByRole('textbox', { name: '编辑文件：src/main.ts' })
  await expect(editor).toBeVisible()
  await editor.focus(); await page.keyboard.press('ControlOrMeta+End'); await page.keyboard.insertText('\n// 编辑器保存验收\n'); await page.keyboard.press('ControlOrMeta+S')
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  const raw = await request.get(`${prefix}/file?path=src/main.ts`, { headers })
  const first = await raw.json()
  expect(first.content).toContain('// 编辑器保存验收')
  const updated = await request.put(`${prefix}/file`, { headers, data: { path: 'src/main.ts', content: first.content + '// 外部更新验收\n', version: first.version } })
  expect(updated.status()).toBe(200)
  await editor.focus(); await page.keyboard.press('ControlOrMeta+End'); await page.keyboard.insertText('// 本地草稿\n'); await page.keyboard.press('ControlOrMeta+S')
  await expect(page.getByText('文件已在外部更新，你的修改已保留。')).toBeVisible()
  await page.getByRole('button', { name: '重新载入', exact: true }).click()
  await expect(page.locator('.monaco-editor .view-lines')).toContainText('外部更新验收')
  for (const path of ['../outside', 'C:/Windows/win.ini', '/etc/passwd']) expect((await request.get(`${prefix}/file`, { headers, params: { path } })).status()).toBe(403)
  const other = await request.post(`${origin}/api/auth/register`, { data: { username: `other_${suffix}`, password: randomUUID() } })
  const otherIdentity = await other.json()
  const otherHeaders = { Authorization: `Bearer ${otherIdentity.token}` }
  for (const endpoint of ['', '/files', '/file?path=src/main.ts']) expect((await request.get(prefix + endpoint, { headers: otherHeaders })).status()).toBe(404)
  const axe = await new AxeBuilder({ page }).analyze()
  // Monaco's editor implementation is upstream; the application controls must pass.
  expect(axe.violations).toEqual([])
  await mkdir('preview', { recursive: true })
  await page.screenshot({ path: 'preview/workspace-files-light.png', fullPage: true })
  await page.getByRole('button', { name: '切换到深色模式' }).click()
  await page.screenshot({ path: 'preview/workspace-files-dark.png', fullPage: true })
  await page.getByRole('button', { name: '切换到浅色模式' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '工作空间文件', exact: true }).click()
  await page.getByRole('button', { name: '打开文件：main.ts', exact: true }).click()
  await expect(editor).toBeVisible()
  await expect(page.getByLabel('给 Codelin 发送消息')).not.toBeVisible()
  expect((await page.locator('.monaco-region').boundingBox())!.height).toBeGreaterThan(300)
  await page.screenshot({ path: 'preview/workspace-files-mobile.png', fullPage: true })
  await page.getByRole('button', { name: '返回文件', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
