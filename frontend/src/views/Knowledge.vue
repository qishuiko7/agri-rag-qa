<template>
  <div>
    <!-- 统计 -->
    <div class="stat-grid">
      <div class="stat">
        <div class="label">文档总数</div>
        <div class="value">{{ stats.total || 0 }}<small>篇</small></div>
      </div>
      <div class="stat">
        <div class="label">总字数</div>
        <div class="value">{{ fmtNum(stats.total_chars) }}<small>字</small></div>
      </div>
      <div class="stat">
        <div class="label">异常文件</div>
        <div class="value" :style="{ color: stats.abnormal ? 'var(--red)' : '' }">
          {{ stats.abnormal || 0 }}<small>个</small>
        </div>
      </div>
      <div class="stat">
        <div class="label">分类数量</div>
        <div class="value">{{ Object.keys(stats.by_category || {}).length }}<small>类</small></div>
      </div>
    </div>

    <!-- 上传区 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>导入语料</h3>
        <span class="hint">支持 TXT / MD / PDF / CSV，单文件 ≤ 20MB，可多选</span>
      </div>

      <div
        class="dropzone"
        :class="{ dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
        @click="$refs.fileInput.click()"
      >
        <div class="dz-icon">⇪</div>
        <div class="dz-text">
          {{ dragging ? '松开鼠标即可导入' : '点击选择文件，或把文件拖到这里' }}
        </div>
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".txt,.md,.pdf,.csv"
          style="display: none"
          @change="onPick"
        />
      </div>

      <div class="upload-row">
        <div class="field" style="margin: 0; max-width: 220px">
          <label>归档分类</label>
          <select v-model="uploadCategory" class="select">
            <option v-for="(name, key) in categories" :key="key" :value="key">{{ name }}</option>
          </select>
        </div>
        <div v-if="pendingFiles.length" class="pending">
          已选 {{ pendingFiles.length }} 个文件
          <button class="btn sm" @click="doUpload" :disabled="uploading">
            {{ uploading ? '导入中…' : '开始导入' }}
          </button>
          <button class="btn ghost sm" @click="pendingFiles = []">取消</button>
        </div>
      </div>
    </div>

    <!-- 文档列表 -->
    <div class="card mt16">
      <div class="card-head">
        <h3>文档列表</h3>
        <div class="filters">
          <select v-model="filterCategory" class="select sm" @change="loadDocs">
            <option value="">全部分类</option>
            <option v-for="(name, key) in categories" :key="key" :value="key">{{ name }}</option>
          </select>
          <input
            v-model="keyword"
            class="input sm"
            placeholder="搜索文件名"
            @input="debouncedLoad"
          />
          <label class="check">
            <input type="checkbox" v-model="onlyAbnormal" @change="loadDocs" />
            仅看异常
          </label>
        </div>
      </div>

      <div v-if="selected.length" class="bulk-bar">
        已选 {{ selected.length }} 项
        <select v-model="moveTarget" class="select sm">
          <option value="">移动到分类…</option>
          <option v-for="(name, key) in categories" :key="key" :value="key">{{ name }}</option>
        </select>
        <button class="btn sm" :disabled="!moveTarget" @click="doMove">移动</button>
        <button class="btn danger sm" @click="doDelete">删除</button>
        <button class="btn ghost sm" @click="selected = []">取消选择</button>
      </div>

      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!docs.length" class="empty">
        <span class="icon">▤</span>
        暂无文档，先导入一些农业语料吧
      </div>

      <table v-else class="table">
        <thead>
          <tr>
            <th style="width: 34px">
              <input type="checkbox" :checked="allSelected" @change="toggleAll" />
            </th>
            <th>文件名</th>
            <th style="width: 100px">分类</th>
            <th style="width: 80px">字数</th>
            <th style="width: 80px">大小</th>
            <th style="width: 76px">状态</th>
            <th style="width: 110px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in docs" :key="d.category + d.name" :class="{ abnormal: d.abnormal }">
            <td>
              <input type="checkbox" :value="d.name" v-model="selected" />
            </td>
            <td>
              <div class="name" :title="d.name">{{ d.name }}</div>
            </td>
            <td><span class="tag" :class="d.category">{{ d.category_name }}</span></td>
            <td class="mono small">{{ d.chars ? d.chars.toLocaleString() : '—' }}</td>
            <td class="mono small">{{ fmtSize(d.size) }}</td>
            <td>
              <span v-if="d.abnormal" class="tag warn" :title="d.abnormal_reason">异常</span>
              <span v-else class="tag gray">正常</span>
            </td>
            <td>
              <button class="link-btn" @click="preview(d)">预览</button>
              <button class="link-btn danger" @click="deleteOne(d)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 预览弹窗 -->
    <div v-if="previewDoc" class="modal-mask" @click.self="previewDoc = null">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ previewDoc.name }}</h3>
          <button class="close-x" @click="previewDoc = null">×</button>
        </div>
        <div class="modal-body">
          <div class="preview-meta">
            <span class="tag" :class="previewDoc.category">{{ previewDoc.category_name }}</span>
            <span class="muted small">{{ previewDoc.chars.toLocaleString() }} 字 · {{ fmtSize(previewDoc.size) }}</span>
          </div>
          <div v-if="previewMeta.title" class="preview-info">
            <div v-if="previewMeta.title"><b>标题</b>{{ previewMeta.title }}</div>
            <div v-if="previewMeta.column"><b>栏目</b>{{ previewMeta.column }}
              <span v-if="previewMeta.publish_date">· {{ previewMeta.publish_date }}</span>
            </div>
            <div v-if="previewMeta.origin" class="mono"><b>来源</b>{{ previewMeta.origin }}</div>
          </div>
          <pre class="preview-text">{{ previewContent }}</pre>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" @click="previewDoc = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const notify = inject('notify')

const stats = reactive({ total: 0, total_chars: 0, abnormal: 0, by_category: {}, categories: {} })
const docs = ref([])
const categories = ref({})
const loading = ref(false)
const keyword = ref('')
const filterCategory = ref('')
const onlyAbnormal = ref(false)
const selected = ref([])
const moveTarget = ref('')

const pendingFiles = ref([])
const uploadCategory = ref('general')
const uploading = ref(false)
const dragging = ref(false)

const previewDoc = ref(null)
const previewContent = ref('')
const previewMeta = ref({})

const allSelected = computed(() => docs.value.length > 0 && selected.value.length === docs.value.length)

function fmtNum(n) {
  if (!n) return '0'
  return n >= 10000 ? (n / 10000).toFixed(1) + ' 万' : n.toLocaleString()
}

function fmtSize(b) {
  if (!b) return '0'
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}

async function loadStats() {
  try {
    const s = await api.kbStats()
    Object.assign(stats, s)
    categories.value = s.categories || {}
  } catch (e) {
    notify('读取统计失败：' + e.message, 'error')
  }
}

async function loadDocs() {
  loading.value = true
  selected.value = []
  try {
    const res = await api.kbDocuments({
      category: filterCategory.value,
      keyword: keyword.value,
      only_abnormal: onlyAbnormal.value,
    })
    docs.value = res.items
  } catch (e) {
    notify('读取文档失败：' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(loadDocs, 300)
}

function toggleAll(e) {
  selected.value = e.target.checked ? docs.value.map((d) => d.name) : []
}

// ---------- 上传 ----------
function onPick(e) {
  pendingFiles.value = Array.from(e.target.files || [])
  e.target.value = ''
}

function onDrop(e) {
  dragging.value = false
  const files = Array.from(e.dataTransfer.files || [])
  if (files.length) pendingFiles.value = files
}

async function doUpload() {
  if (!pendingFiles.value.length) return
  uploading.value = true
  const fd = new FormData()
  pendingFiles.value.forEach((f) => fd.append('files', f))
  try {
    const results = await api.kbUpload(fd, uploadCategory.value)
    const ok = results.filter((r) => r.ok).length
    const fail = results.filter((r) => !r.ok)
    notify(`导入完成：成功 ${ok} 个${fail.length ? `，失败 ${fail.length} 个` : ''}`,
      fail.length ? 'warn' : 'info')
    pendingFiles.value = []
    await Promise.all([loadStats(), loadDocs()])
  } catch (e) {
    notify('上传失败：' + e.message, 'error')
  } finally {
    uploading.value = false
  }
}

// ---------- 操作 ----------
async function preview(d) {
  try {
    const res = await api.kbPreview(d.name, d.category)
    previewDoc.value = d
    previewContent.value = res.content
    previewMeta.value = res.meta || {}
  } catch (e) {
    notify('预览失败：' + e.message, 'error')
  }
}

async function deleteOne(d) {
  if (!confirm(`确定删除「${d.name}」？该操作不可恢复。`)) return
  try {
    await api.kbDelete([d.name])
    notify('已删除 1 个文档')
    await Promise.all([loadStats(), loadDocs()])
  } catch (e) {
    notify('删除失败：' + e.message, 'error')
  }
}

async function doDelete() {
  if (!confirm(`确定删除选中的 ${selected.value.length} 个文档？`)) return
  try {
    const res = await api.kbDelete(selected.value)
    notify(`已删除 ${res.removed} 个文档`)
    await Promise.all([loadStats(), loadDocs()])
  } catch (e) {
    notify('删除失败：' + e.message, 'error')
  }
}

async function doMove() {
  if (!moveTarget.value) return
  try {
    const res = await api.kbReclassify(selected.value, moveTarget.value)
    notify(`已移动 ${res.moved} 个文档到「${categories.value[moveTarget.value]}」`)
    moveTarget.value = ''
    await Promise.all([loadStats(), loadDocs()])
  } catch (e) {
    notify('移动失败：' + e.message, 'error')
  }
}

onMounted(async () => {
  await loadStats()
  uploadCategory.value = Object.keys(categories.value)[0] || 'general'
  await loadDocs()
})
</script>

<style scoped>
.dropzone {
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius);
  padding: 26px;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
  background: #fcfdfc;
}

.dropzone:hover,
.dropzone.dragging {
  border-color: var(--green-500);
  background: var(--green-50);
}

.dz-icon {
  font-size: 22px;
  color: var(--green-500);
  margin-bottom: 6px;
}

.dz-text {
  font-size: 12.5px;
  color: var(--text-2);
}

.upload-row {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.pending {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--green-700);
  background: var(--green-50);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--green-100);
}

.filters {
  display: flex;
  gap: 8px;
  align-items: center;
}

.select.sm,
.input.sm {
  padding: 5px 9px;
  font-size: 12.5px;
  width: auto;
}

.input.sm {
  width: 160px;
}

.check {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  cursor: pointer;
}

.bulk-bar {
  display: flex;
  align-items: center;
  gap: 9px;
  background: var(--green-50);
  border: 1px solid var(--green-100);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 12.5px;
  color: var(--green-700);
}

tr.abnormal td {
  background: #fffbf3;
}

.link-btn {
  font-size: 12px;
  color: var(--green-600);
  padding: 0 3px;
}

.link-btn:hover {
  text-decoration: underline;
}

.link-btn.danger {
  color: var(--red);
}

.preview-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 11px;
}

.preview-info {
  background: #fafcfb;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  margin-bottom: 11px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.85;
  word-break: break-all;
}

.preview-info b {
  display: inline-block;
  min-width: 40px;
  color: var(--text-muted);
  font-weight: 400;
  margin-right: 6px;
}

.preview-text {
  background: #fafcfb;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  font-size: 12.5px;
  line-height: 1.85;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  margin: 0;
  max-height: 52vh;
  overflow-y: auto;
  color: var(--text-2);
}
</style>
