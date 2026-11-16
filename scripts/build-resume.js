/**
 * 简历 HTML -> PDF，并报告页数与页面填充率。
 * 用法：node build-resume.js
 */
const { chromium } = require('playwright-core')
const path = require('path')
const fs = require('fs')

const ROOT = path.join(__dirname, '..')
const HTML = path.join(ROOT, 'docs', process.argv[2] || 'resume.html')
const OUT = path.join(ROOT, 'docs', process.argv[3] || '王振屹-简历.pdf')

const EDGE = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => fs.existsSync(p))

// 页面参数：与原简历一致（Letter，实测边距）
const MARGIN = { top: 0, right: 0, bottom: 0, left: 0 }
const PAGE_H = 279.4

async function main() {
  if (!EDGE) throw new Error('未找到 Edge')

  const browser = await chromium.launch({ executablePath: EDGE, headless: true })
  const page = await browser.newPage()

  // 证件照内联为 base64：setContent 的页面 origin 为 about:blank，
  // 相对路径与 file:// 都可能加载失败
  let html = fs.readFileSync(HTML, 'utf8')
  const photoPath = path.join(ROOT, 'docs', 'photo.png')
  if (fs.existsSync(photoPath)) {
    const b64 = fs.readFileSync(photoPath).toString('base64')
    html = html.replace('src="photo.png"', `src="data:image/png;base64,${b64}"`)
  }

  await page.setContent(html, { waitUntil: 'networkidle' })
  await page.emulateMedia({ media: 'print' })

  // 测量内容高度（相对单页可用高度）
  const metrics = await page.evaluate(
    ({ margin, pageH }) => {
      const mmToPx = 96 / 25.4
      const usablePx = (pageH - margin.top - margin.bottom) * mmToPx
      const contentPx = document.body.scrollHeight
      return {
        contentMm: +(contentPx / mmToPx).toFixed(1),
        usableMm: +(usablePx / mmToPx).toFixed(1),
        ratio: +(contentPx / usablePx).toFixed(3),
      }
    },
    { margin: MARGIN, pageH: PAGE_H },
  )

  await page.pdf({
    path: OUT,
    format: 'Letter',
    printBackground: true,
    preferCSSPageSize: true,
  })

  await browser.close()

  console.log(`内容高度：${metrics.contentMm} mm（单页可用 ${metrics.usableMm} mm）`)
  console.log(`占用比例：${(metrics.ratio * 100).toFixed(1)}%  （2.0 = 刚好两页）`)
  console.log(`已输出：${OUT}`)
}

main().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
