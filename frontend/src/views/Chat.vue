<template>
  <div class="chat-page">
    <!-- 对话区 -->
    <div ref="scrollBox" class="messages">
      <!-- 欢迎页 -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="welcome-icon">🌾</div>
        <h2>你好，我是农技通</h2>
        <p>可以问我种植、病虫害、养殖、施肥、农事管理方面的任何问题。</p>
        <div class="examples">
          <button v-for="q in examples" :key="q" class="example" @click="send(q)">
            {{ q }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === 'user' ? '我' : '禾' }}</div>
        <div class="bubble-wrap">
          <div class="bubble">
            <div v-if="m.blocked" class="blocked-tag">非农业问题已拦截</div>
            <div class="answer" v-html="render(m.content)"></div>
            <span v-if="m.streaming" class="cursor">▋</span>
          </div>

          <!-- 工具调用（Agent 模式） -->
          <div v-if="m.toolCalls && m.toolCalls.length" class="tools">
            <div class="tools-title">调用工具 {{ m.toolCalls.length }} 次</div>
            <div v-for="(t, ti) in m.toolCalls" :key="ti" class="tool-item">
              <span class="tool-name">{{ t.label || t.name }}</span>
              <span class="tool-args mono">{{ shortArgs(t.args) }}</span>
              <span
                class="tool-status"
                :class="t.status === 'running' ? 'running' : t.ok === false ? 'bad' : 'ok'"
              >
                {{ t.status === 'running' ? '执行中' : t.ok === false ? '失败' : '成功' }}
              </span>
            </div>
          </div>

          <!-- 参考来源 -->
          <div v-if="m.sources && m.sources.length" class="sources">
            <button class="src-toggle" @click="m.showSrc = !m.showSrc">
              参考 {{ m.sources.length }} 条知识库片段
              <span class="arrow">{{ m.showSrc ? '▴' : '▾' }}</span>
            </button>
            <div v-if="m.showSrc" class="src-list">
              <div v-for="(s, si) in m.sources" :key="si" class="src-item">
                <div class="src-head">
                  <span class="src-idx">{{ si + 1 }}</span>
                  <span class="src-title">{{ s.title }}</span>
                  <span class="tag" :class="s.category_key">{{ s.category }}</span>
                  <span class="muted small">相似度 {{ (1 - s.score).toFixed(2) }}</span>
                </div>
                <div class="src-content">{{ s.content }}</div>
              </div>
            </div>
          </div>

          <div v-if="m.meta" class="meta">{{ m.meta }}</div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="composer">
      <div class="composer-top">
        <div class="mode-switch">
          <button
            class="mode-btn"
            :class="{ active: mode === 'rag' }"
            @click="mode = 'rag'"
            title="单次检索 + 生成，回答快、可控"
          >
            RAG 模式
          </button>
          <button
            class="mode-btn"
            :class="{ active: mode === 'agent' }"
            @click="mode = 'agent'"
            title="模型自主调用工具、多步推理"
          >
            Agent 模式
          </button>
        </div>
        <div class="composer-tools">
          <span class="muted small">会话 {{ sessionId.slice(0, 6) }}</span>
          <button class="btn ghost sm" @click="clearSession" :disabled="loading">清空会话</button>
        </div>
      </div>

      <div class="input-row">
        <textarea
          v-model="input"
          class="textarea"
          rows="2"
          placeholder="输入农业问题，Enter 发送，Shift+Enter 换行"
          :disabled="loading"
          @keydown.enter.exact.prevent="send()"
        ></textarea>
        <button class="btn send-btn" :disabled="loading || !input.trim()" @click="send()">
          {{ loading ? '思考中' : '发送' }}
        </button>
      </div>

      <div v-if="!vectorReady" class="composer-warn">
        向量库尚未构建，回答将缺少知识库支撑。请先到「向量库构建」页面执行入库。
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api, streamAsk } from '../api'

const notify = inject('notify')
const status = inject('appStatus')

const messages = ref([])
const input = ref('')
const loading = ref(false)
const mode = ref('rag')
const sessionId = ref('')
const scrollBox = ref(null)

// 当前流式连接的关闭函数：切换页面或重新提问时要主动断开，
// 否则 EventSource 会在后台继续接收数据
let abortStream = null

const vectorReady = computed(() => status.vector_ready)

const examples = [
  '小麦越冬水什么时候浇比较合适？',
  '番茄叶片发黄卷曲是什么原因？',
  '玉米螟怎么防治，用什么药？',
  '冬季大棚蔬菜如何防冻害？',
]

function render(text) {
  if (!text) return ''
  // 转义 HTML 后，把换行转成 <br>，保证安全
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc.replace(/\n/g, '<br>')
}

function shortArgs(args) {
  if (!args) return ''
  const s = typeof args === 'string' ? args : JSON.stringify(args)
  return s.length > 60 ? s.slice(0, 60) + '…' : s
}

async function scrollBottom() {
  await nextTick()
  const el = scrollBox.value
  if (el) el.scrollTop = el.scrollHeight
}

function newSession() {
  sessionId.value = Math.random().toString(36).slice(2, 14)
}

async function send(preset) {
  const q = (preset ?? input.value).trim()
  if (!q || loading.value) return

  if (!sessionId.value) newSession()

  messages.value.push({ role: 'user', content: q })
  input.value = ''
  loading.value = true

  messages.value.push({
    role: 'assistant',
    content: '',
    sources: [],
    toolCalls: [],
    showSrc: false,
    streaming: true,
    meta: '',
  })
  // 取数组中的元素（Vue 已包装为响应式代理），直接持有字面量对象无法触发视图更新
  const assistant = messages.value[messages.value.length - 1]
  await scrollBottom()

  const t0 = performance.now()

  if (mode.value === 'agent') {
    // Agent 模式也走 SSE：能看到工具调用过程与流式回答，
    // 否则用户要干等 8~10 秒才看到任何反馈
    abortStream = streamAsk({
      question: q,
      sessionId: sessionId.value,
      mode: 'agent',
      onEvent: (evt) => {
        if (evt.type === 'sources') {
          assistant.sources = evt.data || []
        } else if (evt.type === 'tool_start') {
          assistant.toolCalls.push({
            name: evt.data.name,
            label: evt.data.label,
            args: evt.data.args,
            status: 'running',
          })
          scrollBottom()
        } else if (evt.type === 'tool_end') {
          // 找到同名且仍在执行的那条，回填结果
          const running = assistant.toolCalls.filter(
            (t) => t.name === evt.data.name && t.status === 'running',
          )
          const target = running[running.length - 1]
          if (target) {
            target.ok = evt.data.ok
            target.summary = evt.data.summary
            target.elapsed_ms = evt.data.elapsed_ms
            target.status = 'done'
          }
          scrollBottom()
        } else if (evt.type === 'delta') {
          assistant.content += evt.data
          scrollBottom()
        } else if (evt.type === 'done') {
          const total = Math.round(performance.now() - t0)
          const n = assistant.toolCalls.length
          assistant.meta = `Agent · ${total} ms · ${n} 次工具调用`
          assistant.blocked = evt.data?.blocked
          assistant.streaming = false
          loading.value = false
          scrollBottom()
        } else if (evt.type === 'error') {
          assistant.content = `出错：${evt.data}`
          assistant.streaming = false
          loading.value = false
        } else if (evt.type === 'close') {
          if (!assistant.content) {
            assistant.content = evt.error ? '连接中断，请重试。' : '（未收到回答）'
          }
          assistant.streaming = false
          loading.value = false
          abortStream = null
        }
      },
    })
    return
  }

  // RAG 模式：SSE 流式
  let firstTokenAt = 0
  abortStream = streamAsk({
    question: q,
    sessionId: sessionId.value,
    mode: 'rag',
    onEvent: (evt) => {
      if (evt.type === 'sources') {
        assistant.sources = evt.data || []
      } else if (evt.type === 'delta') {
        if (!firstTokenAt) firstTokenAt = performance.now()
        assistant.content += evt.data
        scrollBottom()
      } else if (evt.type === 'done') {
        const total = Math.round(performance.now() - t0)
        const ttft = firstTokenAt ? Math.round(firstTokenAt - t0) : 0
        assistant.meta = `RAG · 首字 ${ttft} ms · 总计 ${total} ms`
        assistant.blocked = evt.data?.blocked
        assistant.streaming = false
        loading.value = false
        scrollBottom()
      } else if (evt.type === 'error') {
        assistant.content = `出错：${evt.data}`
        assistant.streaming = false
        loading.value = false
      } else if (evt.type === 'close') {
        // 连接意外中断时给出明确提示，避免气泡一直空白
        if (!assistant.content) {
          assistant.content = evt.error ? '连接中断，请重试。' : '（未收到回答）'
        }
        assistant.streaming = false
        loading.value = false
        abortStream = null
      }
    },
  })
}

async function clearSession() {
  if (sessionId.value) {
    try {
      await api.clearSession(sessionId.value)
    } catch {
      /* 忽略 */
    }
  }
  messages.value = []
  newSession()
  notify('会话已清空，上下文记忆已释放')
}

onMounted(() => {
  newSession()
  if (!status.vector_ready) {
    notify('向量库尚未构建，建议先完成入库', 'warn', 3200)
  }
})

onUnmounted(() => {
  // 离开问答页时断开流式连接，避免后台持续接收数据
  if (abortStream) {
    abortStream()
    abortStream = null
  }
})
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 8px;
}

.welcome {
  max-width: 620px;
  margin: 8vh auto 0;
  text-align: center;
}

.welcome-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.welcome h2 {
  font-size: 20px;
  margin: 0 0 8px;
  color: var(--green-900);
}

.welcome p {
  color: var(--text-2);
  font-size: 13.5px;
  margin: 0 0 22px;
}

.examples {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 9px;
}

.example {
  padding: 11px 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  color: var(--text-2);
  text-align: left;
  transition: all 0.15s;
  line-height: 1.5;
}

.example:hover {
  border-color: var(--green-300);
  background: var(--green-50);
  color: var(--green-700);
}

.msg {
  display: flex;
  gap: 11px;
  margin-bottom: 22px;
  max-width: 860px;
}

.msg.user {
  flex-direction: row-reverse;
  margin-left: auto;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  background: var(--green-100);
  color: var(--green-700);
}

.msg.user .avatar {
  background: var(--green-600);
  color: #fff;
}

.bubble-wrap {
  min-width: 0;
  max-width: 100%;
}

.bubble {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 15px;
  font-size: 13.5px;
  line-height: 1.78;
  color: var(--text);
  word-break: break-word;
}

.msg.user .bubble {
  background: var(--green-600);
  color: #fff;
  border-color: var(--green-600);
}

.answer {
  white-space: pre-wrap;
}

.cursor {
  color: var(--green-500);
  animation: blink 1s steps(2) infinite;
  font-size: 12px;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.blocked-tag {
  display: inline-block;
  font-size: 11px;
  background: var(--amber-bg);
  color: var(--amber);
  padding: 2px 7px;
  border-radius: 4px;
  margin-bottom: 7px;
}

.meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 5px;
  padding-left: 2px;
}

/* 来源 */
.sources {
  margin-top: 8px;
}

.src-toggle {
  font-size: 12px;
  color: var(--green-600);
  padding: 3px 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.src-toggle:hover {
  color: var(--green-700);
  text-decoration: underline;
}

.arrow {
  font-size: 9px;
}

.src-list {
  margin-top: 7px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.src-item {
  background: #fff;
  border: 1px solid var(--border);
  border-left: 3px solid var(--green-300);
  border-radius: 6px;
  padding: 9px 12px;
}

.src-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 5px;
  flex-wrap: wrap;
}

.src-idx {
  width: 17px;
  height: 17px;
  border-radius: 4px;
  background: var(--green-100);
  color: var(--green-700);
  font-size: 10.5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.src-title {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text);
}

.src-content {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.65;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 工具调用 */
.tools {
  margin-top: 8px;
  background: #fbfcfb;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  padding: 8px 11px;
}

.tools-title {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 5px;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  padding: 2px 0;
}

.tool-name {
  color: var(--green-700);
  font-weight: 500;
}

.tool-args {
  color: var(--text-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-status {
  flex-shrink: 0;
  font-size: 11px;
}

.tool-status.ok {
  color: var(--green-600);
}

.tool-status.bad {
  color: var(--red);
}

.tool-status.running {
  color: var(--amber);
  animation: pulse 1.1s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}

/* 输入区 */
.composer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: #fff;
  padding: 11px 28px 14px;
}

.composer-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 9px;
}

.mode-switch {
  display: flex;
  background: #f2f5f3;
  border-radius: 7px;
  padding: 2px;
}

.mode-btn {
  padding: 4px 13px;
  font-size: 12px;
  border-radius: 5px;
  color: var(--text-2);
  transition: all 0.15s;
}

.mode-btn.active {
  background: #fff;
  color: var(--green-700);
  font-weight: 500;
  box-shadow: var(--shadow-sm);
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-row .textarea {
  flex: 1;
  min-height: 46px;
  max-height: 140px;
  resize: none;
}

.send-btn {
  height: 46px;
  padding: 0 26px;
  flex-shrink: 0;
}

.composer-warn {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--amber);
  background: var(--amber-bg);
  padding: 6px 10px;
  border-radius: 5px;
}
</style>
