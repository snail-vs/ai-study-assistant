// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App.vue'
import { request } from './api/client'
import { router } from './router'
import { useConversationStore } from './stores/conversation'

vi.mock('./api/client', () => ({ request: vi.fn() }))

let wrapper: VueWrapper | undefined
afterEach(async () => {
  wrapper?.unmount()
  wrapper = undefined
  vi.mocked(request).mockReset()
  await router.replace('/')
})

it('preserves a failed discussion deep link while startup history is still loading', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const space = { id: 'space', title: 'Course', rootCardId: 'card', generationStatus: 'completed' }
  const card = {
    id: 'card', title: 'Card', cardType: 'root',
    sections: [{ id: 'section', title: 'Section', contentMarkdown: 'Content', generationStatus: 'completed' }],
  }
  const conversation = { id: 'conversation', cardId: 'card', sectionId: 'section', title: 'Discussion' }
  let resolveHistory!: (value: { items: typeof space[] }) => void
  const history = new Promise<{ items: typeof space[] }>((resolve) => { resolveHistory = resolve })
  vi.mocked(request).mockImplementation(async (path, options = {}) => {
    if (path === '/auth/me') return { id: 'owner', username: 'owner' }
    if (path === '/learning-spaces') return history
    if (path === '/settings/providers') return { providers: {}, models: {} }
    if (path === '/learning-spaces/space/cards') return [card]
    if (path === '/cards/card') return card
    if (path === '/learning-spaces/space/runtime') return { currentCardId: 'card', navigationStack: [] }
    if (String(path).endsWith('/conversations?sectionId=section')) return [conversation]
    if (path === '/conversations/conversation/messages') return [
      { id: 'question', role: 'user', content: 'Question', visibility: 'user' },
      { id: 'partial', role: 'assistant', content: 'Partial answer', visibility: 'user' },
    ]
    if (path === '/conversations/conversation/runs/latest') return {
      id: 'failed-run', status: 'failed', phase: 'answering', retryable: true,
      questionMessageId: 'question', answerMessageId: 'partial', errorMessage: 'Upstream disconnected',
    }
    if (String(path).endsWith('/guidance')) return options.method === 'POST' ? {} : [{ id: 'intro', content: 'Intro' }]
    return []
  })
  await router.push('/')
  wrapper = mount(App, {
    global: {
      plugins: [pinia, router],
      stubs: { CourseDesignFlow: true, HomeLibrary: true, SettingsDialog: true, NotesDrawer: true, ActivityPanel: true, KnowledgeSidebar: true },
    },
  })
  await flushPromises()
  await router.push('/study/space/card/card?section=0&conversation=conversation')
  resolveHistory({ items: [space] })
  await flushPromises()

  expect(router.currentRoute.value.name).toBe('study')
  expect(router.currentRoute.value.query.conversation).toBe('conversation')
  const store = useConversationStore()
  expect(store.activeConversation?.id).toBe('conversation')
  expect(store.canRetry).toBe(true)
  expect(store.messages.map((message) => message.id)).toEqual(['question', 'partial'])
  expect(wrapper.find('.message-incomplete').exists()).toBe(true)
  expect(wrapper.find('.chat-error button').attributes('disabled')).toBeUndefined()
})
