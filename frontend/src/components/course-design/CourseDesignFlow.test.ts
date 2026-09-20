import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CourseDesignFlow from './CourseDesignFlow.vue'
import { request } from '../../api/client'
import { useCourseDesignStore } from '../../stores/course-design'

vi.mock('../../api/client', () => ({ request: vi.fn() }))
const mockedRequest = vi.mocked(request)
const brief = { topic: 'Kubernetes', learningOutcome: '掌握原理', priorKnowledge: '有基础', learningGoals: ['理解原理'], priorKnowledgeLevels: ['有基础'] }
const question = { id: 'goal-1', stage: 'collecting_goals' as const, target: 'learningGoals' as const, type: 'multi_select_with_text' as const, title: '目标', description: '', options: [{ id: 'goal-a', label: '理解原理' }], allowCustom: true, minimumSelections: 0 }
const snapshot = (overrides: Record<string, unknown> = {}) => ({ sessionId: 's', state: 'collecting_goals' as const, revision: 1, briefRevision: 0, brief: { topic: 'Kubernetes' }, currentQuestion: question, recommendedScale: 'standard' as const, selectedScale: null, outline: [], outlineConfirmed: false, allowedActions: ['answer_question'], operation: {}, outlineRevisionMessages: [], ...overrides })

describe('CourseDesignFlow', () => {
  beforeEach(() => { setActivePinia(createPinia()); mockedRequest.mockReset(); localStorage.clear() })

  it('handles begin failure without an unhandled submit rejection', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('服务不可用'))
    const wrapper = mount(CourseDesignFlow)
    await wrapper.get('textarea[name="topic"]').setValue('学习 Kubernetes')
    await expect(wrapper.get('form').trigger('submit')).resolves.toBeUndefined()
    expect(useCourseDesignStore().error).toBe('服务不可用')
  })

  it('keeps the topic visible while begin is pending', async () => {
    let resolveBegin!: (value: unknown) => void
    mockedRequest.mockReturnValueOnce(new Promise((resolve) => { resolveBegin = resolve }))
    const wrapper = mount(CourseDesignFlow)
    const textarea = wrapper.get('textarea[name="topic"]')
    await textarea.setValue('学习 OpenStack')
    const submitting = wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(mockedRequest).toHaveBeenCalledTimes(1))
    expect((textarea.element as HTMLTextAreaElement).value).toBe('学习 OpenStack')
    resolveBegin(snapshot({ brief: { topic: '学习 OpenStack' } }))
    await submitting
  })

  it('keeps failed topic input editable and supports retry', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('服务不可用'))
    mockedRequest.mockResolvedValueOnce(snapshot({ brief: { topic: '学习 OpenStack' } }))
    const wrapper = mount(CourseDesignFlow)
    const textarea = wrapper.get('textarea[name="topic"]')
    await textarea.setValue('学习 OpenStack')
    await wrapper.get('form').trigger('submit')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('学习 OpenStack')
    await textarea.setValue('学习 OpenStack 网络与 Nova')
    await wrapper.get('form').trigger('submit')
    expect(mockedRequest).toHaveBeenCalledTimes(2)
    expect(JSON.parse(mockedRequest.mock.calls[1][1]?.body as string)).toMatchObject({ topic: '学习 OpenStack 网络与 Nova' })
  })

  it('returns from the first question to the topic page without losing the topic', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot({ brief: { topic: '学习 OpenStack' } }))
    const wrapper = mount(CourseDesignFlow)
    await wrapper.get('textarea[name="topic"]').setValue('学习 OpenStack')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('button.secondary').trigger('click')
    expect(wrapper.get('textarea[name="topic"]').element).toHaveProperty('value', '学习 OpenStack')
    expect(localStorage.getItem('studycenter.courseDesign.sessionId')).toBe(null)
  })

  it('shows answer loading while the command is pending and hides it after success', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot())
    const wrapper = mount(CourseDesignFlow)
    await wrapper.get('textarea[name="topic"]').setValue('学习 OpenStack')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('.course-option-chip').trigger('click')
    let resolveAnswer!: (value: unknown) => void
    mockedRequest.mockReturnValueOnce(new Promise((resolve) => { resolveAnswer = resolve }))
    const answering = wrapper.get('button.primary').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('正在整理你的回答…'))
    expect(wrapper.get('.course-question').attributes('aria-live')).toBe('polite')
    expect(wrapper.get('.course-question').attributes('aria-busy')).toBe('true')
    resolveAnswer(snapshot({ revision: 2, state: 'collecting_background', brief: { topic: 'OpenStack', learningGoals: ['理解原理'], learningOutcome: '掌握原理' }, currentQuestion: { ...question, id: 'background-1', stage: 'collecting_background', target: 'priorKnowledgeLevels' } }))
    await answering
    await flushPromises()
    expect(wrapper.text()).not.toContain('正在整理你的回答…')
  })

  it('shows the answer error after a failed command and keeps the action available', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot())
    const wrapper = mount(CourseDesignFlow)
    await wrapper.get('textarea[name="topic"]').setValue('学习 OpenStack')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('.course-option-chip').trigger('click')
    mockedRequest.mockRejectedValueOnce(new Error('回答服务不可用'))
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('回答服务不可用')
    expect(wrapper.get('button.primary').text()).toContain('下一步')
  })

  it('runs update_brief before generate_outline with explicit two-stage feedback', async () => {
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'reviewing_brief', revision: 3, briefRevision: 2, brief, currentQuestion: null, recommendedScale: 'standard' }))
    const wrapper = mount(CourseDesignFlow)
    await wrapper.get('textarea[name="topic"]').setValue('学习 Kubernetes')
    await wrapper.get('form').trigger('submit')
    mockedRequest.mockResolvedValueOnce(snapshot({ state: 'reviewing_brief', revision: 4, briefRevision: 3, brief, currentQuestion: null, recommendedScale: 'standard', selectedScale: 'standard' }))
    await wrapper.get('.course-scale-card').trigger('click')
    let resolveBrief!: (value: unknown) => void
    let resolveOutline!: (value: unknown) => void
    mockedRequest.mockReturnValueOnce(new Promise((resolve) => { resolveBrief = resolve }))
    mockedRequest.mockReturnValueOnce(new Promise((resolve) => { resolveOutline = resolve }))
    const generating = wrapper.get('button.primary').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('正在保存/整理课程需求…'))
    resolveBrief(snapshot({ state: 'reviewing_brief', revision: 5, briefRevision: 4, brief, currentQuestion: null, recommendedScale: 'standard', selectedScale: 'standard' }))
    await vi.waitFor(() => expect(wrapper.text()).toContain('正在生成课程大纲…'))
    resolveOutline(snapshot({ state: 'reviewing_outline', revision: 6, briefRevision: 4, brief, currentQuestion: null, recommendedScale: 'standard', selectedScale: 'standard', outline: [{ title: '原理', objective: '理解' }] }))
    await generating
    await flushPromises()
    const types = mockedRequest.mock.calls.slice(1).map((call) => JSON.parse(call[1]?.body as string).type)
    expect(types).toEqual(['select_scale', 'update_brief', 'generate_outline'])
  })
})
