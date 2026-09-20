import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { request } from '../api/client'
import type { components } from '../api/generated/schema'

export type CourseScale = Exclude<components['schemas']['CourseDesignSession']['selectedScale'], null | undefined>
export type CourseDesignState = components['schemas']['CourseDesignSession']['state']
export type CourseDesignQuestion = components['schemas']['CourseDesignQuestion']
export type CourseDesignSession = components['schemas']['CourseDesignSession']
export type CourseOutlineItem = components['schemas']['CourseOutlineItem']
export type CourseBrief = components['schemas']['CourseBrief']
export type CourseDesignCommandType = components['schemas']['CourseDesignCommandRequest']['type']
export type CourseDesignPayload = NonNullable<components['schemas']['CourseDesignCommandRequest']['payload']>
export type CourseDesignMessage = components['schemas']['CourseOutlineRevisionMessage']

export interface ScaleOption { id: CourseScale; label: string; hint: string; detail: string }

export const SCALE_OPTIONS: ScaleOption[] = [
  { id: 'quick', label: '快速了解', hint: '15–30 分钟', detail: '2–3 节，聚焦核心概念和眼前问题' },
  { id: 'standard', label: '标准课程', hint: '2–5 小时', detail: '5–8 节，从基础到能够实际使用' },
  { id: 'series', label: '系列课程', hint: '数天到数周', detail: '分阶段系统学习，本轮先生成总览和第一阶段' },
]

const SESSION_KEY = 'studycenter.courseDesign.sessionId'

function commandId() {
  return globalThis.crypto?.randomUUID?.() || `cmd_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

export const useCourseDesignStore = defineStore('courseDesign', () => {
  const session = ref<CourseDesignSession | null>(null)
  const topic = ref('')
  const loading = ref(false)
  const error = ref('')
  const operationError = ref('')
  const activeCommand = ref<CourseDesignCommandType | null>(null)
  const selectedOptionIds = ref<string[]>([])
  const customAnswer = ref('')
  const learningOutcomeDraft = ref('')
  const priorKnowledgeDraft = ref('')

  const phase = computed(() => {
    if (!session.value) return 'topic'
    if (session.value.state === 'collecting_goals' || session.value.state === 'collecting_background') return 'intake'
    if (session.value.state === 'reviewing_brief') return 'brief'
    if (session.value.state === 'reviewing_outline' || session.value.state === 'outline_confirmed') return 'outline'
    if (session.value.state === 'course_queued') return 'queued'
    return 'topic'
  })
  const question = computed(() => session.value?.currentQuestion || null)
  const isGoalStage = computed(() => session.value?.state === 'collecting_goals')
  const isBackgroundStage = computed(() => session.value?.state === 'collecting_background')
  const scaleOptions = computed(() => SCALE_OPTIONS)
  const selectedScale = computed(() => session.value?.selectedScale || null)
  const recommendedScale = computed(() => session.value?.recommendedScale || null)
  const outline = computed(() => session.value?.outline || [])
  const outlineConfirmed = computed(() => Boolean(session.value?.outlineConfirmed))
  const revisionMessages = computed(() => session.value?.outlineRevisionMessages || [])
  const brief = computed(() => session.value?.brief || {})
  const isBusy = computed(() => loading.value)

  function persistSessionId() {
    if (session.value?.sessionId) localStorage.setItem(SESSION_KEY, session.value.sessionId)
    else localStorage.removeItem(SESSION_KEY)
  }

  function applySnapshot(snapshot: CourseDesignSession) {
    session.value = snapshot
    topic.value = snapshot.brief.topic || topic.value
    if (snapshot.state === 'reviewing_brief') {
      learningOutcomeDraft.value = snapshot.brief.learningOutcome || ''
      priorKnowledgeDraft.value = snapshot.brief.priorKnowledge || ''
    }
    if (snapshot.state === 'collecting_goals' || snapshot.state === 'collecting_background') {
      const values = snapshot.state === 'collecting_goals' ? (snapshot.brief.learningGoals || []) : (snapshot.brief.priorKnowledgeLevels || [])
      selectedOptionIds.value = (snapshot.currentQuestion?.options || [])
        .filter((option) => values.includes(option.label)).map((option) => option.id)
      customAnswer.value = snapshot.state === 'collecting_goals'
        ? (snapshot.brief.learningGoalDetails || '')
        : (snapshot.brief.priorKnowledgeDetails || '')
    }
    persistSessionId()
  }

  function reset() {
    session.value = null
    topic.value = ''
    selectedOptionIds.value = []
    customAnswer.value = ''
    learningOutcomeDraft.value = ''
    priorKnowledgeDraft.value = ''
    loading.value = false
    activeCommand.value = null
    error.value = ''
    operationError.value = ''
    persistSessionId()
  }

  async function restore() {
    const id = localStorage.getItem(SESSION_KEY)
    if (!id || loading.value) return null
    loading.value = true
    error.value = ''
    try {
      const snapshot = await request<CourseDesignSession>(`/course-design/sessions/${id}`)
      applySnapshot(snapshot)
      return snapshot
    } catch (err) {
      localStorage.removeItem(SESSION_KEY)
      error.value = err instanceof Error ? err.message : '恢复课程设计失败'
      return null
    } finally { loading.value = false }
  }

  async function begin(value: string, learningSpaceId?: string | null) {
    const text = value.trim()
    if (!text || loading.value) return null
    topic.value = text
    loading.value = true
    error.value = ''
    try {
      const snapshot = await request<CourseDesignSession>('/course-design/sessions', {
        method: 'POST', body: JSON.stringify({ topic: text, ...(learningSpaceId ? { learningSpaceId } : {}) }),
      })
      applySnapshot(snapshot)
      return snapshot
    } catch (err) {
      error.value = err instanceof Error ? err.message : '课程设计请求失败'
      throw err
    } finally { loading.value = false }
  }

  async function execute(type: CourseDesignCommandType, payload: CourseDesignPayload = {}) {
    const current = session.value
    if (!current || loading.value) return null
    loading.value = true
    activeCommand.value = type
    error.value = ''
    operationError.value = ''
    try {
      const snapshot = await request<CourseDesignSession>(`/course-design/sessions/${current.sessionId}/commands`, {
        method: 'POST', body: JSON.stringify({ commandId: commandId(), expectedRevision: current.revision, type, payload }),
      })
      applySnapshot(snapshot)
      return snapshot
    } catch (err) {
      const message = err instanceof Error ? err.message : '课程设计操作失败'
      error.value = message
      operationError.value = message
      throw err
    } finally {
      loading.value = false
      if (activeCommand.value === type) activeCommand.value = null
    }
  }

  function toggleOption(id: string) {
    selectedOptionIds.value = selectedOptionIds.value.includes(id)
      ? selectedOptionIds.value.filter((item) => item !== id)
      : [...selectedOptionIds.value, id]
  }
  function setSelectedOptionIds(values: string[]) { selectedOptionIds.value = [...values] }
  function setCustomAnswer(value: string) { customAnswer.value = value }
  async function answerQuestion() {
    const current = question.value
    if (!current || (!selectedOptionIds.value.length && !customAnswer.value.trim())) return null
    return execute('answer_question', { answer: {
      questionId: current.id, selectedOptionIds: selectedOptionIds.value, customText: customAnswer.value.trim(),
    } })
  }
  async function completeWithAI() { return execute('complete_with_ai') }
  async function goBack() { return execute('go_back') }
  async function restart() { return execute('restart') }
  async function updateBrief() {
    return execute('update_brief', { brief: { learningOutcome: learningOutcomeDraft.value.trim(), priorKnowledge: priorKnowledgeDraft.value.trim() } })
  }
  async function selectScale(scale: CourseScale) { return execute('select_scale', { courseScale: scale }) }
  async function generateOutline() { return execute('generate_outline') }
  async function reviseOutline(feedback: string) {
    if (!feedback.trim()) return null
    return execute('revise_outline', { feedback: feedback.trim() })
  }
  async function confirmOutline() { return execute('confirm_outline') }
  async function generateCourse() {
    const result = await execute('generate_course')
    if (result?.state === 'course_queued') {
      const spaceId = typeof result.operation?.spaceId === 'string' ? result.operation.spaceId : null
      reset()
      return { snapshot: result, spaceId }
    }
    return { snapshot: result, spaceId: null }
  }
  function setOutcomeDraft(value: string) { learningOutcomeDraft.value = value }
  function setPriorKnowledgeDraft(value: string) { priorKnowledgeDraft.value = value }
  async function updateBriefAndGenerateOutline() {
    if (!session.value) return null
    const updated = await updateBrief()
    if (!updated) return null
    return generateOutline()
  }

  return {
    session, topic, phase, question, isGoalStage, isBackgroundStage, brief, selectedScale,
    recommendedScale, outline, outlineConfirmed, revisionMessages, scaleOptions, selectedOptionIds,
    customAnswer, learningOutcomeDraft, priorKnowledgeDraft, loading, isBusy, activeCommand, error, operationError,
    applySnapshot, reset, restore, begin, execute, toggleOption, setCustomAnswer, answerQuestion,
    completeWithAI, goBack, restart, updateBrief, selectScale, generateOutline, reviseOutline,
    confirmOutline, generateCourse, setOutcomeDraft, setPriorKnowledgeDraft,
    setSelectedOptionIds, updateBriefAndGenerateOutline,
  }
})
