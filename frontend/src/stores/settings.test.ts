import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useSettingsStore } from './settings'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

describe('settings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('loads settings and initializes the provider editor', async () => {
    mockedRequest.mockResolvedValue({
      activeProvider: 'google', activeModel: 'gemini-2',
      providers: { google: true }, models: { google: ['gemini-2'] }, taskRoutes: { course_plan: 'google:gemini-2' },
    } as never)
    const store = useSettingsStore()

    await store.open()

    expect(store.selectedProvider).toBe('google')
    expect(store.selectedModels).toEqual(['gemini-2'])
    expect(store.selectedDefaultModel).toBe('google:gemini-2')
    expect(store.taskRoutes).toEqual({ course_plan: 'google:gemini-2' })
  })

  it('starts device-code login and records polling state', async () => {
    mockedRequest.mockResolvedValue({ sessionId: 'session-1', userCode: 'ABCD', verificationUri: 'https://example.test', intervalSeconds: 60 } as never)
    const store = useSettingsStore()

    await store.startChatgptLogin()

    expect(store.chatgptLogin).toMatchObject({ status: 'pending', sessionId: 'session-1', userCode: 'ABCD' })
    store.stopChatgptPolling()
  })

  it('persists provider and model assignments while resetting loading flags', async () => {
    mockedRequest
      .mockResolvedValueOnce({ activeProvider: 'deepseek', providers: { deepseek: true }, models: { deepseek: ['deepseek-chat'] } } as never)
      .mockResolvedValueOnce({ activeProvider: 'deepseek', providers: { deepseek: true }, models: { deepseek: ['deepseek-chat'] }, taskRoutes: { course_plan: 'deepseek:deepseek-chat' } } as never)
      .mockResolvedValueOnce({ activeProvider: 'deepseek', activeModel: 'deepseek-chat', taskRoutes: { course_plan: 'deepseek:deepseek-chat' } } as never)
    const store = useSettingsStore()
    store.selectedProvider = 'deepseek'
    store.selectedModels = ['deepseek-chat']
    store.apiKey = 'secret'
    store.selectedDefaultModel = 'deepseek:deepseek-chat'
    store.taskRoutes = { course_plan: 'deepseek:deepseek-chat' }

    await store.saveProvider()
    await store.saveModelAssignments()

    expect(mockedRequest).toHaveBeenCalledWith('/settings/providers/deepseek', expect.objectContaining({ method: 'PUT' }))
    expect(mockedRequest).toHaveBeenCalledWith('/settings/model-routes', expect.objectContaining({ method: 'PUT' }))
    expect(store.saving).toBe(false)
    expect(store.savingModelAssignments).toBe(false)
  })
})
