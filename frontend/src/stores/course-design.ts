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
  const selectedScale = ref<CourseScale>('standard')
  const recommendedScale = ref<CourseScale>('standard')
  const outline = ref<CourseOutlineItem[]>([])
  const turnCount = ref(0)
  const loading = ref(false)
  const error = ref('')

  const canAskMore = computed(() => turnCount.value < 3)
  const ready = computed(() => phase.value === 'review' && Boolean(goal.value.trim()))
  const scaleOptions = computed(() => SCALE_OPTIONS)

  function reset() {
    phase.value = 'goal'
    goal.value = ''
    messages.value = []
    draftBrief.value = {}
    quickOptions.value = []
    selectedScale.value = 'standard'
    recommendedScale.value = 'standard'
    outline.value = []
    turnCount.value = 0
    loading.value = false
    error.value = ''
  }

  function applyResponse(response: CourseDesignResponse) {
    const assistant = normalizeMessage(response.message)
      || (response.assistantMessage ? { role: 'assistant' as const, content: response.assistantMessage } : null)
    const question = response.question || assistant?.content
    if (assistant) messages.value.push(assistant)
    else if (question) messages.value.push({ role: 'assistant', content: question, quickOptions: response.quickOptions })
    quickOptions.value = response.quickOptions || assistant?.quickOptions || []
    draftBrief.value = { ...draftBrief.value, ...(response.brief || response.courseBrief || {}) }
    if (response.recommendedScale) {
      recommendedScale.value = response.recommendedScale
      if (selectedScale.value === 'standard') selectedScale.value = response.recommendedScale
    }
    if (Array.isArray(response.outline)) outline.value = response.outline
    // An outline can be returned as an early draft while the agent still
    // needs another high-value answer. Only an explicit ready response or
    // the three-turn client limit ends the interview.
    if (response.ready || !canAskMore.value) phase.value = 'review'
  }

  async function submitTurn(answer: string, options: { direct?: boolean } = {}) {
    const text = answer.trim()
    // The first turn is the AI's initial question and intentionally has no
    // user answer yet. Subsequent empty turns are only valid for direct mode.
    if (!text && !options.direct && turnCount.value > 0) return null
    if (loading.value) return null
    error.value = ''
    loading.value = true
    if (text) messages.value.push({ role: 'user', content: text })
    try {
      const response = await request<CourseDesignResponse>('/course-design/turn', {
        method: 'POST',
        body: JSON.stringify({
          messages: messages.value,
          brief: draftBrief.value,
          skip: Boolean(options.direct),
        }),
      })
      turnCount.value += 1
      applyResponse(response)
      if (phase.value !== 'review' && canAskMore.value) phase.value = 'interview'
      return response
    } catch (err) {
      if (text && messages.value[messages.value.length - 1]?.role === 'user') messages.value.pop()
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
    return submitTurn('', { direct: false })
  }

  async function answer(value: string) {
    return submitTurn(value)
  }

  async function generateDirectly() {
    if (!goal.value.trim()) return null
    return submitTurn('', { direct: true })
  }

  function chooseScale(scale: CourseScale) {
    selectedScale.value = scale
    draftBrief.value = { ...draftBrief.value, courseScale: scale }
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
      courseBrief: { ...draftBrief.value, courseScale: selectedScale.value },
      courseScale: selectedScale.value,
    }
  }

  function markGenerating() {
    phase.value = 'generating'
  }

  return {
    phase, goal, messages, draftBrief, quickOptions, selectedScale, recommendedScale,
    outline, turnCount, loading, error, canAskMore, ready, scaleOptions,
    reset, begin, answer, generateDirectly, chooseScale, editBrief, review, payload, markGenerating,
  }
})
