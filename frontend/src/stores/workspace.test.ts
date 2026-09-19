import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useActivityStore } from './activity'
import { useLearningStore } from './learning'
import { useNotesStore } from './notes'
import { useWorkspaceStore } from './workspace'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

function installWindow(pathname = '/') {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      location: { pathname, search: '' },
      history: { replaceState: vi.fn(), pushState: vi.fn() },
    },
  })
}

describe('workspace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
    mockedRequest.mockResolvedValue([] as never)
    installWindow()
  })

  it('clears every domain when returning home and reloads history', async () => {
    const workspace = useWorkspaceStore()
    const learning = useLearningStore()
    const activity = useActivityStore()
    const notes = useNotesStore()
    learning.setSpace({ id: 'space-1' })
    learning.setCard({ id: 'card-1', sections: [{ id: 'section-1' }] })
    activity.activeActivity = { id: 'quiz-1' }
    notes.showNotes = true

    workspace.goHome()
    await Promise.resolve()

    expect(learning.space).toBeNull()
    expect(activity.activeActivity).toBeNull()
    expect(notes.showNotes).toBe(false)
    expect(window.history.replaceState).toHaveBeenCalledWith({}, '', '/')
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces')
  })

  it('switches sections by clearing activities, refreshing context and persisting runtime', async () => {
    const workspace = useWorkspaceStore()
    const learning = useLearningStore()
    learning.setSpace({ id: 'space-1' })
    learning.setCard({ id: 'card-1', sections: [{ id: 's1' }, { id: 's2' }] })
    learning.activeSection = 0

    await workspace.selectSection(1)

    expect(learning.activeSection).toBe(1)
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1/cards')
    expect(mockedRequest).toHaveBeenCalledWith('/cards/card-1/sections/s2/guidance')
    expect(mockedRequest).toHaveBeenCalledWith('/cards/card-1/sections/s2/activities')
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1/runtime', expect.objectContaining({
      method: 'PUT',
      body: expect.stringContaining('section_changed'),
    }))
  })

  it('resets an invalid study URL to home', async () => {
    installWindow('/study/missing/card/card-1')
    const workspace = useWorkspaceStore()
    const learning = useLearningStore()
    learning.history = [{ id: 'space-1' }]
    learning.setSpace({ id: 'space-1' })

    await workspace.restoreStudyRoute()

    expect(learning.space).toBeNull()
    expect(window.history.replaceState).toHaveBeenCalledWith({}, '', '/')
  })

  it('does not let a stale history request replace the current workspace', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    const first = new Promise((resolve) => { resolveFirst = resolve })
    mockedRequest.mockImplementation((path) => {
      if (path === '/cards/card-1') return first as never
      return Promise.resolve([]) as never
    })
    const workspace = useWorkspaceStore()
    const firstOpen = workspace.openHistory({ id: 'space-1', rootCardId: 'card-1' })
    const secondOpen = workspace.openHistory({ id: 'space-2', rootCardId: 'card-2' })
    await secondOpen
    resolveFirst?.({ id: 'card-1', sections: [] })
    await firstOpen

    expect(useLearningStore().space).toEqual({ id: 'space-2', rootCardId: 'card-2' })
  })

  it('ignores related-card results from an earlier section switch', async () => {
    // Keep the two related-card calls independently controllable.
    let releaseFirst: ((value: unknown) => void) | undefined
    let releaseSecond: ((value: unknown) => void) | undefined
    const first = new Promise((resolve) => { releaseFirst = resolve })
    const second = new Promise((resolve) => { releaseSecond = resolve })
    let relatedCall = 0
    mockedRequest.mockImplementation((path) => {
      if (path === '/learning-spaces/space-1/cards') {
        relatedCall += 1
        return (relatedCall === 1 ? first : second) as never
      }
      return Promise.resolve([]) as never
    })
    const workspace = useWorkspaceStore()
    const learning = useLearningStore()
    learning.setSpace({ id: 'space-1' })
    learning.setCard({ id: 'card-1', sections: [{ id: 's1' }, { id: 's2' }] })

    const firstSwitch = workspace.selectSection(0)
    await Promise.resolve()
    const secondSwitch = workspace.selectSection(1)
    await Promise.resolve()
    releaseSecond?.([{ id: 'related-current', cardType: 'related', parentCardId: 'card-1', parentSectionId: 's2' }])
    await secondSwitch
    releaseFirst?.([{ id: 'related-old', cardType: 'related', parentCardId: 'card-1', parentSectionId: 's1' }])
    await firstSwitch

    expect(learning.relatedCards).toEqual([
      { id: 'related-current', cardType: 'related', parentCardId: 'card-1', parentSectionId: 's2' },
    ])
  })
})
