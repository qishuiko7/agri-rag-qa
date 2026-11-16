<template>
  <div>
    <div class="two-col">
      <!-- 模型接口 -->
      <div class="card">
        <div class="card-head">
          <h3>模型接口</h3>
          <span class="hint">修改后需重启服务生效</span>
        </div>

        <div class="field">
          <label>对话模型提供方</label>
          <select v-model="form.llm_provider" class="select">
            <option value="dashscope">阿里云百炼（DashScope）</option>
            <option value="zhipu">智谱 AI</option>
            <option value="mock">Mock 演示模式</option>
          </select>
        </div>

        <div class="field">
          <label>对话模型名称</label>
          <input v-model="form.llm_model" class="input" placeholder="qwen-plus" />
          <div class="desc">百炼常用：qwen-plus / qwen-turbo / qwen-max；智谱常用：glm-4-flash / glm-4-plus</div>
        </div>

        <div class="field">
          <label>百炼 API Key</label>
          <input v-model="form.dashscope_api_key" class="input mono" placeholder="sk-..." />
          <div class="desc">
            当前：{{ cfg.has_dashscope_key ? cfg.dashscope_api_key : '未配置' }} ·
            <a href="https://bailian.console.aliyun.com/" target="_blank" rel="noreferrer">控制台</a>
          </div>
        </div>

        <div class="field">
          <label>智谱 API Key</label>
          <input v-model="form.zhipu_api_key" class="input mono" placeholder="可选" />
          <div class="desc">
            当前：{{ cfg.has_zhipu_key ? cfg.zhipu_api_key : '未配置' }} ·
            <a href="https://bigmodel.cn/" target="_blank" rel="noreferrer">控制台</a>
          </div>
        </div>

        <div class="field">
          <label>嵌入模型提供方</label>
          <select v-model="form.embedding_provider" class="select">
            <option value="dashscope">阿里云百炼（text-embedding-v3）</option>
            <option value="zhipu">智谱（embedding-3）</option>
            <option value="mock">Mock（无真实语义）</option>
          </select>
          <div class="desc">切换嵌入模型后必须重新构建向量库，否则维度不匹配。</div>
        </div>

        <div class="field">
          <label>嵌入模型名称</label>
          <input v-model="form.embedding_model" class="input" placeholder="text-embedding-v3" />
        </div>

        <div class="test-row">
          <button class="btn ghost sm" @click="testLlm" :disabled="testing.llm">
            {{ testing.llm ? '测试中…' : '测试对话模型' }}
          </button>
          <button class="btn ghost sm" @click="testEmb" :disabled="testing.emb">
            {{ testing.emb ? '测试中…' : '测试嵌入模型' }}
          </button>
        </div>
        <div v-if="testResult" class="test-result" :class="{ bad: !testResult.ok }">
          {{ testResult.text }}
        </div>
      </div>

      <!-- RAG 参数 -->
      <div class="card">
        <div class="card-head">
          <h3>检索与运行参数</h3>
          <span class="hint">保存后立即生效</span>
        </div>

        <div class="field">
          <label>切片长度 chunk_size</label>
          <input v-model.number="form.chunk_size" type="number" class="input" min="100" max="2000" />
          <div class="desc">文档建议 500。修改后需重新构建向量库。</div>
        </div>

        <div class="field">
          <label>切片重叠 chunk_overlap</label>
          <input v-model.number="form.chunk_overlap" type="number" class="input" min="0" max="500" />
          <div class="desc">文档建议 50。</div>
        </div>

        <div class="field">
          <label>检索召回条数 top_k</label>
          <input v-model.number="form.top_k" type="number" class="input" min="1" max="20" />
          <div class="desc">文档建议 3~5。条数越多上下文越全，但耗时与 token 消耗增加。</div>
        </div>

        <div class="field">
          <label>多轮记忆轮数</label>
          <input v-model.number="form.memory_rounds" type="number" class="input" min="0" max="20" />
          <div class="desc">文档建议 5。仅保留最近 N 轮问答作为上下文。</div>
        </div>

        <button class="btn block mt12" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存设置' }}
        </button>

        <div class="hint-box mt12">
          <strong>配置文件位置</strong>
          <span class="mono small">{{ cfg.env_path }}</span>
        </div>
      </div>
    </div>

    <!-- 当前生效状态 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>当前生效配置</h3>
        <button class="btn ghost sm" @click="load">刷新</button>
      </div>
      <div class="kv-grid">
        <div class="kv"><span>对话模型</span><b>{{ cfg.llm_provider }} / {{ cfg.llm_model }}</b></div>
        <div class="kv"><span>嵌入模型</span><b>{{ cfg.embedding_provider }} / {{ cfg.embedding_model }}</b></div>
        <div class="kv"><span>向量维度</span><b>{{ cfg.embedding_dim }}</b></div>
        <div class="kv"><span>Collection</span><b class="mono">{{ cfg.collection }}</b></div>
        <div class="kv"><span>切片参数</span><b>{{ cfg.chunk_size }} / {{ cfg.chunk_overlap }}</b></div>
        <div class="kv"><span>召回条数</span><b>{{ cfg.top_k }}</b></div>
        <div class="kv"><span>记忆轮数</span><b>{{ cfg.memory_rounds }}</b></div>
        <div class="kv"><span>批处理大小</span><b>{{ cfg.batch_size }}</b></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const notify = inject('notify')
const refreshStatus = inject('refreshStatus')

const cfg = reactive({})
const form = reactive({
  llm_provider: 'mock',
  llm_model: 'qwen-plus',
  embedding_provider: 'mock',
  embedding_model: 'text-embedding-v3',
  dashscope_api_key: '',
  zhipu_api_key: '',
  chunk_size: 500,
  chunk_overlap: 50,
  top_k: 5,
  memory_rounds: 5,
})

const saving = ref(false)
const testing = reactive({ llm: false, emb: false })
const testResult = ref(null)

async function load() {
  try {
    const data = await api.getSettings()
    Object.assign(cfg, data)
    Object.assign(form, {
      llm_provider: data.llm_provider,
      llm_model: data.llm_model,
      embedding_provider: data.embedding_provider,
      embedding_model: data.embedding_model,
      dashscope_api_key: '',
      zhipu_api_key: '',
      chunk_size: data.chunk_size,
      chunk_overlap: data.chunk_overlap,
      top_k: data.top_k,
      memory_rounds: data.memory_rounds,
    })
  } catch (e) {
    notify('读取配置失败：' + e.message, 'error')
  }
}

async function save() {
  saving.value = true
  try {
    const payload = { ...form }
    // 空密钥不提交，避免覆盖已保存的值
    if (!payload.dashscope_api_key) delete payload.dashscope_api_key
    if (!payload.zhipu_api_key) delete payload.zhipu_api_key

    const res = await api.saveSettings(payload)
    notify(res.message || '已保存')
    await Promise.all([load(), refreshStatus()])
  } catch (e) {
    notify('保存失败：' + e.message, 'error')
  } finally {
    saving.value = false
  }
}

async function testLlm() {
  testing.llm = true
  testResult.value = null
  try {
    const res = await api.testModel()
    testResult.value = res.ok
      ? { ok: true, text: `对话模型连通正常：${res.provider} / ${res.model}，返回「${res.reply}」` }
      : { ok: false, text: `对话模型测试失败：${res.error}` }
  } catch (e) {
    testResult.value = { ok: false, text: '测试请求失败：' + e.message }
  } finally {
    testing.llm = false
  }
}

async function testEmb() {
  testing.emb = true
  testResult.value = null
  try {
    const res = await api.testEmbedding()
    testResult.value = res.ok
      ? { ok: true, text: `嵌入模型连通正常：${res.provider} / ${res.model}，维度 ${res.dim}` }
      : { ok: false, text: `嵌入模型测试失败：${res.error}` }
  } catch (e) {
    testResult.value = { ok: false, text: '测试请求失败：' + e.message }
  } finally {
    testing.emb = false
  }
}

onMounted(load)
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

.test-row {
  display: flex;
  gap: 9px;
  margin-top: 4px;
}

.test-result {
  margin-top: 11px;
  font-size: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--green-50);
  border: 1px solid var(--green-100);
  color: var(--green-700);
  line-height: 1.65;
  word-break: break-all;
}

.test-result.bad {
  background: var(--red-bg);
  border-color: #f5d5d2;
  color: var(--red);
}

.hint-box {
  font-size: 11.5px;
  color: var(--text-2);
  background: #fafcfb;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  line-height: 1.7;
  word-break: break-all;
}

.hint-box strong {
  display: block;
  color: var(--text);
  margin-bottom: 2px;
  font-size: 12px;
}

.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 10px;
}

.kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #fafcfb;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  gap: 10px;
}

.kv span {
  color: var(--text-muted);
}

.kv b {
  color: var(--text);
  font-weight: 500;
  text-align: right;
  word-break: break-all;
}

@media (max-width: 1100px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
