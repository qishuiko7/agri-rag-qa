<template>
  <div class="layout">
    <!-- 侧边导航 -->
    <aside class="sidebar">
      <div class="brand">
        <h1>农技通</h1>
        <p>农业智能问答助手 · RAG</p>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path === item.path }"
        >
          <span class="icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div>v1.0 · 本地单机部署</div>
        <div>{{ modeLabel }}</div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <header class="topbar">
        <div>
          <h2>
            {{ route.meta.title || '农技通' }}
            <span class="sub">{{ route.meta.sub || '' }}</span>
          </h2>
        </div>
        <div class="status-pills">
          <span class="pill" :class="vectorReady ? '' : 'off'">
            <span class="dot" :class="vectorReady ? '' : 'off'"></span>
            向量库 {{ vectorReady ? `${status.vector_chunks} 片段` : '未构建' }}
          </span>
          <span class="pill" :class="status.llm_ready ? '' : 'warn'">
            <span class="dot" :class="status.llm_ready ? '' : 'warn'"></span>
            {{ status.llm_ready ? status.llm_model : 'Mock 演示模式' }}
          </span>
        </div>
      </header>

      <div class="content" :class="{ flush: route.path === '/chat' }">
        <router-view />
      </div>
    </div>

    <!-- 全局提示 -->
    <div class="toast-wrap">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">{{ t.text }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, provide, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'

const route = useRoute()

const navItems = [
  { path: '/', label: '系统首页', icon: '⌂' },
  { path: '/chat', label: '智能问答', icon: '✦' },
  { path: '/knowledge', label: '知识库管理', icon: '▤' },
  { path: '/vector', label: '向量库构建', icon: '◈' },
  { path: '/history', label: '历史记录', icon: '◷' },
  { path: '/settings', label: '系统设置', icon: '⚙' },
]

// ---------- 全局状态 ----------
const status = reactive({
  vector_ready: false,
  vector_chunks: 0,
  llm_ready: false,
  llm_model: '',
  embedding_provider: 'mock',
  embedding_model: '',
  mode: 'Mock 演示',
})

const vectorReady = computed(() => status.vector_ready)
const modeLabel = computed(() => (status.llm_ready ? '云端模型已就绪' : 'Mock 演示模式'))

async function refreshStatus() {
  try {
    const s = await api.status()
    Object.assign(status, s)
  } catch {
    /* 后端未启动时静默失败 */
  }
}

// ---------- Toast ----------
const toasts = ref([])
let toastSeq = 0

function notify(text, type = 'info', duration = 2600) {
  const id = ++toastSeq
  toasts.value.push({ id, text, type })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, duration)
}

provide('notify', notify)
provide('appStatus', status)
provide('refreshStatus', refreshStatus)

let timer = null
onMounted(() => {
  refreshStatus()
  timer = setInterval(refreshStatus, 30000)
})
onUnmounted(() => clearInterval(timer))
</script>
