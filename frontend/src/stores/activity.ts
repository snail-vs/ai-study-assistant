import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'

type Activity = Record<string, any>
type Card = Record<string, any>
type Section = Record<string, any>

function initialAnswers(activity: Activity | null) {
  return Object.fromEntries((activity?.questions || []).map((question: Activity) => [
    question.id,
    question.type === 'short_answer' ? '' : null,
  ]))
}

/** Activity state and assessment actions for the current learning section. */
export const useActivityStore = defineStore('activity', () => {
  const activities = ref<Activity[]>([])
  const activeActivity = ref<Activity | null>(null)
  const answers = ref<Record<string, any>>({})
  const result = ref<Activity | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const followUpAnswer = ref('')
  const followUpSubmitting = ref(false)

  async function loadSectionActivities(card: Card | null, section: Section | null) {
    if (!card || !section) {
      reset()
      return activities.value
    }
    try {
      activities.value = await request<Activity[]>(`/cards/${card.id}/sections/${section.id}/activities`)
      if (activeActivity.value && !activities.value.some((item) => item.id === activeActivity.value?.id)) {
        resetActive()
      }
    } catch (_) {
      activities.value = []
    }
    return activities.value
  }

  async function openQuiz(card: Card | null, section: Section | null, activityId: string | null = null) {
    if (!card || !section) return null
    loading.value = true
    try {
      let activity = activityId
        ? activities.value.find((item) => item.id === activityId && item.status === 'ready')
        : activities.value.find((item) => item.activityType === 'quiz' && item.status === 'ready')
      if (!activity) {
        activity = await request<Activity>(`/cards/${card.id}/sections/${section.id}/activities/quiz`, { method: 'POST' })
        activities.value = [activity, ...activities.value.filter((item) => item.id !== activity?.id)]
      }
      activeActivity.value = activity
      result.value = activity.latestAttempt || null
      followUpAnswer.value = ''
      followUpSubmitting.value = false
      answers.value = result.value ? {} : initialAnswers(activity)
      return activity
    } finally {
      loading.value = false
    }
  }

  function resetActive() {
    activeActivity.value = null
    result.value = null
    answers.value = {}
    followUpAnswer.value = ''
    followUpSubmitting.value = false
  }

  function reset() {
    activities.value = []
    resetActive()
    loading.value = false
    submitting.value = false
  }

  async function submitQuiz() {
    if (!activeActivity.value || submitting.value) return null
    const unanswered = (activeActivity.value.questions || []).filter((question: Activity) => {
      const answer = answers.value[question.id]
      return answer === null || answer === undefined || String(answer).trim() === ''
    })
    if (unanswered.length) throw new Error(`还有 ${unanswered.length} 道题没有完成`)
    submitting.value = true
    try {
      const nextResult = await request<Activity>(`/activities/${activeActivity.value.id}/attempts`, {
        method: 'POST',
        body: JSON.stringify({ answers: answers.value }),
      })
      result.value = nextResult
      activeActivity.value = { ...activeActivity.value, latestAttempt: nextResult }
      activities.value = activities.value.map((item) => item.id === activeActivity.value?.id ? activeActivity.value as Activity : item)
      return nextResult
    } finally {
      submitting.value = false
    }
  }

  function retryQuiz() {
    result.value = null
    followUpAnswer.value = ''
    followUpSubmitting.value = false
    answers.value = initialAnswers(activeActivity.value)
  }

  async function submitFollowUp() {
    if (!activeActivity.value || !result.value?.followUp || followUpSubmitting.value) return null
    const answer = followUpAnswer.value.trim()
    if (!answer) throw new Error('请先回答针对性追问')
    if (answer.length > 4000) throw new Error('回答不能超过 4000 字')
    followUpSubmitting.value = true
    try {
      const nextResult = await request<Activity>(`/activities/${activeActivity.value.id}/attempts/${result.value.id}/follow-up`, {
        method: 'POST',
        body: JSON.stringify({ answer }),
      })
      result.value = nextResult
      activeActivity.value = { ...activeActivity.value, latestAttempt: nextResult }
      activities.value = activities.value.map((item) => item.id === activeActivity.value?.id ? activeActivity.value as Activity : item)
      followUpAnswer.value = ''
      return nextResult
    } finally {
      followUpSubmitting.value = false
    }
  }

  return {
    activities, activeActivity, answers, result, loading, submitting,
    followUpAnswer, followUpSubmitting, loadSectionActivities, openQuiz,
    resetActive, reset, submitQuiz, retryQuiz, submitFollowUp,
  }
})
