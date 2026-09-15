<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'

const base = '/api/v1'
const goal = ref('')
const history = ref([])
const historyCards = ref({})
const space = ref(null)
const card = ref(null)
const rootCard = ref(null)
const relatedCards = ref([])
const activeSection = ref(0)
const conversations = ref([])
const activeConversation = ref(null)
const messages = ref([])
const input = ref('')
const note = ref('')
const loading = ref(false)
const error = ref('')
const showSettings = ref(false)
const selectedProvider = ref('deepseek')
const apiKey = ref('')
const providerStatus = ref({ activeProvider: 'mock', providers: {} })
const selectedModel = ref('')
const availableModels = ref([])
const selectedModels = ref([])
const selectedDefaultModel = ref('')
const fetchingModels = ref(false)
const editingKey = ref(false)
const proposal = ref(null)
const chatWidth = ref(Math.min(560, Math.max(280, Number(localStorage.getItem('studycenter.chatWidth')) || 360)))
let resizingChat = false
const md = new MarkdownIt({ html: false, breaks: true, linkify: true })

onMounted(() => Promise.all([loadHistory(), loadProviderSettings()]))
onUnmounted(() => stopChatResize())

const section = computed(() => card.value?.sections?.[activeSection.value] || null)
const renderedContent = computed(() => md.render(section.value?.contentMarkdown || '本节内容正在生成。'))
const isRelatedCard = computed(() => card.value?.cardType === 'related')
const keyConfigured = computed(() => Boolean(providerStatus.value.providers?.[selectedProvider.value]))
const homeCards = computed(() => history.value.flatMap((spaceItem) => (
  (historyCards.value[spaceItem.id] || []).map((cardItem) => ({
    card: cardItem,
    space: spaceItem,
  }))
)))

function startChatResize(event) {
  event.preventDefault()
  resizingChat = true
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', resizeChat)
  window.addEventListener('pointerup', stopChatResize)
}

function resizeChat(event) {
  if (!resizingChat) return
  chatWidth.value = Math.min(560, Math.max(280, window.innerWidth - event.clientX - 12))
  localStorage.setItem('studycenter.chatWidth', String(chatWidth.value))
}

function stopChatResize() {
  if (!resizingChat) return
  resizingChat = false
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', resizeChat)
  window.removeEventListener('pointerup', stopChatResize)
}

function adjustChatWidth(delta) {
  chatWidth.value = Math.min(560, Math.max(280, chatWidth.value + delta))
  localStorage.setItem('studycenter.chatWidth', String(chatWidth.value))
}

async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body?.error?.message || body?.detail || '请求失败')
  return body
}

async function openSettings() {
  await loadProviderSettings()
  selectedProvider.value = providerStatus.value.activeProvider === 'mock' ? 'deepseek' : providerStatus.value.activeProvider
  selectedModel.value = providerStatus.value.activeModel || providerStatus.value.models?.[selectedProvider.value]?.[0] || ''
  selectedModels.value = [...(providerStatus.value.models?.[selectedProvider.value] || [])]
  selectedDefaultModel.value = providerStatus.value.activeModel || selectedModels.value[0] || ''
  availableModels.value = [...selectedModels.value]
  apiKey.value = ''
  editingKey.value = false
  showSettings.value = true
}

function changeProvider() {
  availableModels.value = [...(providerStatus.value.models?.[selectedProvider.value] || [])]
  selectedModels.value = [...availableModels.value]
  selectedDefaultModel.value = providerStatus.value.activeProvider === selectedProvider.value
    ? providerStatus.value.activeModel || selectedModels.value[0] || ''
    : selectedModels.value[0] || ''
  apiKey.value = ''
  editingKey.value = false
}

function ensureDefaultModel() {
  if (!selectedModels.value.includes(selectedDefaultModel.value)) {
    selectedDefaultModel.value = selectedModels.value[0] || ''
  }
}

async function loadProviderSettings() {
  try {
    providerStatus.value = await request('/settings/providers')
    selectedModel.value = providerStatus.value.activeModel || ''
  } catch (_) {
    // Keep the page usable with Mock when settings are unavailable.
  }
}

async function fetchModels() {
  if (!apiKey.value.trim()) return
  fetchingModels.value = true
  error.value = ''
  try {
    const body = apiKey.value.trim() ? { apiKey: apiKey.value.trim() } : {}
    const result = await request(`/settings/providers/${selectedProvider.value}/models`, {
      method: 'POST', body: JSON.stringify(body),
    })
    availableModels.value = result.models || []
    selectedModels.value = selectedModels.value.filter((model) => availableModels.value.includes(model))
    ensureDefaultModel()
  } catch (err) { error.value = err.message } finally { fetchingModels.value = false }
}

async function saveProvider() {
  if ((!apiKey.value.trim() && !keyConfigured.value) || !selectedModels.value.length || !selectedDefaultModel.value) return
  loading.value = true
  try {
    providerStatus.value = await request(`/settings/providers/${selectedProvider.value}`, {
      method: 'PUT', body: JSON.stringify({ ...(apiKey.value.trim() ? { apiKey: apiKey.value.trim() } : {}), models: selectedModels.value, defaultModel: selectedDefaultModel.value }),
    })
    selectedModel.value = providerStatus.value.activeModel || ''
    availableModels.value = []
    selectedModels.value = []
    apiKey.value = ''
    editingKey.value = false
    showSettings.value = false
  } catch (err) { error.value = err.message } finally { loading.value = false }
}

async function selectModel() {
  if (!selectedModel.value || providerStatus.value.activeProvider === 'mock') return
  providerStatus.value = await request('/settings/model', { method: 'PUT', body: JSON.stringify({ model: selectedModel.value }) })
}

async function useMock() {
  if (providerStatus.value.activeProvider !== 'mock') {
    await request(`/settings/providers/${providerStatus.value.activeProvider}`, { method: 'DELETE' })
  }
  providerStatus.value = await request('/settings/providers')
}

async function startLearning() {
  if (!goal.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    if (selectedModel.value && providerStatus.value.activeProvider !== 'mock') await selectModel()
    space.value = await request('/learning-spaces', {
      method: 'POST',
      body: JSON.stringify({ title: goal.value.trim(), learningGoal: goal.value.trim() }),
    })
    card.value = await request(`/cards/${space.value.rootCardId}`)
    rootCard.value = card.value
    relatedCards.value = (await request(`/learning-spaces/${space.value.id}/cards`)).filter((item) => item.cardType === 'related')
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
    const entries = await Promise.all(history.value.map(async (item) => {
      try {
        return [item.id, await request(`/learning-spaces/${item.id}/cards`)]
      } catch (_) {
        return [item.id, []]
      }
    }))
    historyCards.value = Object.fromEntries(entries)
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
    relatedCards.value = (await request(`/learning-spaces/${item.id}/cards`)).filter((item) => item.cardType === 'related')
    activeSection.value = 0
    conversations.value = await request(`/cards/${card.value.id}/conversations`)
    activeConversation.value = conversations.value[0] || null
    await loadConversationMessages(activeConversation.value)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function goHome() {
  space.value = null
  card.value = null
  rootCard.value = null
  relatedCards.value = []
  activeConversation.value = null
  conversations.value = []
  messages.value = []
  proposal.value = null
  error.value = ''
  loadHistory()
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

async function loadConversationMessages(conversation) {
  if (!conversation) {
    messages.value = []
    return
  }
  const stored = await request(`/conversations/${conversation.id}/messages`)
  messages.value = stored.map((message) => ({ role: message.role, content: message.content }))
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
    relatedCards.value = [...relatedCards.value.filter((item) => item.id !== card.value.id), card.value]
    activeSection.value = 0
    proposal.value = null
  } catch (err) { error.value = err.message } finally { loading.value = false }
}

async function openCard(target) {
  card.value = target
  activeSection.value = 0
  conversations.value = await request(`/cards/${target.id}/conversations`)
  activeConversation.value = conversations.value[0] || null
  await loadConversationMessages(activeConversation.value)
}

async function openHistoryCard(spaceItem, target) {
  await openHistory(spaceItem)
  await openCard(target)
}

function openHomeCard(item) {
  if (item.card.cardType === 'root') {
    openHistory(item.space)
  } else {
    openHistoryCard(item.space, item.card)
  }
}

function returnToMain() {
  if (!rootCard.value) return
  openCard(rootCard.value)
}

async function selectConversation(item) {
  activeConversation.value = item
  await loadConversationMessages(item)
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
      <button class="brand" @click="goHome" title="返回首页">Study<span>Center</span></button>
      <div v-if="space" class="crumb">学习空间 / {{ card?.title }} / {{ section?.title || '未开始' }}</div>
      <div class="status">{{ loading ? 'AI 正在准备内容…' : `当前模型：${providerStatus.activeProvider}` }}</div>
      <button class="settings-button" @click="openSettings">设置</button>
    </header>

    <section v-if="!space" class="welcome">
      <p class="eyebrow">AI LEARNING SPACE</p>
      <h1>从一个问题，开始一条属于你的学习路径。</h1>
      <p class="lead">主 Agent 会先生成一张知识卡。之后的提问、旁支和笔记，都围绕它展开。</p>
      <form @submit.prevent="startLearning" class="start-form">
        <textarea v-model="goal" placeholder="例如：我想系统理解 Kubernetes 容器隔离，并能看懂 Namespace 和 cgroups 的关系" autofocus></textarea>
        <div class="start-options"><label>模型<select v-model="selectedModel" :disabled="providerStatus.activeProvider === 'mock'"><option v-if="providerStatus.activeProvider === 'mock'" value="">Mock（请先配置模型）</option><option v-for="model in (providerStatus.models?.[providerStatus.activeProvider] || [])" :key="model" :value="model">{{ model }}</option></select></label><button :disabled="loading">创建知识卡</button></div>
      </form>
      <div v-if="homeCards.length" class="history">
        <div class="history-title">我的知识卡</div>
        <button v-for="item in homeCards" :key="item.card.id" class="history-item" @click="openHomeCard(item)">
          <span>{{ item.card.title }}</span>
          <small>{{ new Date(item.space.createdAt).toLocaleDateString('zh-CN') }} · 开始学习 →</small>
        </button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <div v-if="showSettings" class="modal-backdrop" @click.self="showSettings = false">
      <section class="settings-modal">
        <div class="settings-head"><div><div class="panel-title">模型设置</div><p>Key 会在后端加密保存，前端不会保存明文。</p></div><button @click="showSettings = false">×</button></div>
        <label>Provider<select v-model="selectedProvider" @change="changeProvider"><option value="deepseek">DeepSeek</option><option value="opencode">OpenCode Zen</option><option value="openrouter">OpenRouter</option></select></label>
        <label>API Key<div class="key-row"><input v-if="editingKey || !keyConfigured" v-model="apiKey" type="password" placeholder="输入 API Key" autocomplete="off" /><div v-else class="masked-key">*****</div><button v-if="keyConfigured && !editingKey" class="edit-key" @click="editingKey = true">编辑</button><button :disabled="fetchingModels || (!apiKey && !keyConfigured)" @click="fetchModels">{{ fetchingModels ? '获取中…' : '获取模型' }}</button></div></label>
        <div v-if="availableModels.length" class="model-catalog"><div class="catalog-title">选择模型，并指定一个默认模型</div><label v-for="model in availableModels" :key="model" class="model-check"><input v-model="selectedModels" type="checkbox" :value="model" @change="ensureDefaultModel" /><span>{{ model }}</span><input v-model="selectedDefaultModel" type="radio" name="default-model" :value="model" :disabled="!selectedModels.includes(model)" /><em>默认</em></label></div>
        <div class="provider-actions"><button class="secondary" @click="useMock">切换 Mock</button><button class="primary" :disabled="loading || ((!apiKey && !keyConfigured) || !selectedModels.length || !selectedDefaultModel)" @click="saveProvider">保存并使用</button></div>
        <div class="provider-hint">已配置：{{ Object.entries(providerStatus.providers).filter(([, value]) => value).map(([key]) => key).join('、') || '暂无' }}</div>
      </section>
    </div>

    <section v-if="space && !card" class="loading-state">
      正在恢复学习空间…
    </section>

    <section v-if="space && card" class="workspace" :style="{ '--chat-width': `${chatWidth}px` }">
      <aside class="sidebar panel">
        <div class="panel-title">知识结构</div>
        <div class="tree-label">主知识卡</div>
        <button v-for="(item, index) in card.sections" :key="item.id" class="tree-item" :class="{ active: index === activeSection }" @click="activeSection = index">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>{{ item.title }}
        </button>
        <div class="tree-label related">关联知识卡</div>
        <button v-for="related in relatedCards" :key="related.id" class="related-card" :class="{ active: card.id === related.id }" @click="openCard(related)">
          <span>↳</span>{{ related.title }}
        </button>
        <div v-if="!relatedCards.length" class="empty-related">从旁支问题中生成<br />新的学习分支</div>
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

      <div class="resize-handle" role="separator" aria-label="调整会话宽度" :aria-valuenow="chatWidth" aria-valuemin="280" aria-valuemax="560" tabindex="0" @pointerdown="startChatResize" @keydown.left.prevent="adjustChatWidth(20)" @keydown.right.prevent="adjustChatWidth(-20)"></div>

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
          <textarea v-model="input" placeholder="问问当前内容…"></textarea>
          <button>发送 ↗</button>
        </form>
      </aside>
    </section>
  </main>
</template>
