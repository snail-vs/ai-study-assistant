// @vitest-environment jsdom
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { router } from './router'
import { request } from './api/client'
import { useConversationStore } from './stores/conversation'
import { useLearningStore } from './stores/learning'
import { useWorkspaceStore } from './stores/workspace'

vi.mock('./api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)
const space = { id: 'space-1', rootCardId: 'card-1', title: '测试课程' }
const card = {
  id: 'card-2',
  cardType: 'root',
  title: '测试章节',
  sections: [{ id: 'section-1', title: '第一节' }, { id: 'section-2', title: '第二节' }],
}

function mockWorkspaceApi() {
  mockedRequest.mockImplementation(async (path, options = {}) => {
    if (path === '/cards/card-2') return card
    if (path === '/learning-spaces/space-1/runtime') {
      if (options.method === 'PUT') return {}
      return { currentCardId: 'card-2', navigationStack: [] }
    }
    if (path === '/learning-spaces/space-1/cards') return []
    if (path === '/cards/card-2/proposals') return []
    if (path === '/cards/card-2/sections/section-2/guidance') return []
    if (path === '/cards/card-2/sections/section-1/guidance') return []
    if (String(path).endsWith('/guidance') && options.method === 'POST') return {}
    if (String(path).includes('/activities')) return []
    if (String(path).includes('/conversations')) return []
    if (String(path).includes('/messages')) return []
    if (String(path).includes('/runs/active')) return null
    return []
  })
}

afterEach(async () => {
  mockedRequest.mockReset()
  await router.replace({ name: 'home' })
})

describe('learning workflow integration', () => {
  it('restores a deep link into the requested course card and section', async () => {
    setActivePinia(createPinia())
    mockWorkspaceApi()
    const learning = useLearningStore()
    const workspace = useWorkspaceStore()
    learning.history = [space]

    await router.push({
      name: 'study',
      params: { spaceId: space.id, cardId: card.id },
      query: { section: '1' },
    })
    await workspace.restoreStudyRoute(router.currentRoute.value)

    expect(learning.space?.id).toBe(space.id)
    expect(learning.card?.id).toBe(card.id)
    expect(learning.activeSection).toBe(1)
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1/runtime', expect.objectContaining({ method: 'PUT' }))
  })

  it('refreshes section-scoped data and persists the section change', async () => {
    setActivePinia(createPinia())
    mockWorkspaceApi()
    const learning = useLearningStore()
    const workspace = useWorkspaceStore()
    learning.setSpace(space)
    learning.setCard(card)

    await workspace.selectSection(1)

    expect(learning.activeSection).toBe(1)
    expect(mockedRequest).toHaveBeenCalledWith('/cards/card-2/sections/section-2/activities')
    expect(mockedRequest).toHaveBeenCalledWith('/learning-spaces/space-1/runtime', expect.objectContaining({ method: 'PUT' }))
    const persistCall = mockedRequest.mock.calls.find(([path, options]) => path === '/learning-spaces/space-1/runtime' && options?.method === 'PUT')
    expect(JSON.parse(String(persistCall?.[1]?.body))).toMatchObject({ currentSectionId: 'section-2', eventType: 'section_changed' })
  })

  it('removes an empty assistant placeholder and resets state when SSE fails', async () => {
    setActivePinia(createPinia())
    const conversation = useConversationStore()
    conversation.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: run.failed\ndata: {"message":"服务失败"}\n\n'))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))

    await expect(conversation.sendMessage('请解释这一节', { id: 'section-1' })).resolves.toBe('服务失败')

    expect(conversation.messages).toHaveLength(1)
    expect(conversation.messages[0]).toMatchObject({ role: 'user', content: '请解释这一节' })
    expect(conversation.sideRun).toMatchObject({ active: false, phase: '', label: '' })
    expect(conversation.streamError).toBe('服务失败')
    vi.unstubAllGlobals()
  })
})
