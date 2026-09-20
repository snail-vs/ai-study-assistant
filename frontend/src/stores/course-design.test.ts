import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCourseDesignStore } from './course-design'
import { request } from '../api/client'

vi.mock('../api/client', () => ({ request: vi.fn() }))
const mockedRequest = vi.mocked(request)

describe('course design store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('asks adaptive questions and moves to review after a structured response', async () => {
    mockedRequest.mockResolvedValueOnce({
      assistantMessage: '你希望学完后能做到什么？',
      quickOptions: ['理解概念', '完成实际项目'],
      brief: { topic: 'Python' },
      recommendedScale: 'standard',
    })
    mockedRequest.mockResolvedValueOnce({
      message: '好的，这是课程安排。',
      ready: true,
      brief: { learningOutcome: '完成数据分析项目' },
    })
    mockedRequest.mockResolvedValueOnce({ outline: [{ title: '基础语法', objective: '建立基础' }] })
    const store = useCourseDesignStore()

    await store.begin('我想学 Python')
    expect(store.phase).toBe('interview')
    expect(store.quickOptions).toEqual(['理解概念', '完成实际项目'])
    await store.answer('完成实际项目')
    expect(store.phase).toBe('review')
    expect(store.draftBrief.learningOutcome).toBe('完成数据分析项目')
    expect(store.selectedScale).toBe(null)
    store.chooseScale('standard')
    await store.generateOutline()
    expect(store.outline).toHaveLength(1)
    expect(mockedRequest.mock.calls[1]).toEqual(['/course-design/turn', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"brief"'),
    })])
    const firstPayload = JSON.parse(mockedRequest.mock.calls[0][1]?.body as string)
    expect(firstPayload.messages).toEqual([{ role: 'user', content: '我想学 Python' }])
    expect(firstPayload).not.toHaveProperty('courseScale')
  })

  it('keeps interviewing when an early draft outline is returned', async () => {
    mockedRequest.mockResolvedValueOnce({
      assistantMessage: '你打算把它用在什么场景？',
      ready: false,
      outline: [{ title: '概念基础' }],
      quickOptions: ['工作', '个人兴趣'],
    })
    const store = useCourseDesignStore()

    await store.begin('我想学 Kubernetes')

    expect(store.phase).toBe('interview')
    expect(store.outline).toEqual([])
    expect(store.quickOptions).toEqual(['工作', '个人兴趣'])
  })

  it('builds a scale-aware final creation payload', () => {
    const store = useCourseDesignStore()
    store.goal = '学习 Kubernetes'
    store.editBrief({ topic: 'Kubernetes', learningOutcome: '能部署服务' })
    store.chooseScale('series')

    expect(store.payload()).toEqual({
      title: 'Kubernetes',
      learningGoal: '学习 Kubernetes',
      courseBrief: { topic: 'Kubernetes', learningOutcome: '能部署服务', courseScale: 'series' },
      courseScale: 'series',
      courseOutline: [],
    })
  })

  it('carries structured learning goals and background details and invalidates a stale outline', async () => {
    const store = useCourseDesignStore()
    store.goal = '学习 OpenStack'
    store.editBrief({ topic: 'OpenStack', learningGoals: ['理解整体架构', '完成部署实践'], learningGoalDetails: '希望能定位服务故障', priorKnowledgeLevels: ['了解基本概念', '有相关实践'], priorKnowledgeDetails: '用过 Linux 和虚拟机' })
    store.chooseScale('quick')
    mockedRequest.mockResolvedValueOnce({ outline: [{ title: '架构', objective: '理解组件关系' }] })
    await store.generateOutline()
    store.confirmOutline()
    expect(store.outlineConfirmed).toBe(true)

    store.editBrief({ learningGoals: ['理解整体架构'] })
    expect(store.outline).toEqual([])
    expect(store.outlineConfirmed).toBe(false)
    expect(store.payload().courseBrief).toMatchObject({
      learningGoals: ['理解整体架构'],
      learningGoalDetails: '希望能定位服务故障',
      priorKnowledgeLevels: ['了解基本概念', '有相关实践'],
      priorKnowledgeDetails: '用过 Linux 和虚拟机',
    })
  })

  it('generates a scale-specific outline and exposes failures for retry', async () => {
    const store = useCourseDesignStore()
    store.goal = '学习 Python'
    store.editBrief({ topic: 'Python' })
    store.chooseScale('quick')
    mockedRequest.mockResolvedValueOnce({ outline: [{ title: '快速入门' }] })

    await store.generateOutline()

    expect(store.outline).toEqual([{ title: '快速入门' }])
    const payload = JSON.parse(mockedRequest.mock.calls[0][1]?.body as string)
    expect(payload).toEqual({ brief: { topic: 'Python', courseScale: 'quick' }, courseScale: 'quick' })

    mockedRequest.mockRejectedValueOnce(new Error('大纲服务不可用'))
    await expect(store.generateOutline()).rejects.toThrow('大纲服务不可用')
    expect(store.outlineError).toBe('大纲服务不可用')
    expect(store.outline).toEqual([])
  })

  it('revises the outline conversationally and requires explicit confirmation', async () => {
    const store = useCourseDesignStore()
    store.goal = '学习 Git'
    store.editBrief({ topic: 'Git' })
    store.chooseScale('quick')
    mockedRequest.mockResolvedValueOnce({ outline: [{ title: '基础' }] })
    await store.generateOutline()
    expect(store.outlineConfirmed).toBe(false)
    mockedRequest.mockResolvedValueOnce({ outline: [{ title: '基础与实战' }], assistantMessage: '已加入实战内容。' })

    await store.reviseOutline('增加一个实战项目')

    expect(store.outline).toEqual([{ title: '基础与实战' }])
    expect(store.outlineConfirmed).toBe(false)
    expect(store.revisionMessages).toEqual([
      { role: 'user', content: '增加一个实战项目' },
      { role: 'assistant', content: '已加入实战内容。' },
    ])
    const payload = JSON.parse(mockedRequest.mock.calls[1][1]?.body as string)
    expect(payload).toMatchObject({ courseScale: 'quick', feedback: '增加一个实战项目', currentOutline: [{ title: '基础' }] })
    store.confirmOutline()
    expect(store.outlineConfirmed).toBe(true)
  })

  it('supports the direct-generation escape hatch', async () => {
    mockedRequest.mockResolvedValueOnce({ assistantMessage: '想重点了解哪一部分？' })
    mockedRequest.mockResolvedValueOnce({ ready: true })
    const store = useCourseDesignStore()
    await store.begin('快速了解 Git')
    await store.generateDirectly()
    expect(store.phase).toBe('review')
    expect(mockedRequest).toHaveBeenCalledTimes(2)
  })

  it('hides answer controls while the AI is preparing the first question', async () => {
    let resolveRequest!: (value: unknown) => void
    mockedRequest.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve }))
    const store = useCourseDesignStore()
    const pending = store.begin('我想系统了解 OpenStack')

    expect(store.waitingForAI).toBe(true)
    expect(store.waitingForUser).toBe(false)
    expect(store.messages[store.messages.length - 1]).toMatchObject({ role: 'assistant', pending: true })
    resolveRequest({ question: '你希望重点理解哪些内容？', assistantMessage: '先确认学习重点。', quickOptions: ['架构', '实现流程'] })
    await pending
    expect(store.waitingForAI).toBe(false)
    expect(store.waitingForUser).toBe(true)
  })

  it('combines an assistant lead-in and question into one assistant turn', async () => {
    mockedRequest.mockResolvedValueOnce({ assistantMessage: '为了安排合适的路径，', question: '你目前对 OpenStack 的基础如何？' })
    const store = useCourseDesignStore()
    await store.begin('我想了解 OpenStack')
    expect(store.messages.filter((message) => message.role === 'assistant')).toHaveLength(1)
    expect(store.messages[store.messages.length - 1]?.content).toBe('为了安排合适的路径，\n你目前对 OpenStack 的基础如何？')
  })

  it('keeps the answer controls hidden after failure and retries without duplicating the goal', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('服务暂时不可用'))
    mockedRequest.mockResolvedValueOnce({ question: '你希望学完后做到什么？' })
    const store = useCourseDesignStore()
    await expect(store.begin('我想了解 OpenStack')).rejects.toThrow('服务暂时不可用')
    expect(store.error).toBe('服务暂时不可用')
    expect(store.waitingForUser).toBe(false)
    await store.retry()
    expect(store.error).toBe('')
    expect(store.messages.filter((message) => message.role === 'user')).toEqual([{ role: 'user', content: '我想了解 OpenStack' }])
    expect(mockedRequest).toHaveBeenCalledTimes(2)
  })
})
