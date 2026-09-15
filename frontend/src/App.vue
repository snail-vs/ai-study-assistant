<script setup>
import { computed, onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'

const base = '/api/v1'
const goal = ref('')
const history = ref([])
const space = ref(null)
const card = ref(null)
const rootCard = ref(null)
const activeSection = ref(0)
const conversations = ref([])
const activeConversation = ref(null)
const messages = ref([])
const input = ref('')
const note = ref('')
const loading = ref(false)
const error = ref('')
const proposal = ref(null)
const md = new MarkdownIt({ html: false, breaks: true, linkify: true })

onMounted(loadHistory)

const section = computed(() => card.value?.sections?.[activeSection.value] || null)
const renderedContent = computed(() => md.render(section.value?.contentMarkdown || '本节内容正在生成。'))
const isRelatedCard = computed(() => card.value?.cardType === 'related')

async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body?.error?.message || body?.detail || '请求失败')
  return body
}

async function startLearning() {
  if (!goal.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    space.value = await request('/learning-spaces', {
      method: 'POST',
      body: JSON.stringify({ title: goal.value.trim(), learningGoal: goal.value.trim() }),
    })
    card.value = await request(`/cards/${space.value.rootCardId}`)
    rootCard.value = card.value
    const main = await request(`/cards/${card.value.id}/conversations`, {
      method: 'POST',
      body: JSON.stringify({ conversationType: 'main', title: '主线导师', rootQuestion: goal.value }),
    })
    conversations.value = [main]
    activeConversation.value = main
    messages.value = []
    await loadHistory()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  try {
    history.value = (await request('/learning-spaces')).items || []
  } catch (_) {
    // The empty state remains usable if the API is temporarily unavailable.
  }
}

async function openHistory(item) {
  loading.value = true
  error.value = ''
  try {
    space.value = item
    card.value = await request(`/cards/${item.rootCardId}`)
    rootCard.value = card.value
    activeSection.value = 0
    conversations.value = await request(`/cards/${card.value.id}/conversations`)
    activeConversation.value = conversations.value[0] || null
    messages.value = []
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function openSideConversation() {
  if (!card.value || !input.value.trim()) return
  const question = input.value.trim()
  const side = await request(`/cards/${card.value.id}/conversations`, {
    method: 'POST',
    body: JSON.stringify({
      conversationType: 'side',
      sectionId: section.value?.id || null,
      title: question.slice(0, 32),
      rootQuestion: question,
    }),
  })
  conversations.value.push(side)
  activeConversation.value = side
  messages.value = []
  await sendMessage(question)
}

async function sendMessage(text = input.value) {
  if (!activeConversation.value || !text.trim()) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  const assistant = { role: 'assistant', content: '' }
  messages.value.push(assistant)
  const response = await fetch(`${base}/conversations/${activeConversation.value.id}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: text }),
  })
  if (!response.ok || !response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    for (const block of decoder.decode(value).split('\n\n')) {
      const dataLine = block.split('\n').find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      try {
        const data = JSON.parse(dataLine.slice(5))
        if (block.includes('message.delta')) assistant.content += data.delta || ''
        if (block.includes('related_card.proposed')) proposal.value = data
      } catch (_) {}
    }
  }
}

async function acceptProposal() {
  if (!proposal.value) return
  loading.value = true
  try {
    card.value = await request(`/proposals/${proposal.value.proposalId}/accept`, { method: 'POST' })
    activeSection.value = 0
    proposal.value = null
  } catch (err) { error.value = err.message } finally { loading.value = false }
}

function returnToMain() {
  if (!rootCard.value) return
  card.value = rootCard.value
  activeSection.value = 0
}

async function selectConversation(item) {
  activeConversation.value = item
  messages.value = []
}

async function saveNote() {
  if (!card.value || !note.value.trim()) return
  await request(`/cards/${card.value.id}/notes`, {
    method: 'POST',
    body: JSON.stringify({ sectionId: section.value?.id || null, content: note.value.trim(), sourceType: 'manual' }),
  })
  note.value = ''
}
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div class="brand">Study<span>Center</span></div>
      <div v-if="space" class="crumb">学习空间 / {{ card?.title }} / {{ section?.title || '未开始' }}</div>
      <div class="status">{{ loading ? 'AI 正在准备内容…' : '本地 Mock Provider' }}</div>
    </header>

    <section v-if="!space" class="welcome">
      <p class="eyebrow">AI LEARNING SPACE</p>
      <h1>从一个问题，开始一条属于你的学习路径。</h1>
      <p class="lead">主 Agent 会先生成一张知识卡。之后的提问、旁支和笔记，都围绕它展开。</p>
      <form @submit.prevent="startLearning" class="start-form">
        <input v-model="goal" placeholder="例如：我想理解 Kubernetes 容器隔离" autofocus />
        <button :disabled="loading">创建知识卡</button>
      </form>
      <div v-if="history.length" class="history">
        <div class="history-title">最近的学习空间</div>
        <button v-for="item in history" :key="item.id" class="history-item" @click="openHistory(item)">
          <span>{{ item.title }}</span>
          <small>{{ new Date(item.createdAt).toLocaleDateString('zh-CN') }} · 继续学习 →</small>
        </button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <section v-else class="workspace">
      <aside class="sidebar panel">
        <div class="panel-title">知识结构</div>
        <div class="tree-label">主知识卡</div>
        <button v-for="(item, index) in card.sections" :key="item.id" class="tree-item" :class="{ active: index === activeSection }" @click="activeSection = index">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>{{ item.title }}
        </button>
        <div class="tree-label related">关联知识卡</div>
        <div class="empty-related">从旁支问题中生成<br />新的学习分支</div>
      </aside>

      <section class="board panel">
        <div class="board-meta"><span>第 {{ activeSection + 1 }} 节</span><span>Markdown 白板</span></div>
        <button v-if="isRelatedCard" class="back-main" @click="returnToMain">← 返回主知识卡</button>
        <article class="markdown">
          <h2>{{ section?.title }}</h2>
          <div class="content" v-html="renderedContent"></div>
        </article>
        <div class="notes">
          <div class="note-title">✦ 我的笔记</div>
          <textarea v-model="note" placeholder="记录这节课中你觉得重要的内容…"></textarea>
          <button class="save-note" @click="saveNote">保存笔记</button>
        </div>
      </section>

      <aside class="chat panel">
        <div class="chat-head"><div class="panel-title">学习对话</div><button class="new-chat" @click="activeConversation = null; messages = []">＋ 新旁支</button></div>
        <div class="conversation-list">
          <button v-for="item in conversations" :key="item.id" @click="selectConversation(item)" :class="{ selected: activeConversation?.id === item.id }">
            <small>{{ item.conversationType === 'main' ? '主线' : '旁支' }}</small>{{ item.title }}
          </button>
        </div>
        <div class="messages">
          <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role"><span>{{ message.role === 'user' ? '你' : 'AI' }}</span>{{ message.content }}</div>
          <div v-if="!messages.length" class="chat-empty">从当前章节提出一个问题，开始旁支探索。</div>
          <div v-if="proposal" class="proposal-card">
            <div class="proposal-kicker">检测到一个知识断层</div>
            <strong>{{ proposal.title }}</strong>
            <p>{{ proposal.reason }}</p>
            <button @click="acceptProposal">生成关联知识卡 →</button>
          </div>
        </div>
        <form class="composer" @submit.prevent="activeConversation ? sendMessage() : openSideConversation()">
          <textarea v-model="input" placeholder="问问当前内容…" @keydown.enter.exact.prevent="activeConversation ? sendMessage() : openSideConversation()"></textarea>
          <button>发送 ↗</button>
        </form>
      </aside>
    </section>
  </main>
</template>
