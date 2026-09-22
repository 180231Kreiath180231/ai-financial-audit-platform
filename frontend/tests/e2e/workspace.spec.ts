import { expect, test } from '@playwright/test'

test('loads the local-first project workspace', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '项目资料' })).toBeVisible()
  await expect(page.getByText('严格离线', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('合成演示项目')).toBeVisible()
  await expect(page.getByRole('button', { name: '选择 PDF' })).toBeVisible()
})

test('mobile workspace exposes all three panes', async ({ page }) => {
  test.skip(test.info().project.name !== 'mobile', 'mobile-only assertion')
  await page.goto('/')
  const switcher = page.getByRole('navigation', { name: '项目工作区' })
  await expect(switcher.getByRole('button', { name: '资料' })).toBeVisible()
  await switcher.getByRole('button', { name: '处置' }).click()
  await expect(page.getByRole('heading', { name: '尚未选择任务' })).toBeVisible()
})
