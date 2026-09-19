import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useActivityStore } from './activity'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

const activity = {
  id: 'activity-1',
  activityType: 'quiz',
  status: 'ready',
  questions: [
    { id: 'q1', type: 'single_choice', options: [{ id: 'a', text: 'A' }] },
    { id: 'q2', type: 'short_answer' },
  ],
}

describe('activity store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('generates a quiz when the section has no ready activity', async () => {
    mockedRequest.mockResolvedValueOnce([] as never).mockResolvedValueOnce(activity as never)
    const store = useActivityStore()

    await store.loadSectionActivities({ id: 'card-1' }, { id: 'section-1' })
    await store.openQuiz({ id: 'card-1' }, { id: 'section-1' })

    expect(store.activeActivity).toEqual(activity)
    expect(store.answers).toEqual({ q1: null, q2: '' })
    expect(store.loading).toBe(false)
  })

  it('persists generated quiz and exposes generation failure without leaving loading state', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('provider unavailable'))
    const store = useActivityStore()

    await expect(store.openQuiz({ id: 'card-1' }, { id: 'section-1' })).rejects.toThrow('provider unavailable')
    expect(store.loading).toBe(false)
    expect(store.activeActivity).toBeNull()
  })

  it('submits answers and updates the activity latest attempt', async () => {
    mockedRequest.mockResolvedValueOnce({ id: 'attempt-1', score: 80, followUp: { status: 'completed' } } as never)
    const store = useActivityStore()
    store.activeActivity = activity
    store.answers = { q1: 'a', q2: 'because' }
    store.activities = [activity]

    await expect(store.submitQuiz()).resolves.toMatchObject({ id: 'attempt-1', score: 80 })
    expect(store.result).toMatchObject({ id: 'attempt-1' })
    expect(store.activeActivity?.latestAttempt).toMatchObject({ id: 'attempt-1' })
    expect(store.submitting).toBe(false)
    expect(mockedRequest).toHaveBeenCalledWith('/activities/activity-1/attempts', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ answers: { q1: 'a', q2: 'because' } }),
    }))
  })

  it('keeps the previous result when follow-up submission fails', async () => {
    const previous = { id: 'attempt-1', score: 50, followUp: { status: 'pending', prompt: 'Explain' } }
    mockedRequest.mockRejectedValueOnce(new Error('evaluation unavailable'))
    const store = useActivityStore()
    store.activeActivity = activity
    store.result = previous
    store.followUpAnswer = 'answer'

    await expect(store.submitFollowUp()).rejects.toThrow('evaluation unavailable')
    expect(store.result).toEqual(previous)
    expect(store.followUpAnswer).toBe('answer')
    expect(store.followUpSubmitting).toBe(false)
  })

  it('clears activity state when switching to another section', async () => {
    mockedRequest.mockResolvedValueOnce([activity] as never)
    const store = useActivityStore()
    store.activeActivity = activity
    store.result = { id: 'attempt-1' }
    store.answers = { q1: 'a' }
    store.followUpAnswer = 'pending answer'

    await store.loadSectionActivities(null, null)

    expect(store.activities).toEqual([])
    expect(store.activeActivity).toBeNull()
    expect(store.result).toBeNull()
    expect(store.answers).toEqual({})
    expect(store.followUpAnswer).toBe('')
  })
})
