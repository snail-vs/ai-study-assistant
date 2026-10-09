import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useConversationStore } from './conversation'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)
const conversation = { id: 'conversation-1', sectionId: 'section-1' }
const failedRun = {
  id: 'run-1', status: 'failed', phase: 'answering', retryable: true,
  questionMessageId: 'question-1', answerMessageId: 'partial-1', errorMessage: '连接中断',
}
const failedMessages = [
  { id: 'history-question', role: 'user', content: '旧问题' },
  { id: 'history-answer', role: 'assistant', content: '完整历史回答' },
  { id: 'question-1', role: 'user', content: '原问题' },
  { id: 'partial-1', role: 'assistant', content: '残缺回答' },
]

function streamResponse(blocks: string[], separator = '\n\n') {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(blocks.join(separator)))
      controller.close()
    },
  })
  return { ok: true, body } as Response
}

describe('conversation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset().mockResolvedValue(null as never)
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
      .mockResolvedValueOnce({ status: 'running', phase: 'answering' } as never)
    const store = useConversationStore()

    await store.loadSectionConversations({ id: 'card-1' }, { id: 'section-1' })

    expect(store.activeConversation?.id).toBe('conversation-1')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].content).toBe('问题')
    expect(store.messages[1].pending).toBe(true)
    expect(store.sideRun).toEqual({ active: true, phase: 'answering', label: 'AI 正在处理中' })
    expect(mockedRequest).toHaveBeenCalledWith('/conversations/conversation-1/runs/latest')
  })

  it('accumulates SSE deltas and updates proposal and guidance state', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1","phase":"waiting","label":"开始"}',
      'event: message.started\ndata: {"messageId":"answer-1","senderName":"主线老师"}',
      'event: message.delta\ndata: {"delta":"你好"}',
      'event: related_card.proposed\ndata: {"proposalId":"proposal-1"}',
      'event: guidance.updated\ndata: {"id":"guidance-1"}',
      'event: run.completed\ndata: {}',
      'event: message.completed\ndata: {}',
    ]))
    const store = useConversationStore()
    const assistEvents: Array<[string, Record<string, any>]> = []
    store.setStudyAssistEventHandler((event, data) => assistEvents.push([event, data]))
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await store.sendMessage('问题', { id: 'section-1' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/conversations/conversation-1/messages/stream', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
      body: JSON.stringify({ content: '问题', sectionId: 'section-1' }),
    }))
    expect(store.messages[0]).toMatchObject({ id: 'question-1', role: 'user', content: '问题' })
    expect(store.messages[1]).toMatchObject({ id: 'answer-1', content: '你好', pending: false, senderName: '主线老师' })
    expect(assistEvents).toEqual([
      ['related_card.proposed', { proposalId: 'proposal-1' }],
      ['guidance.updated', { id: 'guidance-1' }],
    ])
    expect(store.sideRun).toEqual({ active: false, phase: '', label: '' })
  })

  it('removes an unanswered assistant message and retains stream failure state', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.failed\ndata: {"message":"provider down"}',
      'event: message.completed\ndata: {}',
    ]))
    const store = useConversationStore()
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await store.sendMessage('问题', { id: 'section-1' })

    expect(store.messages).toEqual([{ role: 'user', content: '问题' }])
    expect(store.streamError).toBe('provider down')
    expect(store.sideRun.active).toBe(false)
  })

  it('returns the HTTP status and request ID when the stream endpoint fails', async () => {
    const response = new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' })
    response.headers.set('x-request-id', 'request-42')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response)
    const store = useConversationStore()
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await expect(store.sendMessage('问题', { id: 'section-1' })).rejects.toThrow(
      'AI 流式连接失败 [HTTP 502]（请求 ID: request-42）',
    )
  })

  it('keeps the visible guidance failure message while forwarding the event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: guidance.failed\ndata: {"message":"guidance unavailable"}',
      'event: run.failed\ndata: {"phase":"guiding","retryable":false,"message":"课程导师引导失败：guidance unavailable"}',
      'event: message.completed\ndata: {}',
    ]))
    const events: Array<[string, Record<string, any>]> = []
    const store = useConversationStore()
    store.setStudyAssistEventHandler((event, data) => events.push([event, data]))
    store.activeConversation = { id: 'conversation-1', sectionId: 'section-1' }

    await store.sendMessage('问题', { id: 'section-1' })

    expect(store.streamError).toBe('课程导师引导失败：guidance unavailable')
    expect(events).toEqual([['guidance.failed', { message: 'guidance unavailable' }]])
    expect(store.retryRun).toBeNull()
    expect(store.canRetry).toBe(false)
  })

  it.each(['failed', 'expired'])('restores a %s latest answer with retry eligibility after refresh', async (status) => {
    mockedRequest.mockResolvedValueOnce(failedMessages as never)
      .mockResolvedValueOnce({ ...failedRun, status } as never)
    const store = useConversationStore()
    store.activeConversation = conversation

    const loading = store.loadConversationMessages(conversation)
    expect(store.restoringRetry).toBe(true)
    expect(store.canRetry).toBe(false)
    await loading

    expect(store.retryRun).toMatchObject({ id: 'run-1', status, questionMessageId: 'question-1' })
    expect(store.canRetry).toBe(true)
    expect(store.streamError).toBe('连接中断')
    expect(store.messages).toHaveLength(4)
    expect(store.messages[1].incomplete).toBe(false)
    expect(store.messages[3].incomplete).toBe(true)
  })

  it('preserves the original turn until retry acceptance, rejects double clicks, and replaces only the partial', async () => {
    const store = useConversationStore()
    store.activeConversation = conversation
    store.messages = failedMessages.map((message) => ({ ...message }))
    store.latestRun = { ...failedRun }
    let accept!: (response: Response) => void
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise((resolve) => { accept = resolve }))

    const retry = store.retryMessage({ id: 'section-1' })
    expect(store.sideRun.active).toBe(true)
    expect(store.canRetry).toBe(false)
    expect(store.messages.map((message) => message.content)).toEqual(failedMessages.map((message) => message.content))
    await store.retryMessage({ id: 'section-1' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/conversations/conversation-1/runs/run-1/retry', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock.mock.calls[0][1]).not.toHaveProperty('body')

    accept(streamResponse([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1","replacedMessageId":"partial-1","phase":"waiting"}',
      'event: message.started\ndata: {"messageId":"answer-2"}',
      'event: message.delta\ndata: {"delta":"新的"}',
      'event: message.delta\ndata: {"delta":"完整回答"}',
      'event: run.completed\ndata: {}',
      'event: message.completed\ndata: {}',
    ]))
    await retry

    expect(store.messages).toHaveLength(4)
    expect(store.messages.filter((message) => message.role === 'user').map((message) => message.id)).toEqual(['history-question', 'question-1'])
    expect(store.messages[1]).toMatchObject({ id: 'history-answer', content: '完整历史回答' })
    expect(store.messages[3]).toMatchObject({ id: 'answer-2', content: '新的完整回答', pending: false, incomplete: false })
    expect(store.streamError).toBe('')
    expect(store.retryRun).toBeNull()
    expect(store.sideRun.active).toBe(false)
  })

  it('preserves a partial when the server rejects retry before acceptance', async () => {
    const store = useConversationStore()
    store.activeConversation = conversation
    store.messages = failedMessages.map((message) => ({ ...message }))
    store.latestRun = { ...failedRun }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"不能重试"}', { status: 409 }))
    mockedRequest.mockResolvedValueOnce(failedRun as never)

    await expect(store.retryMessage({ id: 'section-1' })).rejects.toThrow('不能重试')

    expect(store.messages.map((message) => message.content)).toEqual(failedMessages.map((message) => message.content))
    expect(store.messages[3].incomplete).toBe(true)
    expect(store.canRetry).toBe(true)
  })

  it('retries a waiting failure with no partial without duplicating its question', async () => {
    const store = useConversationStore()
    store.activeConversation = conversation
    store.messages = [{ id: 'question-1', role: 'user', content: '原问题' }]
    store.latestRun = { ...failedRun, phase: 'waiting', answerMessageId: null }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1","replacedMessageId":null}',
      'event: message.started\ndata: {"messageId":"answer-2"}',
      'event: message.delta\ndata: {"delta":"完整回答"}',
      'event: run.completed\ndata: {}',
      'event: message.completed\ndata: {}',
    ]))

    await store.retryMessage({ id: 'section-1' })

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]).toMatchObject({ id: 'question-1', content: '原问题' })
    expect(store.messages[1]).toMatchObject({ id: 'answer-2', content: '完整回答' })
  })

  it('exposes run.failed eligibility immediately but keeps retry disabled until the request ends', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start(value) { controller = value } })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body))
    const store = useConversationStore()
    store.activeConversation = conversation
    const sending = store.sendMessage('原问题', { id: 'section-1' })
    controller.enqueue(new TextEncoder().encode([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1"}',
      'event: message.started\ndata: {"messageId":"partial-1"}',
      'event: message.delta\ndata: {"delta":"残缺回答"}',
      'event: run.failed\ndata: {"runId":"run-1","phase":"answering","retryable":true,"questionMessageId":"question-1","answerMessageId":"partial-1","message":"连接中断"}',
      '',
    ].join('\n\n')))
    await vi.waitFor(() => expect(store.retryRun?.id).toBe('run-1'))
    expect(store.messages[1].incomplete).toBe(true)
    expect(store.canRetry).toBe(false)
    expect(mockedRequest).not.toHaveBeenCalled()

    controller.enqueue(new TextEncoder().encode('event: message.completed\ndata: {}\n\n'))
    controller.close()
    await sending
    expect(store.canRetry).toBe(true)
    expect(store.streamError).toBe('连接中断')
  })

  it('treats unexpected EOF as interruption and recovers the persisted partial from latest run', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1"}',
      'event: message.started\ndata: {"messageId":"partial-1"}',
      'event: message.delta\ndata: {"delta":"残缺回答"}',
    ]))
    mockedRequest.mockResolvedValueOnce(failedRun as never)
    const store = useConversationStore()
    store.activeConversation = conversation

    await expect(store.sendMessage('原问题', { id: 'section-1' })).rejects.toThrow('连接已中断')

    expect(mockedRequest).toHaveBeenCalledWith('/conversations/conversation-1/runs/latest')
    expect(store.canRetry).toBe(true)
    expect(store.messages[0]).toMatchObject({ id: 'question-1', content: '原问题' })
    expect(store.messages[1]).toMatchObject({ id: 'partial-1', content: '残缺回答', incomplete: true, pending: false })
  })

  it('does not accept run.completed alone as the terminal SSE event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse([
      'event: message.delta\ndata: {"delta":"完整回答"}',
      'event: run.completed\ndata: {}',
    ]))
    mockedRequest.mockResolvedValueOnce({ ...failedRun, status: 'completed', retryable: false } as never)
    const store = useConversationStore()
    store.activeConversation = conversation

    await expect(store.sendMessage('问题', { id: 'section-1' })).rejects.toThrow('连接已中断')
    expect(store.canRetry).toBe(false)
    expect(store.messages[1].incomplete).toBe(false)
  })

  it('recovers retry status after a network exception without keeping an empty placeholder', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network disconnected'))
    mockedRequest.mockResolvedValueOnce({ ...failedRun, phase: 'planning', answerMessageId: null } as never)
    const store = useConversationStore()
    store.activeConversation = conversation

    await expect(store.sendMessage('原问题', { id: 'section-1' })).rejects.toThrow('network disconnected')

    expect(store.messages).toHaveLength(1)
    expect(store.messages[0]).toMatchObject({ id: 'question-1', content: '原问题' })
    expect(store.canRetry).toBe(true)
    expect(store.restoringRetry).toBe(false)
  })

  it('reconciles a retry accepted by the server when the connection loses run.started', async () => {
    const store = useConversationStore()
    store.activeConversation = conversation
    store.messages = failedMessages.map((message) => ({ ...message }))
    store.latestRun = { ...failedRun }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(streamResponse([]))
    mockedRequest.mockResolvedValueOnce({ ...failedRun, answerMessageId: 'partial-2' } as never)
      .mockResolvedValueOnce([
        ...failedMessages.slice(0, 3),
        { id: 'partial-2', role: 'assistant', content: '重试后的残缺回答' },
      ] as never)

    await expect(store.retryMessage({ id: 'section-1' })).rejects.toThrow('连接已中断')

    expect(store.messages.map((message) => message.id)).toEqual([
      'history-question', 'history-answer', 'question-1', 'partial-2',
    ])
    expect(store.messages[3].incomplete).toBe(true)
    fetchMock.mockResolvedValueOnce(streamResponse([
      'event: run.started\ndata: {"runId":"run-1","questionMessageId":"question-1","replacedMessageId":"partial-2"}',
      'event: message.started\ndata: {"messageId":"answer-final"}',
      'event: message.delta\ndata: {"delta":"最终完整回答"}',
      'event: run.completed\ndata: {}',
      'event: message.completed\ndata: {}',
    ]))
    await store.retryMessage({ id: 'section-1' })
    expect(store.messages.map((message) => message.content)).toEqual([
      '旧问题', '完整历史回答', '原问题', '最终完整回答',
    ])
  })

  it.each(['guiding', 'diagnosing'])('does not expose answer retry after a complete-answer %s failure', async (phase) => {
    const store = useConversationStore()
    store.activeConversation = conversation
    mockedRequest.mockResolvedValueOnce(failedMessages as never)
      .mockResolvedValueOnce({ ...failedRun, phase, retryable: false } as never)

    await store.loadConversationMessages(conversation)

    expect(store.retryRun).toBeNull()
    expect(store.messages[3].incomplete).toBe(false)
    expect(store.streamError).toBe('连接中断')
  })

  it('ignores an old stream after selecting another conversation, including assist events and cleanup', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start(value) { controller = value } })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body))
    const store = useConversationStore()
    store.activeConversation = conversation
    const assist = vi.fn()
    store.setStudyAssistEventHandler(assist)
    const sending = store.sendMessage('原问题', { id: 'section-1' })
    controller.enqueue(new TextEncoder().encode('event: message.delta\ndata: {"delta":"旧回答"}\n\n'))
    await vi.waitFor(() => expect(store.messages[1].content).toBe('旧回答'))
    mockedRequest.mockResolvedValueOnce([{ id: 'new-question', role: 'user', content: '新问题' }] as never)
      .mockResolvedValueOnce({ id: 'new-run', status: 'running', phase: 'guiding' } as never)

    await store.selectConversation({ id: 'conversation-2', sectionId: 'section-1' })
    controller.enqueue(new TextEncoder().encode([
      'event: message.delta\ndata: {"delta":"不应出现"}',
      'event: guidance.updated\ndata: {"id":"old-guidance"}',
      'event: run.failed\ndata: {"message":"旧错误","retryable":true}',
      '',
    ].join('\n\n')))
    controller.close()
    await sending

    expect(store.messages).toHaveLength(1)
    expect(store.messages[0]).toMatchObject({ id: 'new-question', content: '新问题' })
    expect(store.sideRun).toMatchObject({ active: true, phase: 'guiding' })
    expect(store.latestRun?.id).toBe('new-run')
    expect(store.streamError).toBe('')
    expect(assist).not.toHaveBeenCalled()
  })

  it('ignores a delayed status recovery after navigating away', async () => {
    let recover!: (run: never) => void
    mockedRequest.mockImplementationOnce(() => new Promise((resolve) => { recover = resolve }))
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse(['event: message.delta\ndata: {"delta":"旧回答"}']))
    const store = useConversationStore()
    store.activeConversation = conversation
    // Catch immediately so the intentionally interrupted promise is always handled.
    const sending = store.sendMessage('原问题', { id: 'section-1' }).catch(() => {})
    await vi.waitFor(() => expect(store.restoringRetry).toBe(true))
    mockedRequest.mockResolvedValueOnce([{ id: 'new-question', role: 'user', content: '新问题' }] as never)
      .mockResolvedValueOnce(null as never)
    await store.selectConversation({ id: 'conversation-2', sectionId: 'section-1' })
    recover(failedRun as never)
    await sending

    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].id).toBe('new-question')
    expect(store.latestRun).toBeNull()
    expect(store.streamError).toBe('')
    expect(store.restoringRetry).toBe(false)
  })

  it('clears errors and retry eligibility when starting a new discussion or resetting', async () => {
    const store = useConversationStore()
    store.activeConversation = conversation
    store.latestRun = { ...failedRun }
    store.streamError = '旧错误'
    await store.selectConversation(null)
    expect(store.streamError).toBe('')
    expect(store.latestRun).toBeNull()
    expect(store.canRetry).toBe(false)
    store.latestRun = { ...failedRun }
    store.streamError = '旧错误'
    store.reset()
    expect(store.streamError).toBe('')
    expect(store.latestRun).toBeNull()
    expect(store.canRetry).toBe(false)
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
