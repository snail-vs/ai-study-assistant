import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { request } from '../api/client'

type LearningSpace = Record<string, any>
type LearningCard = Record<string, any>
type NavigationContext = { cardId: string; sectionId?: string | null }

/** State and persistence for the learning workspace shown by the study shell. */
export const useLearningStore = defineStore('learning', () => {
  const history = ref<LearningSpace[]>([])
  const historyCards = ref<Record<string, LearningCard[]>>({})
  const generationNotice = ref('')
  const editingFailedSpace = ref<LearningSpace | null>(null)
  const space = ref<LearningSpace | null>(null)
  const card = ref<LearningCard | null>(null)
  const rootCard = ref<LearningCard | null>(null)
  const relatedCards = ref<LearningCard[]>([])
  const navigationStack = ref<NavigationContext[]>([])
  const activeSection = ref(0)
  const section = computed(() => card.value?.sections?.[activeSection.value] || null)

  let generationPollTimer: ReturnType<typeof setInterval> | null = null
  let relatedLoadVersion = 0

  function stopGenerationPolling() {
    if (generationPollTimer) {
      clearInterval(generationPollTimer)
      generationPollTimer = null
    }
  }

  async function loadHistory() {
    try {
      const nextHistory = (await request<{ items?: LearningSpace[] }>('/learning-spaces')).items || []
      const previousStatuses = new Map(history.value.map((item) => [item.id, item.generationStatus]))
      for (const item of nextHistory) {
        const previous = previousStatuses.get(item.id)
        if (previous && previous !== item.generationStatus && item.generationStatus === 'completed') {
          generationNotice.value = `课程“${item.title}”已生成完成。`
        } else if (previous && previous !== item.generationStatus && item.generationStatus === 'failed') {
          generationNotice.value = `课程“${item.title}”生成失败：${item.generationError || '请重试。'}`
        }
      }
      history.value = nextHistory
      const entries = await Promise.all(history.value.map(async (item) => {
        try {
          return [item.id, await request<LearningCard[]>(`/learning-spaces/${item.id}/cards`)] as const
        } catch (_) {
          return [item.id, []] as const
        }
      }))
      historyCards.value = Object.fromEntries(entries)
      const hasPending = history.value.some((item) => item.generationStatus === 'queued' || item.generationStatus === 'running')
      if (hasPending && !generationPollTimer) generationPollTimer = setInterval(() => { void loadHistory() }, 3000)
      else if (!hasPending) stopGenerationPolling()
    } catch (_) {
      // Keep the home screen usable if the history endpoint is temporarily unavailable.
    }
    return history.value
  }

  async function persistRuntime(eventType = 'navigation') {
    if (!space.value || !card.value) return
    try {
      await request(`/learning-spaces/${space.value.id}/runtime`, {
        method: 'PUT',
        body: JSON.stringify({
          currentCardId: card.value.id,
          currentSectionId: section.value?.id || null,
          navigationStack: navigationStack.value,
          eventType,
        }),
      })
    } catch (_) {
      // Runtime persistence must not block reading an otherwise available course.
    }
  }

  async function loadRelatedCards() {
    const version = ++relatedLoadVersion
    const spaceId = space.value?.id
    const cardId = card.value?.id
    const sectionId = section.value?.id
    if (!space.value || !card.value || !section.value) {
      relatedCards.value = []
      return relatedCards.value
    }
    const cards = await request<LearningCard[]>(`/learning-spaces/${space.value.id}/cards`)
    if (version !== relatedLoadVersion
      || space.value?.id !== spaceId
      || card.value?.id !== cardId
      || section.value?.id !== sectionId) return relatedCards.value
    relatedCards.value = cards.filter((item) => item.cardType === 'related'
      && item.parentCardId === card.value?.id
      && item.parentSectionId === section.value?.id)
    return relatedCards.value
  }

  function setSpace(nextSpace: LearningSpace | null) {
    space.value = nextSpace
  }

  function setCard(nextCard: LearningCard | null, { root = false } = {}) {
    card.value = nextCard
    if (root) rootCard.value = nextCard
  }

  function resetNavigation() {
    navigationStack.value = []
    activeSection.value = 0
  }

  function pushNavigation(context: NavigationContext) {
    navigationStack.value = [...navigationStack.value, context]
  }

  function popNavigation() {
    const context = navigationStack.value[navigationStack.value.length - 1] || null
    navigationStack.value = navigationStack.value.slice(0, -1)
    return context
  }

  function clearWorkspace() {
    space.value = null
    card.value = null
    rootCard.value = null
    relatedCards.value = []
    navigationStack.value = []
    activeSection.value = 0
  }

  return {
    history, historyCards, generationNotice, editingFailedSpace, space, card, rootCard,
    relatedCards, navigationStack, activeSection, section,
    loadHistory, persistRuntime, loadRelatedCards, stopGenerationPolling, setSpace, setCard, resetNavigation,
    pushNavigation, popNavigation, clearWorkspace,
  }
})
