/**
 * 前端渲染验证脚本：用系统 Edge 打开各页面并截图。
 * 用法：node shot.js [baseUrl] [outDir]
 */
const { chromium } = require('playwright-core')
const path = require('path')
const fs = require('fs')

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = process.argv[3] || path.join(__dirname, 'shots')

const EDGE_PATHS = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
]

const PAGES = [
  { path: '/', name: '01-home' },
  { path: '/chat', name: '02-chat' },
  { path: '/knowledge', name: '03-knowledge' },
  { path: '/vector', name: '04-vector' },
  { path: '/history', name: '05-history' },
  { path: '/settings', name: '06-settings' },
]

async function main() {
  const exe = EDGE_PATHS.find((p) => fs.existsSync(p))
  if (!exe) throw new Error('未找到 Edge')

  fs.mkdirSync(OUT, { recursive: true })

  const browser = await chromium.launch({ executablePath: exe, headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const page = await ctx.newPage()

  const errors = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`[console] ${m.text()}`)
  })
  page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

  for (const p of PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 }).catch((e) => {
      errors.push(`[goto ${p.path}] ${e.message}`)
    })
    await page.waitForTimeout(1200)
    const file = path.join(OUT, `${p.name}.png`)
    await page.screenshot({ path: file, fullPage: true })
    console.log(`saved ${file}`)
  }

  // 额外：检查页面是否有实际内容
  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 300))
  console.log('\n--- 最后一页文本片段 ---\n' + bodyText)

  if (errors.length) {
    console.log('\n--- 前端错误 ---')
    errors.forEach((e) => console.log(e))
  } else {
    console.log('\n前端无 console/page 错误')
  }

  await browser.close()
}

main().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
