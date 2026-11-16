<template>
  <div>
    <!-- 统计 -->
    <div class="stat-grid">
      <div class="stat">
        <div class="label">累计问答</div>
        <div class="value">{{ stats.total || 0 }}<small>次</small></div>
      </div>
      <div class="stat">
        <div class="label">今日问答</div>
        <div class="value">{{ stats.today || 0 }}<small>次</small></div>
      </div>
      <div class="stat">
        <div class="label">拦截次数</div>
        <div class="value">{{ stats.blocked || 0 }}<small>次</small></div>
      </div>
      <div class="stat">
        <div class="label">平均响应</div>
        <div class="value">{{ stats.avg_latency_ms || 0 }}<small>ms</small></div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>记录查询</h3>
        <div class="actions">
          <button class="btn ghost sm" @click="exportCsv">导出 CSV</button>
          <button class="btn ghost sm" :disabled="!selected.length" @click="doDelete">
            删除选中 {{ selected.length ? `(${selected.length})` : '' }}
          </button>
          <button class="btn ghost sm" @click="clearAll">清空全部</button>
        </div>
      </div>

      <div class="filter-row">
        <input v-model="filters.keyword" class="input" placeholder="按问题或回答关键词搜索" @keyup.enter="search" />
        <input v-model="filters.start" type="date" class="input date" />
        <span class="muted">至</span>
        <input v-model="filters.end" type="date" class="input date" />
        <button class="btn" @click="search">查询</button>
        <button class="btn ghost" @click="resetFilters">重置</button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>问答记录</h3>
        <span class="hint">共 {{ result.total || 0 }} 条</span>
      </div>

      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!result.items.length" class="empty">
        <span class="icon">◷</span>
        暂无问答记录，去「智能问答」提个问题吧
      </div>

      <div v-else class="rec-list">
        <div v-for="r in result.items" :key="r.id" class="rec">
          <div class="rec-head">
            <input type="checkbox" :value="r.id" v-model="selected" />
            <span class="rec-time mono">{{ r.datetime }}</span>
            <span class="tag gray">{{ r.mode === 'agent' ? 'Agent' : 'RAG' }}</span>
            <span v-if="r.blocked" class="tag warn">已拦截</span>
            <span class="muted small">{{ r.latency_ms }} ms</span>
            <span v-if="r.tool_calls && r.tool_calls.length" class="tag">
              {{ r.tool_calls.length }} 次工具调用
            </span>
            <button class="link-btn" @click="r._open = !r._open">{{ r._open ? '收起' : '展开' }}</button>
            <button class="link-btn danger" @click="deleteOne(r)">删除</button>
          </div>

          <div class="rec-q">{{ r.question }}</div>

          <div v-if="r._open" class="rec-detail">
            <div class="detail-block">
              <div class="detail-label">回答</div>
              <div class="detail-text">{{ r.answer }}</div>
            </div>
            <div v-if="r.sources && r.sources.length" class="detail-block">
              <div class="detail-label">参考来源（{{ r.sources.length }}）</div>
              <div v-for="(s, i) in r.sources" :key="i" class="detail-src">
                <span class="tag" :class="s.category_key">{{ s.category }}</span>
                <span class="src-name">{{ s.title }}</span>
              </div>
            </div>
            <div v-if="r.tool_calls && r.tool_calls.length" class="detail-block">
              <div class="detail-label">工具调用轨迹</div>
              <div v-for="(t, i) in r.tool_calls" :key="i" class="detail-src">
                <span class="mono small tool-n">{{ i + 1 }}. {{ t.name }}</span>
                <span class="muted small">{{ t.ok === false ? '失败' : '成功' }}</span>
              </div>
            </div>
            <div class="detail-meta muted small">会话 {{ r.session_id }}</div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="result.total > result.page_size" class="pager">
        <button class="btn ghost sm" :disabled="result.page <= 1" @click="go(result.page - 1)">上一页</button>
        <span class="muted small">
          第 {{ result.page }} / {{ totalPages }} 页
        </span>
        <button class="btn ghost sm" :disabled="result.page >= totalPages" @click="go(result.page + 1)">
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const notify = inject('notify')

const stats = reactive({ total: 0, today: 0, blocked: 0, avg_latency_ms: 0 })
const result = reactive({ total: 0, page: 1, page_size: 20, items: [] })
const loading = ref(false)
const selected = ref([])

const filters = reactive({ keyword: '', start: '', end: '' })

const totalPages = computed(() => Math.max(1, Math.ceil(result.total / result.page_size)))

async function loadStats() {
  try {
    Object.assign(stats, await api.historyStats())
  } catch {
    /* 忽略 */
  }
}

async function load(page = 1) {
  loading.value = true
  selected.value = []
  try {
    const res = await api.historyList({
      keyword: filters.keyword,
      start: filters.start,
      end: filters.end,
      page,
      page_size: result.page_size,
    })
    // 保留展开状态
    res.items = res.items.map((r) => ({ ...r, _open: false }))
    Object.assign(result, res)
  } catch (e) {
    notify('查询失败：' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

function search() {
  load(1)
}

function resetFilters() {
  filters.keyword = ''
  filters.start = ''
  filters.end = ''
  load(1)
}

function go(page) {
  load(page)
}

function exportCsv() {
  const url = api.historyExportUrl({
    keyword: filters.keyword,
    start: filters.start,
    end: filters.end,
  })
  window.open(url, '_blank')
  notify('已开始下载 CSV')
}

async function deleteOne(r) {
  if (!confirm('确定删除这条记录？')) return
  try {
    await api.historyDelete([r.id])
    notify('已删除 1 条记录')
    await Promise.all([load(result.page), loadStats()])
  } catch (e) {
    notify('删除失败：' + e.message, 'error')
  }
}

async function doDelete() {
  if (!selected.value.length) return
  if (!confirm(`确定删除选中的 ${selected.value.length} 条记录？`)) return
  try {
    const res = await api.historyDelete(selected.value)
    notify(`已删除 ${res.removed} 条记录`)
    await Promise.all([load(result.page), loadStats()])
  } catch (e) {
    notify('删除失败：' + e.message, 'error')
  }
}

async function clearAll() {
  if (!confirm('确定清空全部问答记录？该操作不可恢复，建议先导出备份。')) return
  try {
    const res = await api.historyClear()
    notify(`已清空 ${res.removed} 条记录`)
    await Promise.all([load(1), loadStats()])
  } catch (e) {
    notify('清空失败：' + e.message, 'error')
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), load(1)])
})
</script>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
}

.filter-row {
  display: flex;
  gap: 9px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-row .input {
  flex: 1;
  min-width: 160px;
}

.input.date {
  flex: 0 0 auto;
  width: 150px;
}

.rec-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rec {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 11px 14px;
  transition: border-color 0.15s;
}

.rec:hover {
  border-color: var(--border-strong);
}

.rec-head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  margin-bottom: 7px;
}

.rec-time {
  font-size: 11.5px;
  color: var(--text-muted);
}

.rec-q {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text);
  line-height: 1.6;
}

.rec-detail {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}

.detail-block {
  margin-bottom: 11px;
}

.detail-label {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 5px;
  font-weight: 500;
}

.detail-text {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.75;
  white-space: pre-wrap;
  background: #fafcfb;
  border-radius: 6px;
  padding: 9px 12px;
}

.detail-src {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 12px;
}

.src-name {
  color: var(--text-2);
}

.tool-n {
  color: var(--green-700);
}

.link-btn {
  font-size: 12px;
  color: var(--green-600);
  padding: 0 3px;
  margin-left: auto;
}

.link-btn + .link-btn {
  margin-left: 6px;
}

.link-btn:hover {
  text-decoration: underline;
}

.link-btn.danger {
  color: var(--red);
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
