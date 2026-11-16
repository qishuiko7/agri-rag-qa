/**
 * 后端接口封装。
 * 统一处理 JSON 解析、错误提示与超时。
 */

const BASE = ''

async function request(path, { method = 'GET', body, params, timeout = 60000 } = {}) {
  let url = BASE + path
  if (params) {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.append(k, v)
    })
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const res = await fetch(url, {
      method,
      headers: body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const j = await res.json()
        detail = j.detail || detail
      } catch {
        /* 忽略非 JSON 错误体 */
      }
      throw new Error(detail)
    }
    const ct = res.headers.get('content-type') || ''
    return ct.includes('application/json') ? res.json() : res.text()
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  // ---------- 对话 ----------
  ask: (payload) => request('/api/chat/ask', { method: 'POST', body: payload }),
  status: () => request('/api/chat/status'),
  clearSession: (sessionId) =>
    request('/api/chat/clear', { method: 'POST', params: { session_id: sessionId } }),
  sessions: () => request('/api/chat/sessions'),
  guard: (q) => request('/api/chat/guard', { params: { q } }),

  // ---------- 知识库 ----------
  kbStats: () => request('/api/kb/stats'),
  kbDocuments: (params) => request('/api/kb/documents', { params }),
  kbPreview: (name, category) => request('/api/kb/preview', { params: { name, category } }),
  kbUpload: (formData, category) =>
    request('/api/kb/upload', { method: 'POST', body: formData, params: { category }, timeout: 120000 }),
  kbDelete: (names) => request('/api/kb/delete', { method: 'POST', body: { names } }),
  kbReclassify: (names, targetCategory) =>
    request('/api/kb/reclassify', {
      method: 'POST',
      body: { names, target_category: targetCategory },
    }),
  kbReport: () => request('/api/kb/report'),

  // ---------- 向量库 ----------
  vectorStats: () => request('/api/vector/stats'),
  vectorBuild: (payload) => request('/api/vector/build', { method: 'POST', body: payload }),
  vectorProgress: () => request('/api/vector/progress'),
  vectorReset: () => request('/api/vector/reset', { method: 'POST' }),
  vectorSources: () => request('/api/vector/sources'),
  vectorSearch: (q, k = 5) => request('/api/vector/search', { method: 'POST', params: { q, k } }),

  // ---------- 历史 ----------
  historyList: (payload) => request('/api/history/list', { method: 'POST', body: payload }),
  historyStats: () => request('/api/history/stats'),
  historyDelete: (ids) => request('/api/history/delete', { method: 'POST', body: { ids } }),
  historyClear: () => request('/api/history/clear', { method: 'POST' }),
  historyExportUrl: ({ keyword = '', start = '', end = '' } = {}) => {
    const qs = new URLSearchParams()
    if (keyword) qs.append('keyword', keyword)
    if (start) qs.append('start', start)
    if (end) qs.append('end', end)
    return `/api/history/export?${qs.toString()}`
  },

  // ---------- 设置 ----------
  getSettings: () => request('/api/settings'),
  saveSettings: (payload) => request('/api/settings', { method: 'POST', body: payload }),
  testModel: () => request('/api/settings/test', { method: 'POST', timeout: 60000 }),
  testEmbedding: () => request('/api/settings/test-embedding', { method: 'POST', timeout: 60000 }),

  // ---------- Agent ----------
  agentTools: () => request('/api/agent/tools'),
  agentAsk: (payload) => request('/api/agent/ask', { method: 'POST', body: payload, timeout: 180000 }),
}

/**
 * SSE 流式问答。
 * @param {object} opts { question, sessionId, mode, topK, onEvent }
 * @returns {function} 中止函数
 */
export function streamAsk({ question, sessionId = '', mode = 'rag', topK, onEvent }) {
  const qs = new URLSearchParams({ question, session_id: sessionId, mode })
  if (topK) qs.append('top_k', topK)
  const es = new EventSource(`/api/chat/stream?${qs.toString()}`)

  es.onmessage = (e) => {
    if (e.data === '[DONE]') {
      es.close()
      onEvent({ type: 'close' })
      return
    }
    try {
      onEvent(JSON.parse(e.data))
    } catch {
      /* 忽略解析失败的心跳包 */
    }
  }
  es.onerror = () => {
    es.close()
    onEvent({ type: 'close', error: true })
  }
  return () => es.close()
}
