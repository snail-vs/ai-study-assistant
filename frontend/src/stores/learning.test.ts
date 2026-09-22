import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useLearningStore } from './learning'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

describe('learning store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
    vi.useRealTimers()
  })

  it('loads spaces and their cards while starting polling for pending generation', async () => {
    vi.useFakeTimers()
    mockedRequest
      .mockResolvedValueOnce({ items: [{ id: 'space-1', title: 'Kubernetes', generationStatus: 'running' }] } as never)
      .mockResolvedValueOnce([{ id: 'card-1', title: 'Root' }] as never)
      .mockResolvedValueOnce({ items: [{ id: 'space-1', title: 'Kubernetes', generationStatus: 'completed' }] } as never)
      .mockResolvedValueOnce([{ id: 'card-1', title: 'Root' }] as never)
    const store = useLearningStore()

    await store.loadHistory()
    expect(store.history).toHaveLength(1)
    expect(store.historyCards).toEqual({ 'space-1': [{ id: 'card-1', title: 'Root' }] })

    await vi.advanceTimersByTimeAsync(3000)
    expect(store.generationNotice).toContain('已生成完成')
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces')
    store.stopGenerationPolling()
  })

  it('maintains navigation context and derives the active section', () => {
    const store = useLearningStore()
    store.setSpace({ id: 'space-1' })
    store.setCard({ id: 'card-1', sections: [{ id: 'section-1' }, { id: 'section-2' }] }, { root: true })
    store.activeSection = 1
    store.pushNavigation({ cardId: 'card-1', sectionId: 'section-1' })

    expect(store.section).toEqual({ id: 'section-2' })
    expect(store.rootCard).toEqual(store.card)
    expect(store.popNavigation()).toEqual({ cardId: 'card-1', sectionId: 'section-1' })
    expect(store.navigationStack).toEqual([])
  })

  it('refreshes the open card as background section generation progresses', async () => {
    mockedRequest
      .mockResolvedValueOnce({ items: [{ id: 'space-1', generationStatus: 'running' }] } as never)
      .mockResolvedValueOnce([{
        id: 'card-1', sections: [{ id: 'section-1', generationStatus: 'completed', contentMarkdown: '正文' }],
      }] as never)
    const store = useLearningStore()
    store.setSpace({ id: 'space-1', generationStatus: 'running' })
    store.setCard({
      id: 'card-1', sections: [{ id: 'section-1', generationStatus: 'generating', contentMarkdown: '' }],
    }, { root: true })

    await store.loadHistory()

    expect(store.section).toMatchObject({ generationStatus: 'completed', contentMarkdown: '正文' })
    expect(store.rootCard).toBe(store.card)
    store.stopGenerationPolling()
  })

  it('deletes a failed space and removes its cached history cards', async () => {
    mockedRequest.mockResolvedValueOnce({ status: 'deleted', spaceId: 'space-1' } as never)
    const store = useLearningStore()
    store.history = [{ id: 'space-1', generationStatus: 'failed' }, { id: 'space-2' }]
    store.historyCards = { 'space-1': [{ id: 'card-1' }], 'space-2': [{ id: 'card-2' }] }
    store.editingFailedSpace = store.history[0]

    await store.deleteFailedSpace(store.history[0])

    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1', { method: 'DELETE' })
    expect(store.history).toEqual([{ id: 'space-2' }])
    expect(store.historyCards).toEqual({ 'space-2': [{ id: 'card-2' }] })
    expect(store.editingFailedSpace).toBeNull()
  })

  it('retries a failed space with its saved course plan instead of starting intake again', async () => {
    mockedRequest
      .mockResolvedValueOnce({ id: 'space-1', generationStatus: 'queued' } as never)
      .mockResolvedValueOnce({ items: [{ id: 'space-1', title: 'Go', generationStatus: 'queued' }] } as never)
      .mockResolvedValueOnce([] as never)
    const store = useLearningStore()
    const failedSpace = {
      id: 'space-1', title: 'Go', learningGoal: '掌握 Go', courseBrief: { audience: '初学者' },
      courseScale: 'compact', courseOutline: [{ title: '基础' }], generationStatus: 'failed',
    }
    store.history = [failedSpace]

    await store.retryFailedSpace(failedSpace)

    expect(mockedRequest).toHaveBeenNthCalledWith(1, '/learning-spaces/space-1/generation', {
      method: 'PUT',
      body: JSON.stringify({
        title: 'Go', learningGoal: '掌握 Go', courseBrief: { audience: '初学者' },
        courseScale: 'compact', courseOutline: [{ title: '基础' }],
      }),
    })
    expect(store.generationNotice).toContain('已重新提交')
    expect(store.history[0].generationStatus).toBe('queued')
  })

  it('persists runtime payload without making navigation fail on an API error', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('offline'))
    const store = useLearningStore()
    store.setSpace({ id: 'space-1' })
    store.setCard({ id: 'card-1', sections: [{ id: 'section-1' }] })
    store.pushNavigation({ cardId: 'root-1', sectionId: 'section-1' })

    await expect(store.persistRuntime('branch_entered')).resolves.toBeUndefined()
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1/runtime', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({
        currentCardId: 'card-1', currentSectionId: 'section-1',
        navigationStack: [{ cardId: 'root-1', sectionId: 'section-1' }], eventType: 'branch_entered',
      }),
    }))
  })

  it('clears workspace state while keeping loaded history', () => {
    const store = useLearningStore()
    store.history = [{ id: 'space-1' }]
    store.setSpace({ id: 'space-1' })
    store.setCard({ id: 'card-1' }, { root: true })
    store.relatedCards = [{ id: 'related-1' }]
    store.pushNavigation({ cardId: 'card-1' })

    store.clearWorkspace()

    expect(store.space).toBeNull()
    expect(store.card).toBeNull()
    expect(store.rootCard).toBeNull()
    expect(store.relatedCards).toEqual([])
    expect(store.history).toEqual([{ id: 'space-1' }])
  })
})
