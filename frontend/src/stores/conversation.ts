import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'

type Conversation = Record<string, any>
type Message = Record<string, any>
type Section = Record<string, any>
type Card = Record<string, any>

const idleRun = () => ({ active: false, phase: '', label: '' })

/** Conversation state, persistence and the discussion SSE lifecycle. */
export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversation = ref<Conversation | null>(null)
  const showConversationList = ref(false)
  const showMobileDiscussion = ref(false)
  const messages = ref<Message[]>([])
  const highlightedMessageIds = ref<string[]>([])
  const sideRun = ref(idleRun())
  const proposal = ref<Record<string, any> | null>(null)
  const recommendations = ref<Record<string, any>[]>([])
  const teacherGuidance = ref<Record<string, any>[]>([])
  const streamError = ref('')

  let conversationLoadVersion = 0
  let highlightTimer: ReturnType<typeof setTimeout> | null = null

  function clearMessages() {
    messages.value = []
    sideRun.value = idleRun()
  }

  async function loadSectionConversations(card: Card | null, section: Section | null, preferredConversationId: string | null = null) {
    if (!card || !section) {
      conversations.value = []
      activeConversation.value = null
      clearMessages()
      return
    }
    const next = await request<Conversation[]>(
      `/cards/${card.id}/conversations?sectionId=${encodeURIComponent(section.id)}`,
    )
    conversations.value = next
    const requestedId = preferredConversationId || activeConversation.value?.id
    activeConversation.value = next.find((item) => item.id === requestedId) || next[0] || null
    clearMessages()
    await loadConversationMessages(activeConversation.value)
  }

  async function loadConversationMessages(conversation: Conversation | null) {
    const version = ++conversationLoadVersion
    if (!conversation) {
      clearMessages()
      return
    }
    const stored = await request<Message[]>(`/conversations/${conversation.id}/messages`)
    if (version !== conversationLoadVersion || activeConversation.value?.id !== conversation.id) return
    messages.value = stored.filter((message) => message.visibility !== 'internal').map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
      senderId: message.senderId,
      senderName: message.senderName,
      senderRole: message.senderRole,
    }))
    const activeRun = await request<any>(`/conversations/${conversation.id}/runs/active`)
    if (version !== conversationLoadVersion || activeConversation.value?.id !== conversation.id) return
    if (activeRun?.status === 'expired' || activeRun?.status === 'failed') {
      sideRun.value = idleRun()
      throw new Error(activeRun.errorMessage || '上一次 AI 请求未完成，请重新发送。')
    }
    if (activeRun) {
      sideRun.value = {
        active: true,
        phase: activeRun.phase || 'waiting',
        label: activeRun.phase === 'guiding' ? '主线老师正在总结引导' : 'AI 正在处理中',
      }
      if (!messages.value.some((message) => message.pending)) {
        messages.value.push({
          role: 'assistant', content: '', pending: true,
          senderId: 'side_tutor', senderName: '答疑助教', senderRole: 'assistant',
        })
      }
    } else sideRun.value = idleRun()
  }

  async function sendMessage(text: string, section: Section | null) {
    if (!activeConversation.value || !section || !text.trim() || sideRun.value.active) return
    if (activeConversation.value.sectionId !== section.id) {
      throw new Error('请在该讨论所属的章节中继续提问。')
    }
    sideRun.value = { active: true, phase: 'waiting', label: '正在等待 AI 响应' }
    streamError.value = ''
    messages.value.push({ role: 'user', content: text })
    const assistant: Message = {
      role: 'assistant', content: '', pending: true,
      senderId: 'side_tutor', senderName: '答疑助教', senderRole: 'assistant',
    }
    messages.value.push(assistant)
    const removeAssistant = () => {
      const index = messages.value.findIndex((message) => message === assistant
        || (message.role === 'assistant' && message.pending && !message.content))
      if (index >= 0) messages.value.splice(index, 1)
    }
    try {
      const response = await fetch(`/api/v1/conversations/${activeConversation.value.id}/messages/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ content: text, sectionId: activeConversation.value.sectionId }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body?.error?.message || body?.detail || '无法建立 AI 流式连接')
      }
      if (!response.body) throw new Error('无法建立 AI 流式连接')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          const dataLine = block.split('\n').find((line) => line.startsWith('data:'))
          if (!dataLine) continue
          try {
            const data = JSON.parse(dataLine.slice(5))
            if (block.includes('run.phase') || block.includes('run.started')) {
              sideRun.value = { active: true, phase: data.phase || 'waiting', label: data.label || 'AI 正在处理' }
            }
            if (block.includes('message.started')) {
              assistant.senderId = data.senderId || assistant.senderId
              assistant.senderName = data.senderName || assistant.senderName
              assistant.senderRole = data.senderRole || assistant.senderRole
            }
            if (block.includes('message.delta')) {
              assistant.pending = false
              sideRun.value = { active: true, phase: 'answering', label: '答疑助教正在回答' }
              assistant.content += data.delta || ''
            }
            if (block.includes('related_card.proposed')) {
              proposal.value = data
              recommendations.value = [data, ...recommendations.value.filter((item) => item.proposalId !== data.proposalId)]
            }
            if (block.includes('guidance.updated')) teacherGuidance.value = [...teacherGuidance.value, data]
            if (block.includes('guidance.failed')) streamError.value = `课程导师引导失败：${data.message || '未知错误'}`
            if (block.includes('run.failed')) {
              streamError.value = data.message || 'AI 服务调用失败'
              if (!assistant.content) removeAssistant()
            }
            if (block.includes('run.completed') || block.includes('run.failed')) {
              assistant.pending = false
              sideRun.value = idleRun()
            }
          } catch (error) {
            if (error instanceof SyntaxError) continue
            throw error
          }
        }
        if (done) break
      }
    } catch (error) {
      if (!assistant.content) removeAssistant()
      throw error
    } finally {
      sideRun.value = idleRun()
    }
    return streamError.value
  }

  function selectConversation(item: Conversation | null) {
    activeConversation.value = item
    showConversationList.value = false
    clearMessages()
    return loadConversationMessages(item)
  }

  function highlightMessages(ids: string[]) {
    if (highlightTimer) clearTimeout(highlightTimer)
    highlightedMessageIds.value = ids
    highlightTimer = setTimeout(() => {
      highlightedMessageIds.value = []
      highlightTimer = null
    }, 2200)
  }

  function reset() {
    conversations.value = []
    activeConversation.value = null
    showConversationList.value = false
    clearMessages()
    proposal.value = null
    recommendations.value = []
    highlightedMessageIds.value = []
  }

  return {
    conversations, activeConversation, showConversationList, showMobileDiscussion,
    messages, highlightedMessageIds, sideRun, proposal, recommendations, teacherGuidance,
    streamError,
    loadSectionConversations, loadConversationMessages, sendMessage, selectConversation,
    highlightMessages, clearMessages, reset,
  }
})
