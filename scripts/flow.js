/**
 * 交互流程验证：模拟真实用户提问，检查流式渲染、来源展示、Agent 模式。
 * 用法：node flow.js [baseUrl]
 */
const { chromium } = require('playwright-core')
const path = require('path')
const fs = require('fs')

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = path.join(__dirname, '..', 'shots3')

const EDGE = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => fs.existsSync(p))

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch({ executablePath: EDGE, headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })

  // ---------- 1. RAG 模式提问 ----------
  console.log('1. RAG 模式提问…')
  await page.goto(`${BASE}/chat`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)

  // 点第一个示例问题
  await page.locator('.example').first().click()
  // 等待回答出现（助手气泡内容非空）
  await page.waitForFunction(
    () => {
      const bubbles = document.querySelectorAll('.msg.assistant .answer')
      return bubbles.length > 0 && bubbles[0].innerText.length > 30
    },
    { timeout: 30000 },
  )
  await page.waitForTimeout(1500)

  const answerText = await page.locator('.msg.assistant .answer').first().innerText()
  console.log(`   回答长度：${answerText.length} 字`)
  console.log(`   回答预览：${answerText.slice(0, 80).replace(/\n/g, ' ')}…`)

  const srcToggle = page.locator('.src-toggle').first()
  const hasSources = await srcToggle.count()
  console.log(`   来源按钮：${hasSources > 0 ? '有' : '无'}`)

  // 展开来源
  if (hasSources > 0) {
    await srcToggle.click()
    await page.waitForTimeout(600)
    const srcCount = await page.locator('.src-item').count()
    console.log(`   展开后来源条目：${srcCount}`)
  }

  await page.screenshot({ path: path.join(OUT, '01-chat-rag.png'), fullPage: true })

  // ---------- 2. 切换 Agent 模式 ----------
  console.log('\n2. Agent 模式提问…')
  await page.locator('.mode-btn').nth(1).click()
  await page.waitForTimeout(300)

  await page.locator('.composer textarea').fill('长春最近天气适合打药吗')
  await page.locator('.send-btn').click()

  await page.waitForFunction(
    () => {
      const els = document.querySelectorAll('.msg.assistant .answer')
      return els.length >= 2 && els[1].innerText.trim().length > 20
    },
    { timeout: 120000 },
  )
  await page.waitForTimeout(2500)

  const agentAnswer = await page.locator('.msg.assistant .answer').nth(1).innerText()
  const toolCount = await page.locator('.tool-item').count()
  console.log(`   Agent 回答长度：${agentAnswer.length} 字`)
  console.log(`   工具调用条目：${toolCount}`)

  await page.screenshot({ path: path.join(OUT, '02-chat-agent.png'), fullPage: true })

  // ---------- 3. 历史记录页 ----------
  console.log('\n3. 历史记录…')
  await page.goto(`${BASE}/history`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const recCount = await page.locator('.rec').count()
  console.log(`   记录条数：${recCount}`)
  await page.screenshot({ path: path.join(OUT, '03-history.png'), fullPage: true })

  // ---------- 4. 知识库预览 ----------
  console.log('\n4. 知识库预览…')
  await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const previewBtn = page.locator('table tbody tr .link-btn').first()
  if ((await previewBtn.count()) > 0) {
    await previewBtn.click()
    await page.waitForTimeout(1000)
    const modalText = await page.locator('.modal-body').innerText()
    console.log(`   预览内容长度：${modalText.length} 字`)
    await page.screenshot({ path: path.join(OUT, '04-kb-preview.png'), fullPage: true })
  } else {
    console.log('   未找到可预览的文档')
  }

  console.log('\n--- 前端错误 ---')
  if (errors.length) errors.forEach((e) => console.log('  ' + e))
  else console.log('  无')

  await browser.close()
}

main().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
