import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useConversationStore } from './conversation'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

function streamResponse(blocks: string[]) {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(blocks.join('\n\n') + '\n\n'))
      controller.close()
    },
  })
  return { ok: true, body } as Response
}

describe('conversation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('loads conversations and excludes internal messages while restoring an active run', async () => {
    mockedRequest
      .mockResolvedValueOnce([
        { id: 'conversation-1', sectionId: 'section-1', title: '讨论' },
      ] as never)
      .mockResolvedValueOnce([
        { id: 'internal', visibility: 'internal', content: 'secret' },
        { id: 'message-1', role: 'user', content: '问题', visibility: 'public' },
      ] as never)
      .mockResolvedValueOnce({ status: 'running', phase: 'guiding' } as never)
    const store = useConversationStore()

    await store.loadSectionConversations({ id: 'card-1' }, { id: 'section-1' })

    expect(store.activeConversation?.id).toBe('conversation-1')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].content).toBe('问题')
    expect(store.messages[1].pending).toBe(true)
    expect(store.sideRun).toEqual({ active: true, phase: 'guiding', label: '主线老师正在总结引导' })
  })

  it('accumulates SSE deltas and updates proposal and guidance state', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.started\ndata: {"phase":"waiting","label":"开始"}',
      'event: message.started\ndata: {"senderName":"主线老师"}',
      'event: message.delta\ndata: {"delta":"你好"}',
      'event: related_card.proposed\ndata: {"proposalId":"proposal-1"}',
      'event: guidance.updated\ndata: {"id":"guidance-1"}',
      'event: run.completed\ndata: {}',
    ]))
    const store = useConversationStore()
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await store.sendMessage('问题', { id: 'section-1' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/conversations/conversation-1/messages/stream', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
      body: JSON.stringify({ content: '问题', sectionId: 'section-1' }),
    }))
    expect(store.messages[1]).toMatchObject({ content: '你好', pending: false, senderName: '主线老师' })
    expect(store.proposal).toEqual({ proposalId: 'proposal-1' })
    expect(store.recommendations).toEqual([{ proposalId: 'proposal-1' }])
    expect(store.teacherGuidance).toEqual([{ id: 'guidance-1' }])
    expect(store.sideRun).toEqual({ active: false, phase: '', label: '' })
  })

  it('removes an unanswered assistant message and retains stream failure state', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.failed\ndata: {"message":"provider down"}',
    ]))
    const store = useConversationStore()
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await store.sendMessage('问题', { id: 'section-1' })

    expect(store.messages).toEqual([{ role: 'user', content: '问题' }])
    expect(store.streamError).toBe('provider down')
    expect(store.sideRun.active).toBe(false)
  })

  it('clears highlighted messages after the UI highlight window', () => {
    vi.useFakeTimers()
    const store = useConversationStore()
    store.highlightMessages(['message-1', 'message-2'])
    expect(store.highlightedMessageIds).toEqual(['message-1', 'message-2'])

    vi.advanceTimersByTime(2200)

    expect(store.highlightedMessageIds).toEqual([])
  })

  it('rejects sending to a conversation from another section', async () => {
    const store = useConversationStore()
    store.activeConversation = { id: 'conversation-1', sectionId: 'other-section' }

    await expect(store.sendMessage('问题', { id: 'section-1' })).rejects.toThrow('该讨论所属的章节')
  })
})
