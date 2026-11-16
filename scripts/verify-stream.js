/**
 * 验证 Agent 流式的中间状态：工具执行中是否实时可见。
 * 用法：node verify-stream.js [baseUrl]
 */
const { chromium } = require('playwright-core')
const path = require('path')
const fs = require('fs')

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = path.join(__dirname, '..', 'docs', 'screenshots')

const EDGE = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => fs.existsSync(p))

async function main() {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))

  await page.goto(`${BASE}/chat`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)

  // 切到 Agent 模式
  await page.locator('.mode-btn').nth(1).click()
  await page.waitForTimeout(200)

  await page.locator('.composer textarea').fill('长春明天能打药吗')
  const t0 = Date.now()
  await page.locator('.send-btn').click()

  // 等待「执行中」状态出现，证明中间过程可见
  let sawRunning = false
  try {
    await page.waitForSelector('.tool-status.running', { timeout: 20000 })
    sawRunning = true
    console.log(`  工具「执行中」状态出现，耗时 ${Date.now() - t0} ms`)
    await page.screenshot({ path: path.join(OUT, '10-Agent执行中.png'), fullPage: true })
  } catch {
    console.log('  未捕获到「执行中」状态（可能工具执行太快）')
  }

  // 等回答完成
  await page.waitForFunction(
    () => {
      const els = document.querySelectorAll('.msg.assistant .answer')
      return els.length > 0 && els[0].innerText.trim().length > 20
    },
    { timeout: 60000 },
  )
  const done = Date.now()
  console.log(`  回答完成，总耗时 ${done - t0} ms`)

  const status = await page.locator('.tool-status').first().innerText()
  console.log(`  最终工具状态：${status}`)
  console.log(`  实时中间态可见：${sawRunning ? '是' : '否'}`)
  console.log(`  前端错误：${errors.length ? errors.join('; ') : '无'}`)

  await browser.close()
}

main().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
