import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { request } from '../api/client'

type Conversation = Record<string, any>
type Message = Record<string, any>
type Section = Record<string, any>
type Card = Record<string, any>
type StudyAssistEventHandler = (event: string, data: Record<string, any>) => void

const idleRun = () => ({ active: false, phase: '', label: '' })

async function createStreamError(response: Response): Promise<Error> {
  const raw = await response.text().catch(() => '')
  let body: any = null
  try {
    body = raw ? JSON.parse(raw) : null
  } catch {
    // Reverse proxies often return an HTML/plain-text error instead of JSON.
  }
  const message = body?.error?.message || body?.detail
  const requestId = response.headers.get('x-request-id')
  const status = response.status ? `HTTP ${response.status}` : '网络错误'
  const suffix = requestId ? `（请求 ID: ${requestId}）` : ''
  if (message) return new Error(`${message} [${status}]${suffix}`)
  return new Error(`AI 流式连接失败 [${status}]${suffix}`)
}

/** Conversation state, persistence and the discussion SSE lifecycle. */
export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversation = ref<Conversation | null>(null)
  const showConversationList = ref(false)
  const showMobileDiscussion = ref(false)
  const messages = ref<Message[]>([])
  const highlightedMessageIds = ref<string[]>([])
  const sideRun = ref(idleRun())
  const streamError = ref('')
  const latestRun = ref<Record<string, any> | null>(null)
  const restoringRetry = ref(false)
  const retryRun = computed(() => {
    const run = latestRun.value
    return run?.retryable && ['failed', 'expired'].includes(run.status)
      && ['waiting', 'planning', 'answering'].includes(run.phase) ? run : null
  })
  const canRetry = computed(() => Boolean(retryRun.value && !sideRun.value.active && !restoringRetry.value))

  let sectionLoadVersion = 0
  let conversationLoadVersion = 0
  let streamVersion = 0
  let streamController: AbortController | null = null
  let highlightTimer: ReturnType<typeof setTimeout> | null = null
  let studyAssistEventHandler: StudyAssistEventHandler | null = null

  function clearMessages() {
    ++conversationLoadVersion
    ++streamVersion
    streamController?.abort()
    streamController = null
    messages.value = []
    sideRun.value = idleRun()
    latestRun.value = null
    restoringRetry.value = false
    streamError.value = ''
  }

  // Some navigation callers assign the selected conversation directly.
  watch(() => activeConversation.value?.id, clearMessages, { flush: 'sync' })

  function applyLatestRun(run: Record<string, any> | null) {
    latestRun.value = run
    for (const message of messages.value) {
      if (message.role === 'assistant') {
        message.incomplete = Boolean(retryRun.value && message.id && message.id === run?.answerMessageId)
      }
    }
    if (run?.status === 'running') {
      sideRun.value = {
        active: true, phase: run.phase || 'waiting',
        label: run.phase === 'guiding' ? '主线老师正在总结引导' : 'AI 正在处理中',
      }
    } else {
      sideRun.value = idleRun()
      if (run && ['failed', 'expired'].includes(run.status)) {
        streamError.value = run.errorMessage || (retryRun.value
          ? '上一次回答未完成，可以重新生成回答。' : '上一次 AI 请求失败。')
      }
    }
  }

  async function loadSectionConversations(card: Card | null, section: Section | null, preferredConversationId: string | null = null) {
    const version = ++sectionLoadVersion
    if (!card || !section) {
      conversations.value = []
      activeConversation.value = null
      clearMessages()
      return
    }
    const next = await request<Conversation[]>(
      `/cards/${card.id}/conversations?sectionId=${encodeURIComponent(section.id)}`,
    )
    if (version !== sectionLoadVersion) return
    conversations.value = next
    const requestedId = preferredConversationId || activeConversation.value?.id
    activeConversation.value = next.find((item) => item.id === requestedId) || next[0] || null
    await loadConversationMessages(activeConversation.value)
  }

  async function loadConversationMessages(conversation: Conversation | null) {
    clearMessages()
    if (!conversation) return
    const version = conversationLoadVersion
    const isCurrent = () => version === conversationLoadVersion && activeConversation.value?.id === conversation.id
    restoringRetry.value = true
    try {
      const stored = await request<Message[]>(`/conversations/${conversation.id}/messages`)
      if (!isCurrent()) return
      messages.value = stored.filter((message) => message.visibility !== 'internal').map((message) => ({
        id: message.id, role: message.role, content: message.content,
        senderId: message.senderId, senderName: message.senderName, senderRole: message.senderRole,
      }))
      const run = await request<Record<string, any> | null>(`/conversations/${conversation.id}/runs/latest`)
      if (!isCurrent()) return
      applyLatestRun(run)
      if (run?.status === 'running' && ['waiting', 'planning', 'answering'].includes(run.phase)
        && !messages.value.some((message) => message.id === run.answerMessageId)) {
        messages.value.push({
          role: 'assistant', content: '', pending: true,
          senderId: 'side_tutor', senderName: '答疑助教', senderRole: 'assistant',
        })
      }
    } catch (error) {
      if (isCurrent()) throw error
    } finally {
      if (isCurrent()) restoringRetry.value = false
    }
  }

  async function streamMessage(section: Section, text?: string, retry?: Record<string, any>) {
    const conversation = activeConversation.value!
    const version = ++streamVersion
    ++conversationLoadVersion
    const isCurrent = () => version === streamVersion && activeConversation.value?.id === conversation.id
    const controller = new AbortController()
    streamController = controller
    sideRun.value = { active: true, phase: 'waiting', label: retry ? '正在重新生成回答' : '正在等待 AI 响应' }
    streamError.value = ''
    if (!retry) latestRun.value = null
    let question: Message | undefined = retry
      ? messages.value.find((message) => message.id === retry.questionMessageId)
      : undefined
    if (!retry) {
      messages.value.push({ role: 'user', content: text })
      question = messages.value[messages.value.length - 1]
    }
    let assistant: Message | undefined
    const appendAssistant = () => {
      messages.value.push({
        role: 'assistant', content: '', pending: true,
        senderId: 'side_tutor', senderName: '答疑助教', senderRole: 'assistant',
      })
      // Mutate the reactive message, not the original raw object.
      assistant = messages.value[messages.value.length - 1]
    }
    if (!retry) appendAssistant()
    const removeEmptyAssistant = () => {
      if (!assistant || assistant.content) return
      const index = messages.value.indexOf(assistant)
      if (index >= 0) messages.value.splice(index, 1)
    }
    let terminal = false
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
    const recoverLatestRun = async () => {
      restoringRetry.value = true
      try {
        const run = await request<Record<string, any> | null>(`/conversations/${conversation.id}/runs/latest`)
        if (!isCurrent()) return
        if (retry && run?.id === retry.id && ['failed', 'expired', 'completed'].includes(run.status)
          && run.answerMessageId !== retry.answerMessageId) {
          // The server may have accepted retry even when run.started never reached us.
          const stored = await request<Message[]>(`/conversations/${conversation.id}/messages`)
          if (!isCurrent()) return
          messages.value = stored.filter((message) => message.visibility !== 'internal').map((message) => ({
            id: message.id, role: message.role, content: message.content,
            senderId: message.senderId, senderName: message.senderName, senderRole: message.senderRole,
          }))
          question = messages.value.find((message) => message.id === run.questionMessageId)
          assistant = messages.value.find((message) => message.id === run.answerMessageId)
        }
        if (question && run?.questionMessageId) question.id = run.questionMessageId
        if (assistant && run?.answerMessageId) assistant.id = run.answerMessageId
        applyLatestRun(run)
      } catch {
        // Keep the interrupted-answer notice if status recovery also fails.
      } finally {
        if (isCurrent()) restoringRetry.value = false
      }
    }
    try {
      const response = await fetch(retry
        ? `/api/v1/conversations/${conversation.id}/runs/${retry.id}/retry`
        : `/api/v1/conversations/${conversation.id}/messages/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        signal: controller.signal,
        ...(retry ? {} : { body: JSON.stringify({ content: text, sectionId: section.id }) }),
      })
      if (!isCurrent()) return
      if (!response.ok) throw await createStreamError(response)
      if (!response.body) throw new Error('AI 流式响应不可用，请检查浏览器或反向代理配置')
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const processBlock = (block: string) => {
        if (!isCurrent() || terminal) return
        const lines = block.split(/\r?\n/)
        const eventLine = lines.find((line) => line.startsWith('event:'))
        const dataLines = lines.filter((line) => line.startsWith('data:'))
        if (!eventLine || !dataLines.length) return
        const event = eventLine.slice(6).trim()
        let data: Record<string, any>
        try {
          data = JSON.parse(dataLines.map((line) => line.slice(5).trim()).join('\n'))
        } catch (error) {
          if (error instanceof SyntaxError) return
          throw error
        }
        if (event === 'run.started') {
          if (question && data.questionMessageId) question.id = data.questionMessageId
          if (retry) {
            // Acceptance is the only point at which the old partial may disappear.
            const index = messages.value.findIndex((message) => message.id === data.replacedMessageId)
            if (data.replacedMessageId && index >= 0) messages.value.splice(index, 1)
            appendAssistant()
          }
          latestRun.value = {
            id: data.runId, status: 'running', phase: data.phase || 'waiting', retryable: false,
            questionMessageId: data.questionMessageId, answerMessageId: null,
          }
        }
        if (event === 'run.phase' || event === 'run.started') {
          sideRun.value = { active: true, phase: data.phase || 'waiting', label: data.label || 'AI 正在处理' }
          if (latestRun.value) latestRun.value.phase = sideRun.value.phase
        }
        if (event === 'message.started' && assistant) {
          assistant.id = data.messageId
          assistant.senderId = data.senderId || assistant.senderId
          assistant.senderName = data.senderName || assistant.senderName
          assistant.senderRole = data.senderRole || assistant.senderRole
          if (latestRun.value) latestRun.value.answerMessageId = data.messageId
        }
        if (event === 'message.delta' && assistant) {
          assistant.pending = false
          sideRun.value = { active: true, phase: 'answering', label: '答疑助教正在回答' }
          assistant.content += data.delta || ''
        }
        if (event === 'related_card.proposed' || event === 'guidance.updated') studyAssistEventHandler?.(event, data)
        if (event === 'guidance.failed') {
          streamError.value = `课程导师引导失败：${data.message || '未知错误'}`
          studyAssistEventHandler?.(event, data)
        }
        if (event === 'run.failed') {
          streamError.value = data.message || 'AI 服务调用失败'
          if (question && data.questionMessageId) question.id = data.questionMessageId
          if (assistant && data.answerMessageId) assistant.id = data.answerMessageId
          applyLatestRun({
            ...latestRun.value, id: data.runId || latestRun.value?.id, status: 'failed',
            phase: data.phase || latestRun.value?.phase, retryable: data.retryable === true,
            questionMessageId: data.questionMessageId, answerMessageId: data.answerMessageId,
            errorMessage: streamError.value,
          })
          // The request remains busy until its terminal event or recovery finishes.
          sideRun.value = { active: true, phase: data.phase || 'waiting', label: '正在结束 AI 请求' }
          removeEmptyAssistant()
        }
        if (event === 'run.completed') {
          applyLatestRun({ ...latestRun.value, status: 'completed', retryable: false })
          sideRun.value.active = true
        }
        if (event === 'message.completed') terminal = true
      }
      while (isCurrent() && !terminal) {
        const { value, done } = await reader.read()
        if (!isCurrent()) return
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop() || ''
        blocks.forEach(processBlock)
        if (done) {
          if (buffer.trim()) processBlock(buffer)
          break
        }
      }
      if (!isCurrent()) return
      if (!terminal) throw new Error('AI 回答连接已中断，回答可能未完成。')
      sideRun.value = idleRun()
    } catch (error) {
      if (!isCurrent()) return
      const message = error instanceof Error ? error.message : 'AI 回答连接已中断'
      streamError.value = message
      sideRun.value = idleRun()
      if (assistant) assistant.pending = false
      removeEmptyAssistant()
      await recoverLatestRun()
      if (isCurrent()) {
        // Status recovery supplies eligibility, not a replacement for this request's error.
        streamError.value = message
        throw error
      }
    } finally {
      if (reader) {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
      if (isCurrent()) {
        if (assistant) assistant.pending = false
        streamController = null
      }
    }
    return isCurrent() ? streamError.value : undefined
  }

  async function sendMessage(text: string, section: Section | null) {
    if (!activeConversation.value || !section || !text.trim() || sideRun.value.active || restoringRetry.value) return
    if (activeConversation.value.sectionId !== section.id) {
      throw new Error('请在该讨论所属的章节中继续提问。')
    }
    return streamMessage(section, text)
  }

  async function retryMessage(section: Section | null) {
    if (!canRetry.value || !activeConversation.value || !section) return
    if (activeConversation.value.sectionId !== section.id) {
      throw new Error('请在该讨论所属的章节中重新生成回答。')
    }
    return streamMessage(section, undefined, retryRun.value!)
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
    ++sectionLoadVersion
    conversations.value = []
    activeConversation.value = null
    showConversationList.value = false
    clearMessages()
    highlightedMessageIds.value = []
  }

  function setStudyAssistEventHandler(handler: StudyAssistEventHandler | null) {
    studyAssistEventHandler = handler
  }

  return {
    conversations, activeConversation, showConversationList, showMobileDiscussion,
    messages, highlightedMessageIds, sideRun, latestRun, retryRun, canRetry, restoringRetry,
    streamError,
    loadSectionConversations, loadConversationMessages, sendMessage, retryMessage, selectConversation,
    highlightMessages, clearMessages, reset, setStudyAssistEventHandler,
  }
})
