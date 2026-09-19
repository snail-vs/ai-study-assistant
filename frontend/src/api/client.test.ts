import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from './client'

afterEach(() => vi.restoreAllMocks())

function response(body: unknown, init: ResponseInit = {}) {
  return {
    ok: init.status === undefined || (init.status >= 200 && init.status < 300),
    status: init.status || 200,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

describe('request', () => {
  it('sends same-origin JSON requests and returns the decoded body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ id: 7 })))

    await expect(request('/auth/me')).resolves.toEqual({ id: 7 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/auth/me', expect.objectContaining({
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
    }))
  })

  it('preserves a structured API error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { message: '无权限' } }, { status: 403 })))

    await expect(request('/settings/providers')).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: '无权限', body: { error: { message: '无权限' } },
    })
  })

  it('uses detail and nested reason error forms', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response({ detail: '参数错误' }, { status: 422 }))
      .mockResolvedValueOnce(response({ error: { details: { reason: '上游失败' } } }, { status: 502 })))

    await expect(request('/activities/1')).rejects.toMatchObject({ message: '参数错误' })
    await expect(request('/activities/1')).rejects.toMatchObject({ message: '上游失败' })
  })

  it('falls back to a generic ApiError for non-JSON failures', async () => {
    const failed = response({}, { status: 500 })
    failed.json = vi.fn().mockRejectedValue(new SyntaxError('not json'))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failed))

    await expect(request('/health')).rejects.toEqual(expect.objectContaining({
      name: 'ApiError', status: 500, message: '请求失败', body: {},
    }))
    await expect(request('/health')).rejects.toBeInstanceOf(ApiError)
  })
})
