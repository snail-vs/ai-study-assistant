import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'

type StudyCard = Record<string, any>
type StudySection = Record<string, any>
type StudyAssistItem = Record<string, any>
type StreamEventHandler = (event: string, data: StudyAssistItem) => void

function itemId(item: StudyAssistItem | null) {
  if (!item || typeof item !== 'object') return ''
  const value = item.proposalId || item.id
  return typeof value === 'string' ? value : ''
}

/** Chapter-scoped teacher guidance and related-card recommendations. */
export const useStudyAssistStore = defineStore('study-assist', () => {
  const teacherGuidance = ref<StudyAssistItem[]>([])
  const recommendations = ref<StudyAssistItem[]>([])
  const proposal = ref<StudyAssistItem | null>(null)
  const selectedRecommendation = ref<StudyAssistItem | null>(null)
  const guidanceError = ref('')
  const recommendationError = ref('')
  const cardId = ref('')
  const sectionId = ref('')

  let contextVersion = 0

  function setContext(card: StudyCard | null, section: StudySection | null) {
    const nextCardId = typeof card?.id === 'string' ? card.id : ''
    const nextSectionId = typeof section?.id === 'string' ? section.id : ''
    if (nextCardId === cardId.value && nextSectionId === sectionId.value) return
    cardId.value = nextCardId
    sectionId.value = nextSectionId
    contextVersion += 1
    teacherGuidance.value = []
    recommendations.value = []
    proposal.value = null
    selectedRecommendation.value = null
    guidanceError.value = ''
    recommendationError.value = ''
  }

  function reset() {
    contextVersion += 1
    cardId.value = ''
    sectionId.value = ''
    teacherGuidance.value = []
    recommendations.value = []
    proposal.value = null
    selectedRecommendation.value = null
    guidanceError.value = ''
    recommendationError.value = ''
  }

  async function loadTeacherGuidance(card: StudyCard | null, section: StudySection | null) {
    setContext(card, section)
    const version = contextVersion
    if (!card?.id || !section?.id) return []
    guidanceError.value = ''
    try {
      let stored = await request<StudyAssistItem[]>(`/cards/${card.id}/sections/${section.id}/guidance`)
      if (!stored.length) {
        await request(`/cards/${card.id}/sections/${section.id}/guidance`, { method: 'POST' })
        stored = await request<StudyAssistItem[]>(`/cards/${card.id}/sections/${section.id}/guidance`)
      }
      if (version === contextVersion && cardId.value === card.id && sectionId.value === section.id) {
        teacherGuidance.value = stored
      }
      return stored
    } catch (error) {
      if (version === contextVersion) guidanceError.value = error instanceof Error ? error.message : String(error)
      throw error
    }
  }

  async function loadRecommendations(card: StudyCard | null, section: StudySection | null) {
    setContext(card, section)
    const version = contextVersion
    if (!card?.id || !section?.id) return []
    recommendationError.value = ''
    try {
      const all = await request<StudyAssistItem[]>(`/cards/${card.id}/proposals`)
      const filtered = all.filter((item) => item.sectionId === section.id)
      if (version === contextVersion && cardId.value === card.id && sectionId.value === section.id) {
        recommendations.value = filtered
      }
      return filtered
    } catch (error) {
      if (version === contextVersion) recommendationError.value = error instanceof Error ? error.message : String(error)
      throw error
    }
  }

  function handleStreamEvent(event: string, data: StudyAssistItem) {
    if (data.sectionId && data.sectionId !== sectionId.value) return
    if (event === 'related_card.proposed') {
      proposal.value = data
      const id = itemId(data)
      recommendations.value = [data, ...recommendations.value.filter((item) => itemId(item) !== id)]
    }
    if (event === 'guidance.updated') {
      const id = itemId(data)
      teacherGuidance.value = id
        ? [data, ...teacherGuidance.value.filter((item) => itemId(item) !== id)]
        : [...teacherGuidance.value, data]
    }
    if (event === 'guidance.failed') guidanceError.value = `课程导师引导失败：${data.message || '未知错误'}`
  }

  function setSelectedRecommendation(item: StudyAssistItem | null) {
    selectedRecommendation.value = item
  }

  function removeRecommendation(id: string) {
    recommendations.value = recommendations.value.filter((item) => itemId(item) !== id)
    if (itemId(proposal.value) === id) proposal.value = null
    if (itemId(selectedRecommendation.value) === id) selectedRecommendation.value = null
  }

  function clearProposal() {
    proposal.value = null
    selectedRecommendation.value = null
  }

  return {
    teacherGuidance, recommendations, proposal, selectedRecommendation,
    guidanceError, recommendationError, cardId, sectionId,
    setContext, reset, loadTeacherGuidance, loadRecommendations,
    handleStreamEvent, setSelectedRecommendation, removeRecommendation, clearProposal,
  }
})
