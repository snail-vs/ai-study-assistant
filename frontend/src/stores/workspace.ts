import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'
import { useActivityStore } from './activity'
import { useConversationStore } from './conversation'
import { useLearningStore } from './learning'
import { useNotesStore } from './notes'
import { useStudyAssistStore } from './study-assist'
import { router } from '../router'

type LearningSpace = Record<string, any>
type LearningCard = Record<string, any>
type NavigationContext = { cardId: string; sectionId?: string | null }

/** Coordinates cross-store navigation for the study workspace shell. */
export const useWorkspaceStore = defineStore('workspace', () => {
  const learningStore = useLearningStore()
  const conversationStore = useConversationStore()
  const studyAssistStore = useStudyAssistStore()
  const activityStore = useActivityStore()
  const notesStore = useNotesStore()

  const loading = ref(false)
  const error = ref('')
  const learningView = ref('content')
  let workflowVersion = 0
  let internalNavigation = false

  const isCurrent = (version: number) => version === workflowVersion

  function syncStudyUrl({ replace = false } = {}) {
    if (!learningStore.space || !learningStore.card) return
    const params = new URLSearchParams({ section: String(learningStore.activeSection) })
    if (conversationStore.activeConversation?.id) {
      params.set('conversation', conversationStore.activeConversation.id)
    }
    if (learningView.value === 'activity') {
      params.set('view', 'quiz')
      if (activityStore.activeActivity?.id) params.set('activity', activityStore.activeActivity.id)
    }
    const location = {
      name: 'study' as const,
      params: {
        spaceId: String(learningStore.space.id),
        cardId: String(learningStore.card.id),
      },
      query: Object.fromEntries(params.entries()),
    }
    internalNavigation = true
    const navigation = replace ? router.replace(location) : router.push(location)
    void navigation.catch(() => {
      internalNavigation = false
    })
  }

  async function loadSectionConversations(preferredConversationId: string | null = null, version = workflowVersion) {
    try {
      await conversationStore.loadSectionConversations(
        learningStore.card,
        learningStore.section,
        preferredConversationId,
      )
    } catch (cause) {
      if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function loadSectionActivities() {
    return activityStore.loadSectionActivities(learningStore.card, learningStore.section)
  }

  async function loadAssistAndSection(version = workflowVersion) {
    const refresh = async (action: () => Promise<unknown>) => {
      try {
        await action()
      } catch (cause) {
        if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
      }
    }
    await refresh(() => studyAssistStore.loadTeacherGuidance(learningStore.card, learningStore.section))
    await refresh(() => studyAssistStore.loadRecommendations(learningStore.card, learningStore.section))
    await refresh(() => learningStore.loadRelatedCards())
    await refresh(() => loadSectionActivities())
    await refresh(() => loadSectionConversations(null, version))
  }

  async function openCard(
    target: LearningCard,
    navigationContext: NavigationContext | null = null,
    options: { preserveNavigation?: boolean; persist?: boolean; eventType?: string; version?: number } = {},
  ) {
    const version = options.version || ++workflowVersion
    if (navigationContext) learningStore.pushNavigation(navigationContext)
    else if (!options.preserveNavigation) learningStore.resetNavigation()
    learningStore.setCard(target)
    learningView.value = 'content'
    activityStore.resetActive()
    conversationStore.showConversationList = false
    studyAssistStore.clearProposal()
    learningStore.activeSection = 0
    await loadAssistAndSection(version)
    if (!isCurrent(version)) return false
    syncStudyUrl({ replace: router.currentRoute.value.name === 'study' })
    if (options.persist !== false) await learningStore.persistRuntime(options.eventType || 'card_opened')
    return true
  }

  async function openHistory(item: LearningSpace) {
    const version = ++workflowVersion
    loading.value = true
    error.value = ''
    try {
      learningStore.setSpace(item)
      const target = await request<LearningCard>(`/cards/${item.rootCardId}`)
      if (!isCurrent(version)) return
      learningStore.setCard(target, { root: true })
      learningStore.resetNavigation()
      await openCard(target, null, { version, persist: false })
      if (!isCurrent(version)) return
      await notesStore.loadNotes()
      syncStudyUrl({ replace: true })
      await learningStore.persistRuntime('card_opened')
    } catch (cause) {
      if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (isCurrent(version)) loading.value = false
    }
  }

  async function openHistoryCard(spaceItem: LearningSpace, target: LearningCard) {
    const version = ++workflowVersion
    loading.value = true
    error.value = ''
    try {
      learningStore.setSpace(spaceItem)
      learningStore.setCard(target, { root: target.cardType === 'root' })
      await openCard(target, null, { version })
      if (isCurrent(version)) await notesStore.loadNotes()
    } catch (cause) {
      if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (isCurrent(version)) loading.value = false
    }
  }

  async function openRelatedCard(target: LearningCard) {
    if (!learningStore.card) return
    await openCard(target, {
      cardId: learningStore.card.id,
      sectionId: learningStore.section?.id || null,
    }, { eventType: 'branch_entered' })
  }

  async function returnToMain() {
    const context = learningStore.navigationStack[learningStore.navigationStack.length - 1]
    if (!context) return
    const version = ++workflowVersion
    learningStore.popNavigation()
    try {
      const sourceCard = await request<LearningCard>(`/cards/${context.cardId}`)
      if (!isCurrent(version)) return
      await openCard(sourceCard, null, { preserveNavigation: true, persist: false, version })
      const sourceIndex = sourceCard.sections?.findIndex((item: LearningCard) => item.id === context.sectionId) ?? -1
      learningStore.activeSection = sourceIndex >= 0 ? sourceIndex : 0
      await studyAssistStore.loadTeacherGuidance(learningStore.card, learningStore.section)
      await learningStore.loadRelatedCards()
      await loadSectionConversations()
      syncStudyUrl({ replace: true })
      await learningStore.persistRuntime('branch_returned')
    } catch (cause) {
      if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function selectSection(index: number) {
    const version = ++workflowVersion
    learningStore.activeSection = index
    learningView.value = 'content'
    activityStore.resetActive()
    try {
      await learningStore.loadRelatedCards()
      await studyAssistStore.loadTeacherGuidance(learningStore.card, learningStore.section)
      await loadSectionActivities()
      await loadSectionConversations()
      if (!isCurrent(version)) return
      syncStudyUrl({ replace: true })
      await learningStore.persistRuntime('section_changed')
    } catch (cause) {
      if (isCurrent(version)) error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function restoreStudyRoute(route = router.currentRoute.value) {
    if (internalNavigation) {
      internalNavigation = false
      return
    }
    if (route.name !== 'study') {
      if (route.name !== 'home' || learningStore.space) goHome()
      return
    }
    const version = ++workflowVersion
    const spaceId = String(route.params.spaceId || '')
    const cardId = String(route.params.cardId || '')
    if (!spaceId || !cardId) {
      goHome()
      return
    }
    const spaceItem = learningStore.history.find((item) => item.id === spaceId)
    if (!spaceItem) {
      goHome()
      return
    }
    loading.value = true
    error.value = ''
    try {
      learningStore.setSpace(spaceItem)
      const target = await request<LearningCard>(`/cards/${cardId}`)
      const runtime = await request<any>(`/learning-spaces/${spaceId}/runtime`)
      if (!isCurrent(version)) return
      learningStore.setCard(target, { root: target.cardType === 'root' })
      learningStore.navigationStack = runtime?.currentCardId === cardId ? (runtime.navigationStack || []) : []
      await openCard(target, null, { preserveNavigation: true, persist: false, version })
      const params = route.query
      const queryValue = (name: string) => {
        const value = params[name]
        return Array.isArray(value) ? value[0] : value
      }
      const requestedSection = Number(queryValue('section'))
      if (Number.isInteger(requestedSection) && requestedSection >= 0
        && requestedSection < (learningStore.card?.sections?.length || 0)) {
        learningStore.activeSection = requestedSection
      await loadAssistAndSection(version)
      }
      const conversation = conversationStore.conversations.find((item) => item.id === queryValue('conversation'))
      if (conversation && conversationStore.activeConversation?.id !== conversation.id) {
        await conversationStore.selectConversation(conversation)
      }
      await loadSectionActivities()
      if (queryValue('view') === 'quiz') {
        learningView.value = 'activity'
        await activityStore.openQuiz(learningStore.card, learningStore.section, queryValue('activity'))
      }
      if (!isCurrent(version)) return
      syncStudyUrl({ replace: true })
      await learningStore.persistRuntime('restore')
    } catch (cause) {
      if (isCurrent(version)) {
        error.value = cause instanceof Error ? cause.message : String(cause)
        goHome()
      }
    } finally {
      if (isCurrent(version)) loading.value = false
    }
  }

  function goHome() {
    workflowVersion += 1
    learningStore.clearWorkspace()
    conversationStore.reset()
    studyAssistStore.reset()
    activityStore.reset()
    notesStore.closeNotes()
    learningView.value = 'content'
    loading.value = false
    error.value = ''
    internalNavigation = true
    void router.replace({ name: 'home' }).catch(() => {
      internalNavigation = false
    })
    void learningStore.loadHistory()
  }

  return {
    loading, error, learningView, syncStudyUrl, restoreStudyRoute,
    openHistory, openHistoryCard, openCard, openRelatedCard, returnToMain,
    selectSection, goHome,
  }
})
