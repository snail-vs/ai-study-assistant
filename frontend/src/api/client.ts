import type { paths } from './generated/schema'

type ApiPath = keyof paths & string

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function errorMessage(body: unknown): string {
  if (!body || typeof body !== 'object') return '请求失败'
  const value = body as { error?: unknown; detail?: unknown }
  if (typeof value.error === 'string') return value.error
  if (value.error && typeof value.error === 'object') {
    const error = value.error as { message?: unknown; details?: { reason?: unknown } }
    if (typeof error.message === 'string') return error.message
    if (typeof error.details?.reason === 'string') return error.details.reason
  }
  if (typeof value.detail === 'string') return value.detail
  return '请求失败'
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return {}
  }
}

/** The single same-origin JSON boundary used by the application. */
export async function request<T = unknown>(path: ApiPath | string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
  })
  const body = await readBody(response)
  if (!response.ok) throw new ApiError(errorMessage(body), response.status, body)
  return body as T
}
