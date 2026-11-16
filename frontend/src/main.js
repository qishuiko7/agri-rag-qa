import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'

import Home from './views/Home.vue'
import Knowledge from './views/Knowledge.vue'
import Vector from './views/Vector.vue'
import Chat from './views/Chat.vue'
import History from './views/History.vue'
import Settings from './views/Settings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home, meta: { title: '系统首页', sub: '运行概览与功能导航' } },
    { path: '/knowledge', name: 'knowledge', component: Knowledge, meta: { title: '知识库管理', sub: '语料导入、预览与分类归档' } },
    { path: '/vector', name: 'vector', component: Vector, meta: { title: '向量库构建', sub: '切片、向量化与入库' } },
    { path: '/chat', name: 'chat', component: Chat, meta: { title: '智能问答', sub: 'RAG 检索增强问答' } },
    { path: '/history', name: 'history', component: History, meta: { title: '历史记录', sub: '问答检索、统计与导出' } },
    { path: '/settings', name: 'settings', component: Settings, meta: { title: '系统设置', sub: '模型接口与运行参数' } },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

createApp(App).use(router).mount('#app')
