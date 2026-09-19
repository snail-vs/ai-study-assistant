import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { request } from '../api/client'

export type CourseScale = 'quick' | 'standard' | 'series'
export type CourseDesignPhase = 'goal' | 'interview' | 'review' | 'generating'

export interface CourseBrief {
  topic?: string
  learningOutcome?: string
  priorKnowledge?: string
  useCase?: string
  focus?: string[]
  excludedTopics?: string[]
  preferredStyle?: string[]
  timeBudgetMinutes?: number
  courseScale?: CourseScale
  [key: string]: unknown
}

export interface CourseDesignMessage {
  role: 'user' | 'assistant'
  content: string
  quickOptions?: string[]
  pending?: boolean
}

export interface CourseOutlineItem {
  title: string
  objective?: string
  [key: string]: unknown
}

export interface CourseDesignResponse {
  message?: string | { content?: string; quickOptions?: string[] }
  assistantMessage?: string
  question?: string
  quickOptions?: string[]
  brief?: CourseBrief
  courseBrief?: CourseBrief
  recommendedScale?: CourseScale
  outline?: CourseOutlineItem[]
  ready?: boolean
}

const SCALE_OPTIONS: Array<{ id: CourseScale; label: string; hint: string; detail: string }> = [
  { id: 'quick', label: '快速了解', hint: '15–30 分钟', detail: '2–3 节，聚焦核心概念和眼前问题' },
  { id: 'standard', label: '标准课程', hint: '2–5 小时', detail: '5–8 节，从基础到能够实际使用' },
  { id: 'series', label: '系列课程', hint: '数天到数周', detail: '分阶段系统学习，本轮先生成总览和第一阶段' },
]

function normalizeMessage(value: CourseDesignResponse['message']): CourseDesignMessage | null {
  if (!value) return null
  if (typeof value === 'string') return { role: 'assistant', content: value }
  if (typeof value.content !== 'string') return null
  return { role: 'assistant', content: value.content, quickOptions: value.quickOptions }
}

export const useCourseDesignStore = defineStore('courseDesign', () => {
  const phase = ref<CourseDesignPhase>('goal')
  const goal = ref('')
  const messages = ref<CourseDesignMessage[]>([])
  const draftBrief = ref<CourseBrief>({})
  const quickOptions = ref<string[]>([])
  const selectedScale = ref<CourseScale | null>(null)
  const recommendedScale = ref<CourseScale>('standard')
  const outline = ref<CourseOutlineItem[]>([])
  const outlineLoading = ref(false)
  const outlineError = ref('')
  const outlineConfirmed = ref(false)
  const revisionMessages = ref<CourseDesignMessage[]>([])
  const revisionLoading = ref(false)
  const revisionError = ref('')
  const turnCount = ref(0)
  const loading = ref(false)
  const error = ref('')

  const canAskMore = computed(() => turnCount.value < 3)
  const ready = computed(() => phase.value === 'review' && Boolean(goal.value.trim()))
  const waitingForAI = computed(() => phase.value === 'interview' && loading.value)
  const waitingForUser = computed(() => phase.value === 'interview' && !loading.value
    && !error.value && messages.value.some((message) => message.role === 'assistant' && !message.pending && Boolean(message.content.trim())))
  const scaleOptions = computed(() => SCALE_OPTIONS)

  function reset() {
    phase.value = 'goal'
    goal.value = ''
    messages.value = []
    draftBrief.value = {}
    quickOptions.value = []
    selectedScale.value = null
    recommendedScale.value = 'standard'
    outline.value = []
    outlineLoading.value = false
    outlineError.value = ''
    outlineConfirmed.value = false
    revisionMessages.value = []
    revisionLoading.value = false
    revisionError.value = ''
    turnCount.value = 0
    loading.value = false
    error.value = ''
  }

  function applyResponse(response: CourseDesignResponse) {
    const message = normalizeMessage(response.message)
    const lead = response.assistantMessage || message?.content || ''
    const question = response.question || (!response.ready ? lead || '为了更准确地设计课程，请告诉我你希望学完后能够完成什么？' : '')
    const content = response.ready
      ? lead || question
      : lead && question && lead.trim() !== question.trim() ? `${lead.trim()}\n${question.trim()}` : question
    const assistant = content ? { role: 'assistant' as const, content, quickOptions: response.quickOptions || message?.quickOptions } : null
    const pendingIndex = messages.value.findIndex((item) => item.role === 'assistant' && item.pending)
    if (pendingIndex >= 0) {
      if (assistant) messages.value.splice(pendingIndex, 1, assistant)
      else messages.value.splice(pendingIndex, 1)
    } else if (assistant) messages.value.push(assistant)
    quickOptions.value = response.ready ? [] : (response.quickOptions || message?.quickOptions || [])
    draftBrief.value = { ...draftBrief.value, ...(response.brief || response.courseBrief || {}) }
    if (response.recommendedScale) {
      recommendedScale.value = response.recommendedScale
    }
    // The turn endpoint may include a draft outline. It is deliberately not
    // used for confirmation; the dedicated outline endpoint creates the
    // scale-aware outline after the learner chooses a scale.
    // An outline can be returned as an early draft while the agent still
    // needs another high-value answer. Only an explicit ready response or
    // the three-turn client limit ends the interview.
    if (response.ready || !canAskMore.value) phase.value = 'review'
  }

  async function submitTurn(answer: string, options: { direct?: boolean; initial?: boolean; retry?: boolean } = {}) {
    const text = answer.trim()
    // The first turn is the AI's initial question and intentionally has no
    // user answer yet. Subsequent empty turns are only valid for direct mode.
    if (!text && !options.direct && !options.retry && turnCount.value > 0) return null
    if (loading.value) return null
    error.value = ''
    loading.value = true
    if (text) messages.value.push({ role: 'user', content: text })
    messages.value.push({ role: 'assistant', content: '', pending: true })
    try {
      const response = await request<CourseDesignResponse>('/course-design/turn', {
        method: 'POST',
        body: JSON.stringify({
          messages: messages.value.filter((message) => !message.pending),
          brief: draftBrief.value,
          skip: Boolean(options.direct),
        }),
      })
      turnCount.value += 1
      applyResponse(response)
      if (phase.value !== 'review' && canAskMore.value) phase.value = 'interview'
      return response
    } catch (err) {
      const pendingIndex = messages.value.findIndex((item) => item.role === 'assistant' && item.pending)
      if (pendingIndex >= 0) messages.value.splice(pendingIndex, 1)
      if (text) {
        let userIndex = -1
        for (let index = messages.value.length - 1; index >= 0; index -= 1) {
          if (messages.value[index].role === 'user' && messages.value[index].content === text) {
            userIndex = index
            break
          }
        }
        if (userIndex >= 0) messages.value.splice(userIndex, 1)
      }
      error.value = err instanceof Error ? err.message : '课程设计请求失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function begin(value: string) {
    const text = value.trim()
    if (!text || loading.value) return null
    goal.value = text
    phase.value = 'interview'
    // The backend derives the topic from the conversation; keep the initial
    // goal as the first user turn instead of sending it as an out-of-band field.
    messages.value.push({ role: 'user', content: text })
    return submitTurn('', { direct: false, initial: true })
  }

  async function answer(value: string) {
    return submitTurn(value)
  }

  async function generateDirectly() {
    if (!goal.value.trim()) return null
    return submitTurn('', { direct: true })
  }

  async function retry() {
    if (loading.value || phase.value !== 'interview') return null
    return submitTurn('', { retry: true })
  }

  function chooseScale(scale: CourseScale) {
    selectedScale.value = scale
    draftBrief.value = { ...draftBrief.value, courseScale: scale }
    outline.value = []
    outlineError.value = ''
    outlineConfirmed.value = false
    revisionMessages.value = []
    revisionError.value = ''
  }

  async function generateOutline() {
    if (outlineLoading.value || !goal.value.trim() || !selectedScale.value) return null
    outlineLoading.value = true
    outlineError.value = ''
    outline.value = []
    try {
      const response = await request<{ outline?: CourseOutlineItem[] }>('/course-design/outline', {
        method: 'POST',
        body: JSON.stringify({ brief: draftBrief.value, courseScale: selectedScale.value }),
      })
      const generated = Array.isArray(response?.outline) ? response.outline : []
      if (!generated.length) throw new Error('课程大纲为空，请重试')
      outline.value = generated
      return generated
    } catch (err) {
      outlineError.value = err instanceof Error ? err.message : '课程大纲生成失败，请重试'
      throw err
    } finally {
      outlineLoading.value = false
    }
  }

  async function reviseOutline(feedback: string) {
    const text = feedback.trim()
    if (!text || revisionLoading.value || !selectedScale.value || !outline.value.length) return null
    revisionLoading.value = true
    revisionError.value = ''
    revisionMessages.value.push({ role: 'user', content: text })
    try {
      const response = await request<{ outline?: CourseOutlineItem[]; assistantMessage?: string }>('/course-design/outline/revise', {
        method: 'POST',
        body: JSON.stringify({
          brief: draftBrief.value,
          courseScale: selectedScale.value,
          currentOutline: outline.value,
          feedback: text,
          // `feedback` carries the current turn; messages contains only prior
          // revision turns so the backend does not receive it twice.
          messages: revisionMessages.value.slice(0, -1),
        }),
      })
      const generated = Array.isArray(response?.outline) ? response.outline : []
      if (!generated.length) throw new Error('修改后的课程大纲为空，请重试')
      outline.value = generated
      outlineConfirmed.value = false
      if (response.assistantMessage) revisionMessages.value.push({ role: 'assistant', content: response.assistantMessage })
      return generated
    } catch (err) {
      revisionMessages.value.pop()
      revisionError.value = err instanceof Error ? err.message : '大纲修改失败，请重试'
      throw err
    } finally {
      revisionLoading.value = false
    }
  }

  function confirmOutline() {
    if (outline.value.length && !outlineLoading.value && !revisionLoading.value) outlineConfirmed.value = true
  }

  function editBrief(next: Partial<CourseBrief>) {
    draftBrief.value = { ...draftBrief.value, ...next }
  }

  function review() {
    phase.value = 'review'
  }

  function payload() {
    const title = String(draftBrief.value.topic || goal.value).trim()
    return {
      title,
      learningGoal: goal.value.trim(),
      courseBrief: { ...draftBrief.value, ...(selectedScale.value ? { courseScale: selectedScale.value } : {}) },
      courseScale: selectedScale.value,
      courseOutline: outline.value,
    }
  }

  function markGenerating() {
    phase.value = 'generating'
  }

  return {
    phase, goal, messages, draftBrief, quickOptions, selectedScale, recommendedScale,
    outline, outlineLoading, outlineError, outlineConfirmed, revisionMessages, revisionLoading, revisionError,
    turnCount, loading, error, canAskMore, ready, waitingForAI, waitingForUser, scaleOptions,
    reset, begin, answer, generateDirectly, retry, chooseScale, generateOutline, reviseOutline, confirmOutline, editBrief, review, payload, markGenerating,
  }
})
