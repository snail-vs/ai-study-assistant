import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCourseDesignStore } from './course-design'
import { request } from '../api/client'

vi.mock('../api/client', () => ({ request: vi.fn() }))
const mockedRequest = vi.mocked(request)

const question = {
  id: 'goal-1', stage: 'collecting_goals' as const, target: 'learningGoals' as const,
  type: 'multi_select_with_text' as const, title: '你希望获得哪些能力？', description: '', allowCustom: true,
  minimumSelections: 0, options: [{ id: 'a', label: '理解原理' }, { id: 'b', label: '完成实践' }],
}
function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    sessionId: 'session-1', state: 'collecting_goals' as const, revision: 1, briefRevision: 0,
    brief: { topic: 'Kubernetes' }, currentQuestion: question, recommendedScale: 'standard' as const,
    selectedScale: null, outline: [], outlineConfirmed: false, allowedActions: ['answer_question'], operation: {}, outlineRevisionMessages: [],
    ...overrides,
  }
}

describe('course design session store', () => {
  beforeEach(() => { setActivePinia(createPinia()); mockedRequest.mockReset(); localStorage.clear() })

  it('creates a session and persists its id for refresh recovery', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot())
    const store = useCourseDesignStore()
    await store.begin('学习 Kubernetes')
    expect(localStorage.getItem('studycenter.courseDesign.sessionId')).toBe('session-1')
    expect(store.phase).toBe('intake')
    expect(mockedRequest).toHaveBeenCalledWith('/course-design/sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('returns to the topic page while preserving the topic and clearing the active session', () => {
    const store = useCourseDesignStore()
    store.applySnapshot(snapshot())
    store.topic = '学习 OpenStack'
    store.toggleOption('a')
    store.returnToTopic()
    expect(store.phase).toBe('topic')
    expect(store.topic).toBe('学习 OpenStack')
    expect(store.session).toBe(null)
    expect(store.selectedOptionIds).toEqual([])
    expect(localStorage.getItem('studycenter.courseDesign.sessionId')).toBe(null)
    store.reset()
    expect(store.topic).toBe('')
  })

  it('does not request when selecting chips; Next sends one typed command', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot())
    const store = useCourseDesignStore()
    await store.begin('学习 Kubernetes')
    mockedRequest.mockClear()
    store.toggleOption('a')
    store.toggleOption('b')
    store.setCustomAnswer('希望能够独立开发 Operator')
    expect(mockedRequest).not.toHaveBeenCalled()
    mockedRequest.mockResolvedValueOnce(snapshot({ revision: 2, state: 'collecting_background', brief: { topic: 'Kubernetes', learningGoals: ['理解原理', '完成实践'], learningOutcome: '掌握并实践' }, currentQuestion: { ...question, id: 'background-1', stage: 'collecting_background', target: 'priorKnowledgeLevels' } }))
    await store.answerQuestion()
    expect(mockedRequest).toHaveBeenCalledTimes(1)
    const body = JSON.parse(mockedRequest.mock.calls[0][1]?.body as string)
    expect(body).toMatchObject({ type: 'answer_question', expectedRevision: 1, payload: { answer: { questionId: 'goal-1', selectedOptionIds: ['a', 'b'], customText: '希望能够独立开发 Operator' } } })
    expect(body.commandId).toEqual(expect.any(String))
  })

  it('keeps server selections and restores the previous question after going back', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'collecting_background', revision: 2, brief: { topic: 'Kubernetes', learningGoals: ['理解原理'] }, currentQuestion: { ...question, id: 'background-1', stage: 'collecting_background', target: 'priorKnowledgeLevels' } }))
    const store = useCourseDesignStore()
    await store.begin('学习 Kubernetes')
    mockedRequest.mockResolvedValueOnce(snapshot({ revision: 3, brief: { topic: 'Kubernetes', learningGoals: ['理解原理'] } }))
    await store.goBack()
    expect(store.phase).toBe('intake')
    expect(store.question?.id).toBe('goal-1')
    expect(store.brief.learningGoals).toEqual(['理解原理'])
  })

  it('keeps AI recommendation separate from selection and requires explicit outline generation', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'reviewing_brief', revision: 3, briefRevision: 2, brief: { topic: 'Kubernetes', learningOutcome: '掌握原理', priorKnowledge: '有基础', learningGoals: ['理解原理'], priorKnowledgeLevels: ['有基础'] }, currentQuestion: null, recommendedScale: 'standard' }))
    const store = useCourseDesignStore()
    await store.begin('学习 Kubernetes')
    mockedRequest.mockClear()
    expect(store.selectedScale).toBe(null)
    expect(store.recommendedScale).toBe('standard')
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'reviewing_brief', revision: 4, briefRevision: 3, selectedScale: 'standard', recommendedScale: 'standard', currentQuestion: null, brief: { topic: 'Kubernetes', learningOutcome: '掌握原理', priorKnowledge: '有基础' } }))
    await store.selectScale('standard')
    expect(mockedRequest).toHaveBeenCalledTimes(1)
    const scaleBody = JSON.parse(mockedRequest.mock.calls[0][1]?.body as string)
    expect(scaleBody.type).toBe('select_scale')
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'reviewing_outline', revision: 5, briefRevision: 3, selectedScale: 'standard', currentQuestion: null, outline: [{ title: '原理', objective: '理解' }] }))
    await store.generateOutline()
    expect(JSON.parse(mockedRequest.mock.calls[1][1]?.body as string).type).toBe('generate_outline')
  })

  it('gates course generation behind confirmed outline and emits the exact space id result', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'outline_confirmed', revision: 8, briefRevision: 3, selectedScale: 'standard', currentQuestion: null, outline: [{ title: '原理', objective: '理解' }], outlineConfirmed: true }))
    const store = useCourseDesignStore()
    await store.begin('学习 Kubernetes')
    mockedRequest.mockClear()
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'course_queued', revision: 9, briefRevision: 3, selectedScale: 'standard', currentQuestion: null, outline: [{ title: '原理', objective: '理解' }], outlineConfirmed: true, operation: { status: 'succeeded', type: 'generate_course', spaceId: 'space-42' } }))
    const result = await store.generateCourse()
    expect(result.spaceId).toBe('space-42')
    expect(localStorage.getItem('studycenter.courseDesign.sessionId')).toBe(null)
    expect(JSON.parse(mockedRequest.mock.calls[0][1]?.body as string).type).toBe('generate_course')
  })
})
