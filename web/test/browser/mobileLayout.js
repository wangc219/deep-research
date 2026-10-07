// 已登录开发环境：playwright-cli -s=<session> run-code --filename=web/test/browser/mobileLayout.js
// Only navigation, local UI state and screenshots; no creation or backend mutations.
// prettier-ignore
async (page) => {
  const originalViewport = page.viewportSize()
  const origin = new URL(page.url()).origin
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  const routes = [
    ['/knowledge', '.kp-stats'],
    ['/equipment/runs', '.equipment-runs-page'],
    ['/equipment/queries', '.equipment-workbench-frame:not(.is-booting)'],
    ['/equipment/capabilities', '.capability-page'],
    ['/equipment/reports', '.reports-page'],
    ['/equipment/favorites', '.equipment-workbench-frame:not(.is-booting)'],
    ['/equipment/deep-thinking', '.deep-research-shell'],
    ['/agent', '.agent-view'],
    ['/workspace', '.workspace-shell'],
    ['/models', '.model-settings-content'],
    ['/agent-manage', '.agent-manage-content'],
    ['/extensions', '.extensions-content'],
    ['/dashboard', '.dashboard-grid'],
    ['/enterprise', '.enterprise-page']
  ]
  try {
    for (const width of [320, 375, 390, 430, 768, 844, 1440]) {
      await page.setViewportSize({ width, height: width === 844 ? 390 : 900 })
      for (const [path, ready] of routes) {
        await page.goto(origin + path)
        check(!new URL(page.url()).pathname.startsWith('/login'), '请先用可访问管理页面的测试账号登录')
        await page.locator(ready).waitFor({ state: 'visible' })
        await page.evaluate(() => document.fonts.ready)
        const bounds = await page.evaluate(() => {
          const root = document.querySelector('#app-router-view')
          return {
            viewport: innerWidth,
            document: document.documentElement.scrollWidth,
            content: root.scrollWidth,
            available: root.clientWidth
          }
        })
        check(bounds.document <= bounds.viewport + 1, `${path}: 整页溢出 ${width}px`)
        check(bounds.content <= bounds.available + 1, `${path}: 内容区溢出 ${width}px`)
      }
    }

    await page.setViewportSize({ width: 320, height: 740 })
    await page.goto(origin + '/workspace')
    const locations = page.getByRole('button', { name: '文件位置', exact: true })
    await locations.waitFor()
    check(await page.locator('.workspace-sidebar-slot').count() === 0, '手机文件侧栏应默认收起')
    await locations.click()
    await page.getByRole('button', { name: '智能体文件', exact: true }).click()
    await page.locator('.workspace-sidebar-slot').waitFor({ state: 'detached' })
    await page.getByRole('button', { name: '打开导航菜单', exact: true }).click()
    await page.getByRole('dialog', { name: '主导航' }).waitFor()
    await page.keyboard.press('Escape')
    await page.getByRole('dialog', { name: '主导航' }).waitFor({ state: 'hidden' })
    check(await page.getByRole('button', { name: '打开导航菜单' }).evaluate(e => e === document.activeElement), '关闭导航后应恢复焦点')
    await page.screenshot({ path: '/tmp/mobile-workspace-320.png' })

    await page.goto(origin + '/equipment/queries')
    const queryCard = page.locator('.query-library-card').first()
    await queryCard.waitFor()
    await queryCard.click()
    const detail = page.locator('.query-detail-panel.mobile-detail-active')
    await detail.waitFor()
    await page.waitForFunction(() => {
      const rect = document.querySelector('.query-detail-panel.mobile-detail-active')?.getBoundingClientRect()
      return rect && rect.top >= 0 && rect.top < innerHeight / 2
    })
    await page.screenshot({ path: '/tmp/mobile-query-detail-320.png' })
    await page.getByRole('button', { name: '返回 Query 列表', exact: true }).click()
    await detail.waitFor({ state: 'hidden' })
    await page.getByPlaceholder('搜索 Query、理由或研究角度').waitFor()
  } finally {
    if (originalViewport) await page.setViewportSize(originalViewport)
  }
}
