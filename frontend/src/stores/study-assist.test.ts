import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useStudyAssistStore } from './study-assist'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)
const card = { id: 'card-1' }
const section = { id: 'section-1' }

describe('study assist store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('generates guidance when empty, then reads it again', async () => {
    mockedRequest
      .mockResolvedValueOnce([] as never)
      .mockResolvedValueOnce({ status: 'queued' } as never)
      .mockResolvedValueOnce([{ id: 'guidance-1', sectionId: 'section-1' }] as never)
    const store = useStudyAssistStore()

    await store.loadTeacherGuidance(card, section)

    expect(mockedRequest).toHaveBeenNthCalledWith(1, '/cards/card-1/sections/section-1/guidance')
    expect(mockedRequest).toHaveBeenNthCalledWith(2, '/cards/card-1/sections/section-1/guidance', { method: 'POST' })
    expect(store.teacherGuidance).toEqual([{ id: 'guidance-1', sectionId: 'section-1' }])
  })

  it('does not let an old chapter load overwrite the current chapter', async () => {
    let resolveOld!: (value: unknown) => void
    const oldRequest = new Promise((resolve) => { resolveOld = resolve })
    mockedRequest.mockReturnValueOnce(oldRequest as never)
    const store = useStudyAssistStore()
    const oldLoad = store.loadTeacherGuidance(card, section)

    store.setContext(card, { id: 'section-2' })
    resolveOld([{ id: 'old-guidance' }])
    await oldLoad

    expect(store.sectionId).toBe('section-2')
    expect(store.teacherGuidance).toEqual([])
  })

  it('filters recommendations by chapter and preserves them on a failed refresh', async () => {
    mockedRequest.mockResolvedValueOnce([
      { proposalId: 'one', sectionId: 'section-1' },
      { proposalId: 'other', sectionId: 'section-2' },
    ] as never)
    const store = useStudyAssistStore()
    await store.loadRecommendations(card, section)
    expect(store.recommendations).toEqual([{ proposalId: 'one', sectionId: 'section-1' }])

    mockedRequest.mockRejectedValueOnce(new Error('recommendation unavailable'))
    await expect(store.loadRecommendations(card, section)).rejects.toThrow('recommendation unavailable')
    expect(store.recommendations).toEqual([{ proposalId: 'one', sectionId: 'section-1' }])
    expect(store.recommendationError).toBe('recommendation unavailable')
  })

  it('merges SSE recommendations and guidance updates by stable id', () => {
    const store = useStudyAssistStore()
    store.setContext(card, section)
    store.handleStreamEvent('related_card.proposed', { proposalId: 'proposal-1', title: '初始' })
    store.handleStreamEvent('related_card.proposed', { proposalId: 'proposal-1', title: '更新' })
    store.handleStreamEvent('guidance.updated', { id: 'guidance-1', content: '第一版' })
    store.handleStreamEvent('guidance.updated', { id: 'guidance-1', content: '第二版' })

    expect(store.proposal).toMatchObject({ title: '更新' })
    expect(store.recommendations).toEqual([{ proposalId: 'proposal-1', title: '更新' }])
    expect(store.teacherGuidance).toEqual([{ id: 'guidance-1', content: '第二版' }])
  })

  it('resets all chapter-scoped state and errors', () => {
    const store = useStudyAssistStore()
    store.setContext(card, section)
    store.handleStreamEvent('related_card.proposed', { proposalId: 'proposal-1' })
    store.handleStreamEvent('guidance.failed', { message: 'failed' })
    store.setSelectedRecommendation({ proposalId: 'proposal-1' })

    store.reset()

    expect(store.cardId).toBe('')
    expect(store.sectionId).toBe('')
    expect(store.teacherGuidance).toEqual([])
    expect(store.recommendations).toEqual([])
    expect(store.proposal).toBeNull()
    expect(store.selectedRecommendation).toBeNull()
    expect(store.guidanceError).toBe('')
  })
})
