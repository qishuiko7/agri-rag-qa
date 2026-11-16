<template>
  <div>
    <!-- 顶部介绍 -->
    <div class="hero">
      <div class="hero-text">
        <h2>面向农业场景的检索增强问答系统</h2>
        <p>
          基于 LangChain 构建，覆盖语料预处理、轻量切片、文件型向量库、语义检索、
          云端大模型生成、多轮对话与记录管理的完整链路。全部组件单机运行，无需服务器与独立显卡。
        </p>
        <div class="hero-actions">
          <router-link to="/chat" class="btn">开始提问</router-link>
          <router-link to="/vector" class="btn ghost">构建向量库</router-link>
        </div>
      </div>
      <div class="hero-badge">
        <div class="badge-num">{{ status.vector_chunks }}</div>
        <div class="badge-label">已入库片段</div>
      </div>
    </div>

    <!-- 运行状态 -->
    <div class="stat-grid">
      <div class="stat">
        <div class="label">语料文档</div>
        <div class="value">{{ kb.total || 0 }}<small>篇</small></div>
      </div>
      <div class="stat">
        <div class="label">语料总字数</div>
        <div class="value">{{ fmtNum(kb.total_chars) }}<small>字</small></div>
      </div>
      <div class="stat">
        <div class="label">向量片段</div>
        <div class="value">{{ status.vector_chunks || 0 }}<small>个</small></div>
      </div>
      <div class="stat">
        <div class="label">累计问答</div>
        <div class="value">{{ hist.total || 0 }}<small>次</small></div>
      </div>
      <div class="stat">
        <div class="label">平均响应</div>
        <div class="value">{{ hist.avg_latency_ms || 0 }}<small>ms</small></div>
      </div>
    </div>

    <!-- 系统状态 + 语料分布 -->
    <div class="two-col mt16">
      <div class="card">
        <div class="card-head">
          <h3>系统运行状态</h3>
          <button class="btn ghost sm" @click="refresh">刷新</button>
        </div>
        <ul class="status-list">
          <li>
            <span class="k">向量库</span>
            <span class="v">
              <span class="tag" :class="status.vector_ready ? '' : 'warn'">
                {{ status.vector_ready ? '已就绪' : '未构建' }}
              </span>
              <span class="muted small">{{ status.vector_chunks }} 片段 · {{ status.vector_size_mb }} MB</span>
            </span>
          </li>
          <li>
            <span class="k">嵌入模型</span>
            <span class="v">
              <span class="mono small">{{ status.embedding_provider }} / {{ status.embedding_model }}</span>
            </span>
          </li>
          <li>
            <span class="k">对话模型</span>
            <span class="v">
              <span class="tag" :class="status.llm_ready ? '' : 'warn'">
                {{ status.llm_ready ? status.llm_model : 'Mock 模式' }}
              </span>
            </span>
          </li>
          <li>
            <span class="k">切片参数</span>
            <span class="v mono small">
              size={{ status.chunk_size }} / overlap={{ status.chunk_overlap }}
            </span>
          </li>
          <li>
            <span class="k">检索条数</span>
            <span class="v mono small">top_k={{ status.top_k }} · 记忆 {{ status.memory_rounds }} 轮</span>
          </li>
        </ul>
        <div v-if="!status.llm_ready" class="notice mt12">
          当前为 Mock 演示模式。到「系统设置」填写百炼 API Key 并重启，即可获得真实农业解答。
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>语料分类分布</h3>
          <span class="hint">共 {{ kb.total || 0 }} 篇</span>
        </div>
        <div v-for="(v, k) in kb.by_category" :key="k" class="cat-row">
          <div class="cat-top">
            <span class="tag" :class="k">{{ v.name }}</span>
            <span class="muted small">{{ v.count }} 篇 · {{ fmtNum(v.chars) }} 字</span>
          </div>
          <div class="progress">
            <div class="progress-bar" :style="{ width: pct(v.count) + '%' }"></div>
          </div>
        </div>
        <div v-if="!kb.total" class="empty">
          <span class="icon">▤</span>
          语料目录为空，请先到「知识库管理」导入文档
        </div>
      </div>
    </div>

    <!-- 功能导航 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>核心功能</h3>
        <span class="hint">六个模块覆盖项目全流程</span>
      </div>
      <div class="feature-grid">
        <router-link v-for="f in features" :key="f.to" :to="f.to" class="feature">
          <div class="f-icon">{{ f.icon }}</div>
          <div class="f-title">{{ f.title }}</div>
          <div class="f-desc">{{ f.desc }}</div>
        </router-link>
      </div>
    </div>

    <!-- 近 7 日问答 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>近 7 日问答量</h3>
        <span class="hint">累计 {{ hist.total || 0 }} 次 · 拦截 {{ hist.blocked || 0 }} 次</span>
      </div>
      <div class="bars">
        <div v-for="d in hist.daily || []" :key="d.date" class="bar-col">
          <div class="bar-wrap">
            <div class="bar" :style="{ height: barHeight(d.count) }" :title="`${d.count} 次`"></div>
          </div>
          <div class="bar-label">{{ d.date.slice(5) }}</div>
          <div class="bar-num">{{ d.count }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const status = inject('appStatus')
const refreshStatus = inject('refreshStatus')

const kb = reactive({ total: 0, total_chars: 0, by_category: {} })
const hist = reactive({ total: 0, blocked: 0, avg_latency_ms: 0, daily: [] })

const features = [
  { to: '/chat', icon: '✦', title: '智能问答', desc: '单轮问答、多轮上下文、非农问题拦截' },
  { to: '/knowledge', icon: '▤', title: '知识库管理', desc: '批量导入、在线预览、四类归档、异常筛查' },
  { to: '/vector', icon: '◈', title: '向量库构建', desc: '切片参数配置、向量化入库、进度追踪' },
  { to: '/history', icon: '◷', title: '历史记录', desc: '条件检索、基础统计、CSV 导出' },
  { to: '/settings', icon: '⚙', title: '系统设置', desc: '模型接口、检索参数、连通性测试' },
  { to: '/chat', icon: '◐', title: 'Agent 模式', desc: '工具调用与多步推理（问答页可切换）' },
]

const maxDaily = computed(() => Math.max(1, ...(hist.daily || []).map((d) => d.count)))

function barHeight(n) {
  return Math.max(2, (n / maxDaily.value) * 100) + '%'
}

function pct(n) {
  const total = kb.total || 1
  return Math.round((n / total) * 100)
}

function fmtNum(n) {
  if (!n) return '0'
  if (n >= 10000) return (n / 10000).toFixed(1) + ' 万'
  return n.toLocaleString()
}

async function refresh() {
  try {
    const [k, h] = await Promise.all([api.kbStats(), api.historyStats()])
    Object.assign(kb, k)
    Object.assign(hist, h)
    await refreshStatus()
  } catch {
    /* 后端未就绪时保持空态 */
  }
}

onMounted(refresh)
</script>

<style scoped>
.hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  background: linear-gradient(120deg, #f0f8f3 0%, #e6f2ea 100%);
  border: 1px solid var(--green-100);
  border-radius: var(--radius);
  padding: 26px 28px;
  margin-bottom: 16px;
}

.hero-text h2 {
  margin: 0 0 8px;
  font-size: 19px;
  color: var(--green-900);
  font-weight: 600;
}

.hero-text p {
  margin: 0 0 16px;
  color: var(--text-2);
  font-size: 13px;
  max-width: 620px;
  line-height: 1.75;
}

.hero-actions {
  display: flex;
  gap: 10px;
}

.hero-badge {
  flex-shrink: 0;
  text-align: center;
  background: #fff;
  border: 1px solid var(--green-100);
  border-radius: var(--radius);
  padding: 16px 26px;
  box-shadow: var(--shadow-sm);
}

.badge-num {
  font-size: 30px;
  font-weight: 700;
  color: var(--green-600);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.badge-label {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-top: 4px;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.two-col .card + .card {
  margin-top: 0;
}

.status-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.status-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 0;
  border-bottom: 1px dashed #eef3f0;
  gap: 12px;
}

.status-list li:last-child {
  border-bottom: none;
}

.status-list .k {
  color: var(--text-2);
  font-size: 13px;
}

.status-list .v {
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: right;
}

.notice {
  background: var(--amber-bg);
  color: #7a5210;
  font-size: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  line-height: 1.6;
}

.cat-row {
  margin-bottom: 13px;
}

.cat-row:last-child {
  margin-bottom: 0;
}

.cat-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
  gap: 8px;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.feature {
  display: block;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  transition: all 0.15s;
  color: inherit;
}

.feature:hover {
  border-color: var(--green-300);
  background: var(--green-50);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.f-icon {
  font-size: 17px;
  color: var(--green-600);
  margin-bottom: 6px;
}

.f-title {
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 3px;
}

.f-desc {
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.55;
}

.bars {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  height: 130px;
  padding-top: 8px;
}

.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}

.bar-wrap {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.bar {
  width: 60%;
  max-width: 34px;
  background: linear-gradient(180deg, var(--green-500), var(--green-600));
  border-radius: 4px 4px 0 0;
  transition: height 0.3s;
  min-height: 2px;
}

.bar-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}

.bar-num {
  font-size: 11px;
  color: var(--green-700);
  font-weight: 500;
}

@media (max-width: 1100px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
