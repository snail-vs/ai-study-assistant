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
      outline: [{ title: '基础语法', objective: '建立基础' }],
    })
    const store = useCourseDesignStore()

    await store.begin('我想学 Python')
    expect(store.phase).toBe('interview')
    expect(store.quickOptions).toEqual(['理解概念', '完成实际项目'])
    await store.answer('完成实际项目')
    expect(store.phase).toBe('review')
    expect(store.draftBrief.learningOutcome).toBe('完成数据分析项目')
    expect(store.outline).toHaveLength(1)
    expect(mockedRequest).toHaveBeenLastCalledWith('/course-design/turn', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"brief"'),
    }))
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
    expect(store.outline).toEqual([{ title: '概念基础' }])
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
    })
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
})
