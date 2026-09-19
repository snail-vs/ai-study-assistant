import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from './router'

describe('application router', () => {
  let router: ReturnType<typeof createAppRouter>

  afterEach(() => router = undefined as never)

  it('round-trips encoded study identifiers and query parameters', async () => {
    router = createAppRouter(createMemoryHistory())
    await router.push({
      name: 'study',
      params: { spaceId: 'space/一', cardId: 'card?二' },
      query: { section: '2', conversation: 'conversation/三', view: 'quiz', activity: 'quiz/四' },
    })

    expect(router.currentRoute.value.name).toBe('study')
    expect(router.currentRoute.value.params).toEqual({ spaceId: 'space/一', cardId: 'card?二' })
    expect(router.currentRoute.value.query).toEqual({
      section: '2', conversation: 'conversation/三', view: 'quiz', activity: 'quiz/四',
    })
  })

  it('keeps browser navigation semantics for push and replace', async () => {
    router = createAppRouter(createMemoryHistory())
    const afterEach = []
    router.afterEach((to, from) => afterEach.push([to.name, from.name]))

    await router.push({ name: 'study', params: { spaceId: 'space-1', cardId: 'card-1' } })
    await router.push({ name: 'study', params: { spaceId: 'space-1', cardId: 'card-2' } })
    await router.replace({ name: 'study', params: { spaceId: 'space-1', cardId: 'card-3' } })

    expect(router.currentRoute.value.params.cardId).toBe('card-3')
    router.back()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(router.currentRoute.value.params.cardId).toBe('card-1')
    expect(afterEach.map(([to]) => to)).toEqual(['study', 'study', 'study', 'study'])
  })

  it('redirects unknown deep links to home', async () => {
    router = createAppRouter(createMemoryHistory())
    await router.push('/unknown/path')

    expect(router.currentRoute.value.name).toBe('home')
    expect(router.currentRoute.value.path).toBe('/')
  })
})
