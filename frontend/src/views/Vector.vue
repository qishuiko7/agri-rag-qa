<template>
  <div>
    <!-- 当前状态 -->
    <div class="stat-grid">
      <div class="stat">
        <div class="label">向量库状态</div>
        <div class="value" :style="{ fontSize: '18px', color: info.ready ? 'var(--green-700)' : 'var(--amber)' }">
          {{ info.ready ? '已就绪' : '未构建' }}
        </div>
      </div>
      <div class="stat">
        <div class="label">片段总数</div>
        <div class="value">{{ info.chunks || 0 }}<small>个</small></div>
      </div>
      <div class="stat">
        <div class="label">占用空间</div>
        <div class="value">{{ info.size_mb || 0 }}<small>MB</small></div>
      </div>
      <div class="stat">
        <div class="label">向量维度</div>
        <div class="value">{{ info.dim || 0 }}</div>
      </div>
    </div>

    <!-- 构建配置 -->
    <div class="two-col mt16">
      <div class="card">
        <div class="card-head">
          <h3>切片参数</h3>
          <span class="hint">对齐文档节能策略</span>
        </div>

        <div class="field">
          <label>切片长度 chunk_size</label>
          <input v-model.number="form.chunk_size" type="number" class="input" min="100" max="2000" />
          <div class="desc">默认 500 字符。越小召回越精准，但片段数增多、入库变慢。</div>
        </div>

        <div class="field">
          <label>重叠长度 chunk_overlap</label>
          <input v-model.number="form.chunk_overlap" type="number" class="input" min="0" max="500" />
          <div class="desc">默认 50 字符。用于避免句子被切断导致语义丢失。</div>
        </div>

        <div class="field">
          <label>入库模式</label>
          <select v-model="form.rebuild" class="select">
            <option :value="true">清空重建（推荐，保证数据一致）</option>
            <option :value="false">追加入库（在现有库后追加）</option>
          </select>
        </div>

        <div class="field">
          <label>处理范围</label>
          <select v-model="form.category" class="select">
            <option value="">全部语料</option>
            <option v-for="(name, key) in categories" :key="key" :value="key">仅 {{ name }}</option>
          </select>
        </div>

        <div class="btn-row">
          <button class="btn block" :disabled="progress.running" @click="build">
            {{ progress.running ? '构建中…' : '开始构建向量库' }}
          </button>
        </div>
        <button class="btn ghost block mt12" :disabled="progress.running" @click="resetStore">
          清空向量库
        </button>
      </div>

      <!-- 进度 -->
      <div class="card">
        <div class="card-head">
          <h3>入库进度</h3>
          <span class="hint">{{ stageLabel }}</span>
        </div>

        <div class="progress-big">
          <div class="progress">
            <div class="progress-bar" :style="{ width: progress.percent + '%' }"></div>
          </div>
          <div class="progress-num">{{ progress.percent || 0 }}%</div>
        </div>

        <ul class="prog-list">
          <li>
            <span>扫描文件</span>
            <span class="mono">{{ progress.total_files || 0 }}</span>
          </li>
          <li>
            <span>已处理</span>
            <span class="mono">{{ progress.processed_files || 0 }}</span>
          </li>
          <li>
            <span>生成片段</span>
            <span class="mono">{{ progress.total_chunks || 0 }}</span>
          </li>
          <li>
            <span>已写入</span>
            <span class="mono">{{ progress.written_chunks || 0 }}</span>
          </li>
          <li>
            <span>跳过文件</span>
            <span class="mono">{{ progress.skipped_files || 0 }}</span>
          </li>
          <li>
            <span>耗时</span>
            <span class="mono">{{ progress.elapsed || 0 }} s</span>
          </li>
        </ul>

        <div v-if="progress.message" class="prog-msg" :class="{ err: progress.stage === 'error' }">
          {{ progress.message }}
        </div>

        <div class="hint-box mt12">
          <strong>说明</strong>
          入库时会对语料做清洗去重、按中文标点切片，再调用嵌入模型转为向量写入本地 Chroma。
          首次构建约需 1~3 分钟（取决于语料量与嵌入接口速度）。
        </div>
      </div>
    </div>

    <!-- 已入库来源 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>已入库语料</h3>
        <span class="hint">共 {{ sources.length }} 个来源</span>
      </div>
      <div v-if="!sources.length" class="empty">
        <span class="icon">◈</span>
        向量库为空，完成一次构建后这里会显示来源清单
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>来源文件</th>
            <th style="width: 120px">分类</th>
            <th style="width: 100px">片段数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sources.slice(0, 60)" :key="s.source">
            <td>
              <div class="name" :title="s.source">{{ s.title || s.source }}</div>
            </td>
            <td><span class="tag" :class="s.category">{{ catName(s.category) }}</span></td>
            <td class="mono small">{{ s.chunks }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="sources.length > 60" class="muted small mt12">
        仅展示前 60 条，共 {{ sources.length }} 条
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api } from '../api'

const notify = inject('notify')
const refreshStatus = inject('refreshStatus')

const info = reactive({ ready: false, chunks: 0, size_mb: 0, dim: 0 })
const progress = reactive({ running: false, stage: 'idle', percent: 0 })
const sources = ref([])
const categories = ref({})

const form = reactive({
  chunk_size: 500,
  chunk_overlap: 50,
  rebuild: true,
  category: '',
})

const stageMap = {
  idle: '空闲',
  scanning: '扫描文件',
  loading: '加载清洗',
  splitting: '文本切片',
  embedding: '向量化入库',
  done: '已完成',
  error: '出错',
}

const stageLabel = computed(() => stageMap[progress.stage] || progress.stage)

function catName(key) {
  return categories.value[key] || '通用农技'
}

async function loadInfo() {
  try {
    const [st, cfg] = await Promise.all([api.vectorStats(), api.getSettings()])
    Object.assign(info, st)
    form.chunk_size = st.chunk_size
    form.chunk_overlap = st.chunk_overlap
    categories.value = {
      planting: '种植技术',
      pest: '病虫害防治',
      breeding: '养殖技术',
      general: '通用农技',
    }
  } catch (e) {
    notify('读取向量库状态失败：' + e.message, 'error')
  }
}

async function loadSources() {
  try {
    const res = await api.vectorSources()
    sources.value = res.items || []
  } catch {
    sources.value = []
  }
}

let pollTimer = null

async function poll() {
  try {
    const p = await api.vectorProgress()
    Object.assign(progress, p)
    if (!p.running && p.stage === 'done') {
      clearInterval(pollTimer)
      pollTimer = null
      notify(p.message || '向量库构建完成')
      await Promise.all([loadInfo(), loadSources()])
      await refreshStatus()
    } else if (!p.running && p.stage === 'error') {
      clearInterval(pollTimer)
      pollTimer = null
      notify('入库失败：' + (p.error || '未知错误'), 'error', 4000)
    }
  } catch {
    /* 忽略轮询期间的瞬时错误 */
  }
}

async function build() {
  try {
    await api.vectorBuild({
      rebuild: form.rebuild,
      category: form.category || null,
      chunk_size: form.chunk_size,
      chunk_overlap: form.chunk_overlap,
    })
    notify('入库任务已启动')
    Object.assign(progress, { running: true, stage: 'scanning', percent: 0 })
    if (!pollTimer) pollTimer = setInterval(poll, 1200)
  } catch (e) {
    notify(e.message, 'error')
  }
}

async function resetStore() {
  if (!confirm('确定清空向量库？已入库的片段将全部删除，需重新构建。')) return
  try {
    await api.vectorReset()
    notify('向量库已清空')
    await Promise.all([loadInfo(), loadSources()])
    await refreshStatus()
  } catch (e) {
    notify(e.message, 'error')
  }
}

onMounted(async () => {
  await loadInfo()
  await loadSources()
  const p = await api.vectorProgress().catch(() => null)
  if (p) {
    Object.assign(progress, p)
    if (p.running) pollTimer = setInterval(poll, 1200)
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.two-col .card + .card {
  margin-top: 0;
}

.btn-row {
  margin-top: 4px;
}

.progress-big {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.progress-big .progress {
  flex: 1;
  height: 10px;
}

.progress-num {
  font-size: 15px;
  font-weight: 600;
  color: var(--green-700);
  font-variant-numeric: tabular-nums;
  min-width: 52px;
  text-align: right;
}

.prog-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.prog-list li {
  display: flex;
  justify-content: space-between;
  padding: 7px 0;
  border-bottom: 1px dashed #eef3f0;
  font-size: 12.5px;
  color: var(--text-2);
}

.prog-list li:last-child {
  border-bottom: none;
}

.prog-msg {
  margin-top: 12px;
  font-size: 12px;
  color: var(--green-700);
  background: var(--green-50);
  border: 1px solid var(--green-100);
  border-radius: var(--radius-sm);
  padding: 8px 11px;
  line-height: 1.6;
}

.prog-msg.err {
  color: var(--red);
  background: var(--red-bg);
  border-color: #f5d5d2;
}

.hint-box {
  font-size: 11.5px;
  color: var(--text-2);
  background: #fafcfb;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  line-height: 1.7;
}

.hint-box strong {
  display: block;
  color: var(--text);
  margin-bottom: 3px;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
