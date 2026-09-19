import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useAuthStore } from './auth'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('checks the current user and marks the check complete', async () => {
    mockedRequest.mockResolvedValue({ id: 'user-1', username: 'alice' } as never)
    const store = useAuthStore()

    await expect(store.check()).resolves.toMatchObject({ id: 'user-1' })
    expect(store.checked).toBe(true)
    expect(store.user).toMatchObject({ username: 'alice' })
    expect(mockedRequest).toHaveBeenCalledWith('/auth/me')
  })

  it('submits registration payload and clears secret fields', async () => {
    mockedRequest.mockResolvedValue({ id: 'user-1' } as never)
    const store = useAuthStore()
    store.mode = 'register'
    store.username = 'alice'
    store.password = 'password'
    store.inviteCode = 'invite'

    await store.submit()

    expect(mockedRequest).toHaveBeenCalledWith('/auth/register', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ username: 'alice', password: 'password', inviteCode: 'invite' }),
    }))
    expect(store.password).toBe('')
    expect(store.inviteCode).toBe('')
    expect(store.loading).toBe(false)
  })

  it('clears the user even when logout request fails', async () => {
    mockedRequest.mockRejectedValue(new Error('network'))
    const store = useAuthStore()
    store.user = { id: 'user-1' }

    await store.logout()

    expect(store.user).toBeNull()
  })
})
