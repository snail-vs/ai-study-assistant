<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { request as apiRequest } from './api/client'
import { storeToRefs } from 'pinia'
import { useAuthStore } from './stores/auth'
import { useSettingsStore } from './stores/settings'
import { useLearningStore } from './stores/learning'

const authStore = useAuthStore()
const settingsStore = useSettingsStore()
const learningStore = useLearningStore()
const {
  checked: authChecked, user: authUser, mode: authMode, username: authUsername,
  password: authPassword, inviteCode: authInviteCode, loading: authLoading,
} = storeToRefs(authStore)
const {
  status: providerStatus, selectedProvider, apiKey, availableModels, selectedModels,
  selectedDefaultModel, taskRoutes, showAdvancedRoutes, saving: savingSettings,
  fetchingModels, editingKey, savingModelAssignments, chatgptLogin,
} = storeToRefs(settingsStore)
const {
  history, historyCards, generationNotice, editingFailedSpace, space, card, rootCard,
  relatedCards, navigationStack, activeSection, section,
} = storeToRefs(learningStore)

const base = '/api/v1'
const goal = ref('')
const learningView = ref('content')
const activities = ref([])
const activeActivity = ref(null)
const activityAnswers = ref({})
const activityResult = ref(null)
const activityLoading = ref(false)
const activitySubmitting = ref(false)
const followUpAnswer = ref('')
const followUpSubmitting = ref(false)
const showKnowledgeSidebar = ref(localStorage.getItem('studycenter.knowledgeSidebar') !== 'false')
const teacherGuidance = ref([])
const showTeacherGuidance = ref(true)
const conversations = ref([])
const activeConversation = ref(null)
const showConversationList = ref(false)
const showMobileDiscussion = ref(false)
const messages = ref([])
const highlightedMessageIds = ref([])
const input = ref('')
const sideRun = ref({ active: false, phase: '', label: '' })
const composerInput = ref(null)
const notesList = ref([])
const showNotes = ref(false)
const editingNote = ref(null)
const noteEditorMode = ref('list')
const noteEditorTitle = ref('')
const noteEditorContent = ref('')
const noteEditorInitial = ref({ title: '', content: '' })
const noteTargetCardId = ref('')
const noteTargetSectionId = ref('')
const loading = ref(false)
const creatingCard = ref(false)
const creatingBranch = ref(false)
const startingDiscussion = ref(false)
const error = ref('')

const relationLabels = {
  prerequisite: '前置知识',
  deep_dive: '深入理解',
  application: '应用延展',
}

function relationLabel(relationType) {
  return relationLabels[relationType] || '学习分支'
}

function proposalKicker(proposalItem) {
  const relationType = proposalItem?.relationType || 'prerequisite'
  if (relationType === 'prerequisite') return '发现一个前置知识缺口'
  if (relationType === 'deep_dive') return '推荐深入理解'
  if (relationType === 'application') return '推荐应用延展'
  return '推荐学习分支'
}

function proposalId(proposalItem) {
  if (!proposalItem || typeof proposalItem !== 'object') return ''
  const value = proposalItem.proposalId || proposalItem.id
  return typeof value === 'string' ? value.trim() : ''
}

const recommendationGroupLabel = computed(() => {
  const labels = [...new Set(recommendations.value.map((item) => relationLabel(item.relationType || 'prerequisite')))]
  return labels.length === 1 ? `${labels[0]}建议` : '学习分支建议'
})
const theme = ref(localStorage.getItem('studycenter.theme') || 'light')
const showSettings = ref(false)
const taskDefinitions = [
  { id: 'course_plan', label: '课程规划' },
  { id: 'section_content', label: '章节内容生成' },
  { id: 'section_review', label: '章节质量审查' },
  { id: 'section_repair', label: '章节内容修订' },
  { id: 'quiz_generation', label: '理解检查生成' },
  { id: 'quiz_evaluation', label: '理解检查评估' },
  { id: 'teacher_guidance', label: '导师引导' },
  { id: 'side_answer', label: '答疑回复' },
  { id: 'side_answer_plan', label: '答疑规划' },
  { id: 'gap_diagnosis', label: '知识断层诊断' },
  { id: 'bridge_note', label: '知识桥接' },
  { id: 'conversation_title', label: '会话标题' },
  { id: 'group_director', label: '多角色调度' },
]
// 后端仍按任务保存路由；设置页按学习体验中的模型角色归类，避免让用户面对内部任务名。
const modelRoleDefinitions = [
  {
    id: 'course',
    label: '课程设计与内容生成',
    hint: '课程规划、章节生成、内容修订、理解检查生成',
    tasks: ['course_plan', 'section_content', 'section_repair', 'quiz_generation'],
  },
  {
    id: 'quality',
    label: '质量审查与知识诊断',
    hint: '章节审查、理解检查评估、知识断层诊断',
    tasks: ['section_review', 'quiz_evaluation', 'gap_diagnosis'],
  },
  {
    id: 'interaction',
    label: '课堂实时互动',
    hint: '导师引导、课程讨论、知识桥接、多角色调度与会话标题',
    tasks: ['teacher_guidance', 'side_answer', 'side_answer_plan', 'bridge_note', 'conversation_title', 'group_director'],
  },
]
const allModelOptions = computed(() => {
  const options = Object.entries(providerStatus.value.models || {}).flatMap(([provider, models]) => (
    (models || []).map((model) => ({ value: `${provider}:${model}`, label: `${provider} · ${model}` }))
  ))
  if (availableModels.value.length) {
    for (const model of availableModels.value) {
      const value = `${selectedProvider.value}:${model}`
      if (!options.some((item) => item.value === value)) options.push({ value, label: `${selectedProvider.value} · ${model}` })
    }
  }
  return options
})
const proposal = ref(null)
const recommendations = ref([])
const selectedRecommendation = ref(null)
const chatWidth = ref(Math.min(560, Math.max(280, Number(localStorage.getItem('studycenter.chatWidth')) || 360)))
let resizingChat = false
let conversationLoadVersion = 0
let guidanceLoadVersion = 0
// 普通换行按 Markdown 语义处理，避免模型的排版换行被全部渲染成额外的 <br>。
const md = new MarkdownIt({ html: false, breaks: false, linkify: true })

function masteryLabel(level) {
  return level === 'mastered' ? '已掌握' : level === 'developing' ? '掌握中' : level === 'needs_review' ? '需要复习' : ''
}

onMounted(async () => {
  window.addEventListener('popstate', restoreStudyRoute)
  await checkAuth()
  if (authUser.value) {
    await Promise.all([loadHistory(), loadProviderSettings()])
    await restoreStudyRoute()
  }
  authChecked.value = true
})
onUnmounted(() => {
  stopChatResize()
  stopChatgptPolling()
  window.removeEventListener('popstate', restoreStudyRoute)
  learningStore.stopGenerationPolling()
})

function stripRepeatedSectionTitle(content, title) {
  const source = String(content || '').replace(/\r\n?/g, '\n')
  const firstHeading = source.match(/^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*(?:\n|$)/)
  if (!firstHeading || firstHeading[1].trim() !== String(title || '').trim()) return source
  return source.slice(firstHeading[0].length).replace(/^\n+/, '')
}

const renderedContent = computed(() => md.render(
  stripRepeatedSectionTitle(section.value?.contentMarkdown || '本节内容正在生成。', section.value?.title),
))
function renderMessage(content) {
  const source = String(content || '').replace(/\r\n?/g, '\n')
  // 只压缩普通 Markdown 文本，围栏代码块中的空行必须保持原样。
  const compacted = source.split(/(```[\s\S]*?```)/g).map((part, index) => (
    index % 2 === 1 ? part : part.replace(/\n{3,}/g, '\n\n')
  )).join('').trim()
  return md.render(compacted)
}

function guidanceQuestion(item) {
  const question = String(item.sourceQuestion || '').trim()
  if (question) return question.length > 42 ? `${question.slice(0, 42)}…` : question
  const conversation = conversations.value.find((entry) => entry.id === item.sourceConversationId)
  return conversation?.title || '查看对应讨论'
}
const isRelatedCard = computed(() => navigationStack.value.length > 0)
const keyConfigured = computed(() => Boolean(providerStatus.value.providers?.[selectedProvider.value]))
const isChatGpt = computed(() => selectedProvider.value === 'chatgpt')
const knowledgeCardModel = computed(() => providerStatus.value.taskRoutes?.course_plan
  || (providerStatus.value.activeModel ? `${providerStatus.value.activeProvider}:${providerStatus.value.activeModel}` : '未配置模型'))
const sectionTypeLabels = {
  concept: '概念讲解',
  practice: '理解练习',
  summary: '章节总结',
  quiz: '课堂测验',
  interactive: '互动讲解',
}
const sectionTypeLabel = computed(() => sectionTypeLabels[section.value?.contentType] || '课程内容')
const quizActivity = computed(() => activities.value.find((item) => item.activityType === 'quiz') || null)
const quizStatusLabel = computed(() => {
  const result = quizActivity.value?.latestAttempt
  if (!result) return '理解检查'
  return `${result.score} 分`
})
const noteEditorDirty = computed(() => noteEditorMode.value !== 'list' && (
  noteEditorTitle.value !== noteEditorInitial.value.title
  || noteEditorContent.value !== noteEditorInitial.value.content
))
const homeCards = computed(() => history.value.flatMap((spaceItem) => (
  (historyCards.value[spaceItem.id] || []).map((cardItem) => ({
    card: cardItem,
    space: spaceItem,
  }))
)))
const creatingSpaces = computed(() => history.value.filter((item) => (
  item.generationStatus === 'queued' || item.generationStatus === 'running' || item.generationStatus === 'failed'
)))
const noteCardOptions = computed(() => {
  const cards = homeCards.value.map((item) => item.card)
  if (card.value && !cards.some((item) => item.id === card.value.id)) cards.unshift(card.value)
  return cards
})
const noteTargetCard = computed(() => noteCardOptions.value.find((item) => item.id === noteTargetCardId.value) || null)
const noteTargetSections = computed(() => noteTargetCard.value?.sections || [])
const noteEditorSource = computed(() => {
  if (noteEditorMode.value === 'edit' && editingNote.value) return noteSource(editingNote.value)
  const sectionItem = noteTargetSections.value.find((item) => item.id === noteTargetSectionId.value)
  return sectionItem ? `${noteTargetCard.value?.title} · ${sectionItem.title}` : noteTargetCard.value?.title || '学习笔记'
})

function startChatResize(event) {
  event.preventDefault()
  resizingChat = true
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', resizeChat)
  window.addEventListener('pointerup', stopChatResize)
}

function resizeChat(event) {
  if (!resizingChat) return
  chatWidth.value = Math.min(560, Math.max(280, window.innerWidth - event.clientX - 12))
  localStorage.setItem('studycenter.chatWidth', String(chatWidth.value))
}

function stopChatResize() {
  if (!resizingChat) return
  resizingChat = false
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', resizeChat)
  window.removeEventListener('pointerup', stopChatResize)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  localStorage.setItem('studycenter.theme', theme.value)
}

function syncStudyUrl({ replace = false } = {}) {
  if (!space.value || !card.value) return
  const params = new URLSearchParams({ section: String(activeSection.value) })
  if (activeConversation.value?.id) params.set('conversation', activeConversation.value.id)
  if (learningView.value === 'activity') {
    params.set('view', 'quiz')
    if (activeActivity.value?.id) params.set('activity', activeActivity.value.id)
  }
  const url = `/study/${space.value.id}/card/${card.value.id}?${params.toString()}`
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url)
}

async function restoreStudyRoute() {
  const match = window.location.pathname.match(/^\/study\/([^/]+)\/card\/([^/]+)$/)
  if (!match) {
    if (space.value) goHome()
    return
  }
  const [, spaceId, cardId] = match
  const spaceItem = history.value.find((item) => item.id === spaceId)
  if (!spaceItem) return
  loading.value = true
  error.value = ''
  try {
    learningStore.setSpace(spaceItem)
    const target = await request(`/cards/${cardId}`)
    rootCard.value = target.cardType === 'root' ? target : null
    const runtime = await request(`/learning-spaces/${spaceId}/runtime`)
    navigationStack.value = runtime?.currentCardId === cardId ? (runtime.navigationStack || []) : []
    await openCard(target, null, { preserveNavigation: true, persist: false })
    const requestedSection = Number(new URLSearchParams(window.location.search).get('section'))
    if (Number.isInteger(requestedSection) && requestedSection >= 0 && requestedSection < (card.value?.sections?.length || 0)) {
      activeSection.value = requestedSection
      await loadTeacherGuidance()
      await loadRelatedCards()
      await loadSectionConversations()
    }
    const conversationId = new URLSearchParams(window.location.search).get('conversation')
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation && activeConversation.value?.id !== conversation.id) {
      await selectConversation(conversation)
    }
    await loadSectionActivities()
    const params = new URLSearchParams(window.location.search)
    if (params.get('view') === 'quiz') await openQuiz(params.get('activity'))
    syncStudyUrl({ replace: true })
    await persistLearningRuntime('restore')
  } catch (err) {
    error.value = err.message
    window.history.replaceState({}, '', '/')
    goHome()
  } finally {
    loading.value = false
  }
}

function adjustChatWidth(delta) {
  chatWidth.value = Math.min(560, Math.max(280, chatWidth.value + delta))
  localStorage.setItem('studycenter.chatWidth', String(chatWidth.value))
}

function toggleKnowledgeSidebar() {
  showKnowledgeSidebar.value = !showKnowledgeSidebar.value
  localStorage.setItem('studycenter.knowledgeSidebar', String(showKnowledgeSidebar.value))
}

function resizeComposer(event) {
  const textarea = event?.target || composerInput.value
  if (!textarea) return
  textarea.style.height = 'auto'
  const height = Math.min(textarea.scrollHeight, 180)
  textarea.style.height = `${height}px`
  textarea.style.overflowY = textarea.scrollHeight > 180 ? 'auto' : 'hidden'
}

function handleComposerKeydown(event) {
  if (event.key !== 'Enter' || (!event.shiftKey && !event.ctrlKey && !event.metaKey)) return
  event.preventDefault()
  sendMessage()
}

async function request(path, options = {}) {
  return apiRequest(path, options)
}

async function checkAuth() {
  return authStore.check()
}

async function submitAuth() {
  error.value = ''
  try {
    await authStore.submit()
    await Promise.all([loadHistory(), loadProviderSettings()])
  } catch (err) {
    error.value = err.message
  }
}

async function logout() {
  await authStore.logout()
  space.value = null
  history.value = []
}

async function persistLearningRuntime(eventType = 'navigation') {
  return learningStore.persistRuntime(eventType)
}

async function loadSectionActivities() {
  if (!card.value || !section.value) {
    activities.value = []
    return
  }
  try {
    activities.value = await request(`/cards/${card.value.id}/sections/${section.value.id}/activities`)
    if (activeActivity.value && !activities.value.some((item) => item.id === activeActivity.value.id)) {
      activeActivity.value = null
      activityResult.value = null
    }
  } catch (_) {
    activities.value = []
  }
}

async function openQuiz(activityId = null) {
  if (!card.value || !section.value) return
  activityLoading.value = true
  learningView.value = 'activity'
  error.value = ''
  try {
    let activity = activityId ? activities.value.find((item) => item.id === activityId && item.status === 'ready') : activities.value.find((item) => item.activityType === 'quiz' && item.status === 'ready')
    if (!activity) {
      activity = await request(`/cards/${card.value.id}/sections/${section.value.id}/activities/quiz`, { method: 'POST' })
      activities.value = [activity, ...activities.value.filter((item) => item.id !== activity.id)]
    }
    activeActivity.value = activity
    activityResult.value = activity.latestAttempt || null
    followUpAnswer.value = ''
    followUpSubmitting.value = false
    if (activityResult.value) {
      activityAnswers.value = {}
    } else {
      activityAnswers.value = Object.fromEntries((activity.questions || []).map((question) => [question.id, question.type === 'short_answer' ? '' : null]))
    }
    syncStudyUrl({ replace: true })
  } catch (err) {
    error.value = err.message
  } finally {
    activityLoading.value = false
  }
}

function closeQuiz() {
  learningView.value = 'content'
  activeActivity.value = null
  activityResult.value = null
  activityAnswers.value = {}
  followUpAnswer.value = ''
  followUpSubmitting.value = false
  syncStudyUrl({ replace: true })
}

async function submitQuiz() {
  if (!activeActivity.value || activitySubmitting.value) return
  const unanswered = (activeActivity.value.questions || []).filter((question) => {
    const answer = activityAnswers.value[question.id]
    return answer === null || answer === undefined || String(answer).trim() === ''
  })
  if (unanswered.length) {
    error.value = `还有 ${unanswered.length} 道题没有完成`
    return
  }
  activitySubmitting.value = true
  error.value = ''
  try {
    activityResult.value = await request(`/activities/${activeActivity.value.id}/attempts`, {
      method: 'POST',
      body: JSON.stringify({ answers: activityAnswers.value }),
    })
    activeActivity.value = { ...activeActivity.value, latestAttempt: activityResult.value }
    activities.value = activities.value.map((item) => item.id === activeActivity.value.id ? activeActivity.value : item)
    if (activityResult.value?.followUp?.status !== 'pending') {
      await loadTeacherGuidance()
      await loadRecommendations()
    }
  } catch (err) {
    error.value = err.message
  } finally {
    activitySubmitting.value = false
  }
}

function retryQuiz() {
  activityResult.value = null
  followUpAnswer.value = ''
  followUpSubmitting.value = false
  activityAnswers.value = Object.fromEntries((activeActivity.value?.questions || []).map((question) => [question.id, question.type === 'short_answer' ? '' : null]))
}

async function submitFollowUp() {
  if (!activeActivity.value || !activityResult.value?.followUp || followUpSubmitting.value) return
  const answer = followUpAnswer.value.trim()
  if (!answer) {
    error.value = '请先回答针对性追问'
    return
  }
  if (answer.length > 4000) {
    error.value = '回答不能超过 4000 字'
    return
  }
  followUpSubmitting.value = true
  error.value = ''
  try {
    activityResult.value = await request(`/activities/${activeActivity.value.id}/attempts/${activityResult.value.id}/follow-up`, {
      method: 'POST',
      body: JSON.stringify({ answer }),
    })
    activeActivity.value = { ...activeActivity.value, latestAttempt: activityResult.value }
    activities.value = activities.value.map((item) => item.id === activeActivity.value.id ? activeActivity.value : item)
    followUpAnswer.value = ''
    await loadTeacherGuidance()
    await loadRecommendations()
  } catch (err) {
    error.value = err.message
  } finally {
    followUpSubmitting.value = false
  }
}

async function openSettings() {
  await settingsStore.open()
  showSettings.value = true
}

async function openNotes() {
  await loadNotes()
  resetNoteEditor()
  showNotes.value = true
}

function startNote() {
  const targetCard = card.value || noteCardOptions.value[0]
  if (!targetCard) return
  editingNote.value = null
  noteEditorMode.value = 'create'
  noteTargetCardId.value = targetCard.id
  noteTargetSectionId.value = card.value?.id === targetCard.id ? section.value?.id || '' : ''
  noteEditorTitle.value = ''
  noteEditorContent.value = ''
  noteEditorInitial.value = { title: '', content: '' }
  showNotes.value = true
}

async function loadNotes() {
  try {
    notesList.value = await request('/notes')
  } catch (_) {
    // Notes remain optional if the API is temporarily unavailable.
  }
}

function editNote(item) {
  editingNote.value = item
  noteEditorMode.value = 'edit'
  noteEditorTitle.value = item.title
  noteEditorContent.value = item.content
  noteEditorInitial.value = { title: item.title, content: item.content }
}

function noteSource(item) {
  const owner = homeCards.value.find(({ card: cardItem }) => cardItem.id === item.cardId)
  if (!owner) return '学习笔记'
  const sectionItem = owner.card.sections?.find((sectionItem) => sectionItem.id === item.sectionId)
  return sectionItem ? `${owner.card.title} · ${sectionItem.title}` : owner.card.title
}

function resetNoteEditor() {
  editingNote.value = null
  noteEditorMode.value = 'list'
  noteEditorTitle.value = ''
  noteEditorContent.value = ''
  noteEditorInitial.value = { title: '', content: '' }
  noteTargetCardId.value = ''
  noteTargetSectionId.value = ''
}

function closeNoteEditor() {
  if (noteEditorDirty.value && !window.confirm('当前笔记还没有保存，确定放弃修改吗？')) return
  resetNoteEditor()
}

function closeNotes() {
  if (noteEditorDirty.value && !window.confirm('当前笔记还没有保存，确定关闭吗？')) return
  showNotes.value = false
  resetNoteEditor()
}

async function createNote() {
  if (!noteTargetCardId.value || !noteEditorContent.value.trim()) return
  try {
    await request(`/cards/${noteTargetCardId.value}/notes`, {
      method: 'POST',
      body: JSON.stringify({
        title: noteEditorTitle.value.trim() || null,
        sectionId: noteTargetSectionId.value || null,
        content: noteEditorContent.value.trim(),
        sourceType: 'manual',
      }),
    })
    await loadNotes()
    resetNoteEditor()
  } catch (err) { error.value = err.message }
}

async function updateNote() {
  if (!editingNote.value || !noteEditorContent.value.trim()) return
  try {
    const updated = await request(`/notes/${editingNote.value.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: noteEditorTitle.value.trim() || '未命名笔记', content: noteEditorContent.value.trim() }),
    })
    notesList.value = notesList.value.map((item) => item.id === updated.id ? updated : item)
    resetNoteEditor()
  } catch (err) { error.value = err.message }
}

async function removeNote(item) {
  if (!window.confirm(`确定删除“${item.title}”吗？`)) return
  try {
    await request(`/notes/${item.id}`, { method: 'DELETE' })
    notesList.value = notesList.value.filter((noteItem) => noteItem.id !== item.id)
    if (editingNote.value?.id === item.id) closeNoteEditor()
  } catch (err) { error.value = err.message }
}

function changeProvider() {
  settingsStore.changeProvider()
}

function stopChatgptPolling() {
  settingsStore.stopChatgptPolling()
}

async function startChatgptLogin(method = 'device_code') {
  return settingsStore.startChatgptLogin(method)
}

async function completeChatgptLogin() {
  return settingsStore.completeChatgptLogin()
}

async function logoutChatgpt() {
  try {
    await settingsStore.logoutChatgpt()
  } catch (err) { error.value = err.message }
}

function roleRouteValue(role) {
  const configured = new Set(role.tasks.map((task) => taskRoutes.value[task] || ''))
  return configured.size === 1 ? [...configured][0] : '__custom__'
}

function setRoleRoute(role, model) {
  if (model === '__custom__') return
  const next = { ...taskRoutes.value }
  for (const task of role.tasks) {
    if (model) next[task] = model
    else delete next[task]
  }
  taskRoutes.value = next
}

async function loadProviderSettings() {
  return settingsStore.load()
}

async function fetchModels() {
  error.value = ''
  try {
    await settingsStore.fetchModels()
  } catch (err) { error.value = err.message }
}

async function saveProvider() {
  error.value = ''
  try {
    await settingsStore.saveProvider()
  } catch (err) { error.value = err.message }
}

async function saveModelAssignments() {
  error.value = ''
  try {
    await settingsStore.saveModelAssignments()
  } catch (err) { error.value = err.message }
}

async function startLearning() {
  if (!goal.value.trim()) return
  creatingCard.value = true
  error.value = ''
  try {
    const payload = { title: goal.value.trim(), learningGoal: goal.value.trim() }
    const createdSpace = editingFailedSpace.value
      ? await request(`/learning-spaces/${editingFailedSpace.value.id}/generation`, {
        method: 'PUT', body: JSON.stringify(payload),
      })
      : await request('/learning-spaces', { method: 'POST', body: JSON.stringify(payload) })
    goal.value = ''
    generationNotice.value = editingFailedSpace.value
      ? `课程“${createdSpace.title}”已重新提交，正在后台生成…`
      : `课程“${createdSpace.title}”已提交，正在后台生成…`
    editingFailedSpace.value = null
    await loadHistory()
  } catch (err) {
    error.value = err.message
  } finally {
    creatingCard.value = false
  }
}

function editFailedGeneration(item) {
  editingFailedSpace.value = item
  goal.value = item.learningGoal
  generationNotice.value = `正在编辑“${item.title}”，修改学习目标后重新生成。`
}

function cancelFailedGenerationEdit() {
  editingFailedSpace.value = null
  goal.value = ''
}

async function loadHistory() {
  return learningStore.loadHistory()
}

async function openHistory(item) {
  loading.value = true
  error.value = ''
  try {
    learningStore.setSpace(item)
    learningStore.setCard(await request(`/cards/${item.rootCardId}`), { root: true })
    learningStore.resetNavigation()
    learningView.value = 'content'
    activeActivity.value = null
    activityResult.value = null
    followUpAnswer.value = ''
    followUpSubmitting.value = false
    await loadTeacherGuidance()
    await loadRecommendations()
    await loadRelatedCards()
    await loadSectionActivities()
    await loadSectionConversations()
    await loadNotes()
    syncStudyUrl({ replace: true })
    await persistLearningRuntime('card_opened')
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function goHome() {
  learningStore.clearWorkspace()
  activeConversation.value = null
  showConversationList.value = false
  teacherGuidance.value = []
  recommendations.value = []
  selectedRecommendation.value = null
  conversations.value = []
  messages.value = []
  proposal.value = null
  error.value = ''
  window.history.replaceState({}, '', '/')
  loadHistory()
}

async function openSideConversation() {
  if (!card.value || !section.value || !input.value.trim()) return
  const question = input.value.trim()
  const side = await request(`/cards/${card.value.id}/conversations`, {
    method: 'POST',
    body: JSON.stringify({
      conversationType: 'side',
      sectionId: section.value.id,
      title: question.slice(0, 32),
      rootQuestion: question,
    }),
  })
  conversations.value.push(side)
  activeConversation.value = side
  showConversationList.value = false
  messages.value = []
  syncStudyUrl()
  await sendMessage(question)
}

async function loadSectionConversations(preferredConversationId = null) {
  if (!card.value || !section.value) {
    conversations.value = []
    activeConversation.value = null
    messages.value = []
    return
  }
  const next = await request(
    `/cards/${card.value.id}/conversations?sectionId=${encodeURIComponent(section.value.id)}`,
  )
  conversations.value = next
  const requestedId = preferredConversationId || activeConversation.value?.id
  activeConversation.value = next.find((item) => item.id === requestedId) || next[0] || null
  messages.value = []
  await loadConversationMessages(activeConversation.value)
}

async function loadConversationMessages(conversation) {
  const version = ++conversationLoadVersion
  if (!conversation) {
    messages.value = []
    return
  }
  const stored = await request(`/conversations/${conversation.id}/messages`)
  if (version !== conversationLoadVersion || activeConversation.value?.id !== conversation.id) return
  messages.value = stored.filter((message) => message.visibility !== 'internal').map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    senderId: message.senderId,
    senderName: message.senderName,
    senderRole: message.senderRole,
  }))
  const activeRun = await request(`/conversations/${conversation.id}/runs/active`)
  if (version !== conversationLoadVersion || activeConversation.value?.id !== conversation.id) return
  if (activeRun?.status === 'expired' || activeRun?.status === 'failed') {
    sideRun.value = { active: false, phase: '', label: '' }
    error.value = activeRun.errorMessage || '上一次 AI 请求未完成，请重新发送。'
  } else if (activeRun) {
    sideRun.value = {
      active: true,
      phase: activeRun.phase || 'waiting',
      label: activeRun.phase === 'guiding' ? '主线老师正在总结引导' : 'AI 正在处理中',
    }
    if (!messages.value.some((message) => message.pending)) {
      messages.value.push({
        role: 'assistant',
        content: '',
        pending: true,
        senderId: 'side_tutor',
        senderName: '答疑助教',
        senderRole: 'assistant',
      })
    }
  } else {
    sideRun.value = { active: false, phase: '', label: '' }
  }
}

async function sendMessage(text = input.value) {
  if (!activeConversation.value || !section.value || !text.trim() || sideRun.value.active) return
  if (activeConversation.value.sectionId !== section.value.id) {
    error.value = '请在该讨论所属的章节中继续提问。'
    return
  }
  error.value = ''
  sideRun.value = { active: true, phase: 'waiting', label: '正在等待 AI 响应' }
  input.value = ''
  await nextTick()
  resizeComposer()
  messages.value.push({ role: 'user', content: text })
  const assistant = { role: 'assistant', content: '', pending: true, senderId: 'side_tutor', senderName: '答疑助教', senderRole: 'assistant' }
  messages.value.push(assistant)
  try {
    const response = await fetch(`${base}/conversations/${activeConversation.value.id}/messages/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text, sectionId: activeConversation.value.sectionId }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body?.error?.message || body?.detail || '无法建立 AI 流式连接')
    }
    if (!response.body) throw new Error('无法建立 AI 流式连接')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        const dataLine = block.split('\n').find((line) => line.startsWith('data:'))
        if (!dataLine) continue
        try {
          const data = JSON.parse(dataLine.slice(5))
          if (block.includes('run.phase') || block.includes('run.started')) {
            sideRun.value = { active: true, phase: data.phase || 'waiting', label: data.label || 'AI 正在处理' }
          }
          if (block.includes('message.started')) {
            assistant.senderId = data.senderId || assistant.senderId
            assistant.senderName = data.senderName || assistant.senderName
            assistant.senderRole = data.senderRole || assistant.senderRole
          }
          if (block.includes('message.delta')) {
            assistant.pending = false
            sideRun.value = { active: true, phase: 'answering', label: '答疑助教正在回答' }
            assistant.content += data.delta || ''
          }
          if (block.includes('related_card.proposed')) {
            proposal.value = data
            recommendations.value = [data, ...recommendations.value.filter((item) => item.proposalId !== data.proposalId)]
          }
          if (block.includes('guidance.updated')) teacherGuidance.value = [...teacherGuidance.value, data]
          if (block.includes('guidance.failed')) error.value = `课程导师引导失败：${data.message || '未知错误'}`
          if (block.includes('run.failed')) {
            error.value = data.message || 'AI 服务调用失败'
            if (!assistant.content) messages.value = messages.value.filter((message) => message !== assistant)
          }
          if (block.includes('run.completed') || block.includes('run.failed')) {
            assistant.pending = false
            sideRun.value = { active: false, phase: '', label: '' }
          }
        } catch (_) {}
      }
      if (done) break
    }
  } catch (err) {
    error.value = err.message
    if (!assistant.content) messages.value = messages.value.filter((message) => message !== assistant)
  } finally {
    sideRun.value = { active: false, phase: '', label: '' }
  }
}

async function acceptProposal(item = proposal.value) {
  // A bare @click="acceptProposal" passes the MouseEvent and bypasses the
  // default parameter. Keep the handler defensive so UI events can never be
  // interpolated into `/proposals/undefined/...`.
  const candidate = proposalId(item) ? item : proposal.value
  const id = proposalId(candidate)
  if (!candidate || !id) {
    await loadRecommendations()
    error.value = '推荐信息尚未同步，请稍后再试'
    return
  }
  creatingBranch.value = true
  try {
    const sourceEntry = { cardId: card.value.id, sectionId: section.value?.id || null }
    const generatedCard = await request(`/proposals/${id}/accept`, { method: 'POST' })
    await openCard(generatedCard, sourceEntry, { eventType: 'branch_entered' })
    recommendations.value = recommendations.value.filter((recommendation) => proposalId(recommendation) !== id)
    proposal.value = null
    selectedRecommendation.value = null
  } catch (err) { error.value = err.message } finally { creatingBranch.value = false }
}

async function continueRecommendation(item) {
  const id = proposalId(item)
  if (!id) {
    await loadRecommendations()
    error.value = '推荐信息尚未同步，请稍后再试'
    return
  }
  startingDiscussion.value = true
  error.value = ''
  try {
    const conversation = await request(`/proposals/${id}/discussion`, { method: 'POST' })
    conversations.value = [...conversations.value, conversation]
    activeConversation.value = conversation
    messages.value = []
    proposal.value = null
    selectedRecommendation.value = null
    await sendMessage(`我想先了解“${item.title}”，请先说明它和当前章节的关系，以及我是否需要为它创建学习分支。`)
    await loadRecommendations()
  } catch (err) { error.value = err.message } finally { startingDiscussion.value = false }
}

async function deleteRecommendation(item) {
  const id = proposalId(item)
  if (!id) {
    await loadRecommendations()
    error.value = '推荐信息尚未同步，请稍后再试'
    return
  }
  try {
    await request(`/proposals/${id}/reject`, { method: 'POST' })
    recommendations.value = recommendations.value.filter((recommendation) => proposalId(recommendation) !== id)
    if (proposalId(proposal.value) === id) proposal.value = null
    selectedRecommendation.value = null
  } catch (err) { error.value = err.message }
}

async function loadRelatedCards() {
  if (!space.value || !card.value || !section.value) {
    relatedCards.value = []
    return
  }
  const cards = await request(`/learning-spaces/${space.value.id}/cards`)
  relatedCards.value = cards.filter((item) => item.cardType === 'related'
    && item.parentCardId === card.value.id
    && item.parentSectionId === section.value.id)
}

async function openCard(target, navigationContext = null, options = {}) {
  if (navigationContext) {
    learningStore.pushNavigation(navigationContext)
  } else if (!options.preserveNavigation) {
    learningStore.resetNavigation()
  }
  learningStore.setCard(target)
  learningView.value = 'content'
  activeActivity.value = null
  activityResult.value = null
  activityAnswers.value = {}
  followUpAnswer.value = ''
  followUpSubmitting.value = false
  showConversationList.value = false
  selectedRecommendation.value = null
  proposal.value = null
  activeSection.value = 0
  await loadTeacherGuidance()
  await loadRecommendations()
  await loadRelatedCards()
  await loadSectionActivities()
  await loadSectionConversations()
  syncStudyUrl({ replace: window.location.pathname.startsWith('/study/') })
  if (options.persist !== false) await persistLearningRuntime(options.eventType || 'card_opened')
}

async function openRelatedCard(target) {
  if (!card.value) return
  await openCard(target, { cardId: card.value.id, sectionId: section.value?.id || null }, { eventType: 'branch_entered' })
}

async function openHistoryCard(spaceItem, target) {
  loading.value = true
  error.value = ''
  try {
    learningStore.setSpace(spaceItem)
    learningStore.setCard(target, { root: target.cardType === 'root' })
    await openCard(target, null)
    await loadNotes()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function deleteHomeCard(item) {
  if (!window.confirm(`确定删除“${item.card.title}”吗？\n\n知识卡会从首页隐藏，但讨论、消息、笔记和学习分支都会保留。`)) return
  try {
    await request(`/cards/${item.card.id}`, { method: 'DELETE' })
    historyCards.value = {
      ...historyCards.value,
      [item.space.id]: (historyCards.value[item.space.id] || []).filter((cardItem) => cardItem.id !== item.card.id),
    }
    if (card.value?.id === item.card.id) goHome()
  } catch (err) {
    error.value = err.message
  }
}

function openHomeCard(item) {
  if (item.card.cardType === 'root') {
    openHistory(item.space)
  } else {
    openHistoryCard(item.space, item.card)
  }
}

async function returnToMain() {
  const context = navigationStack.value[navigationStack.value.length - 1]
  if (!context) return
  learningStore.popNavigation()
  try {
    const sourceCard = await request(`/cards/${context.cardId}`)
    await openCard(sourceCard, null, { preserveNavigation: true, persist: false })
    const sourceIndex = sourceCard.sections?.findIndex((item) => item.id === context.sectionId) ?? -1
    activeSection.value = sourceIndex >= 0 ? sourceIndex : 0
    await loadTeacherGuidance()
    await loadRelatedCards()
    await loadSectionConversations()
    syncStudyUrl({ replace: true })
    await persistLearningRuntime('branch_returned')
  } catch (err) {
    error.value = err.message
  }
}

async function selectConversation(item) {
  if (item.sectionId !== section.value?.id) {
    error.value = '该讨论属于其他章节。'
    return
  }
  activeConversation.value = item
  showConversationList.value = false
  messages.value = []
  syncStudyUrl({ replace: true })
  await loadConversationMessages(item)
}

async function openGuidanceDiscussion(guidance) {
  const conversation = conversations.value.find((item) => item.id === guidance.sourceConversationId)
  if (!conversation) {
    error.value = '对应讨论已不可用。'
    return
  }
  await selectConversation(conversation)
  showMobileDiscussion.value = true

  const messageIds = [guidance.sourceQuestionMessageId, guidance.sourceAnswerMessageId].filter(Boolean)
  if (!messageIds.length) return
  highlightedMessageIds.value = messageIds
  await nextTick()
  document.getElementById(`discussion-message-${messageIds[0]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  window.setTimeout(() => {
    highlightedMessageIds.value = []
  }, 2200)
}

async function loadTeacherGuidance() {
  const version = ++guidanceLoadVersion
  const sectionId = card.value?.sections?.[activeSection.value]?.id
  if (!card.value || !sectionId) {
    teacherGuidance.value = []
    return
  }
  try {
    let stored = await request(`/cards/${card.value.id}/sections/${sectionId}/guidance`)
    if (!stored.length) {
      await request(`/cards/${card.value.id}/sections/${sectionId}/guidance`, { method: 'POST' })
      stored = await request(`/cards/${card.value.id}/sections/${sectionId}/guidance`)
    }
    if (version === guidanceLoadVersion) teacherGuidance.value = stored
  } catch (err) {
    if (version === guidanceLoadVersion) error.value = err.message
  }
}

async function loadRecommendations() {
  if (!card.value || !section.value) {
    recommendations.value = []
    return
  }
  try {
    const all = await request(`/cards/${card.value.id}/proposals`)
    recommendations.value = all.filter((item) => item.sectionId === section.value.id)
  } catch (err) {
    error.value = err.message
  }
}

async function selectSection(index) {
  activeSection.value = index
  learningView.value = 'content'
  activeActivity.value = null
  activityResult.value = null
  activityAnswers.value = {}
  followUpAnswer.value = ''
  followUpSubmitting.value = false
  await loadRelatedCards()
  await loadTeacherGuidance()
  await loadSectionActivities()
  await loadSectionConversations()
  syncStudyUrl({ replace: true })
  await persistLearningRuntime('section_changed')
}

function previousSection() {
  if (activeSection.value > 0) selectSection(activeSection.value - 1)
}

function nextSection() {
  if (card.value?.sections && activeSection.value < card.value.sections.length - 1) {
    selectSection(activeSection.value + 1)
  }
}

</script>

<template>
  <main class="shell" :class="`theme-${theme}`">
    <section v-if="authChecked && !authUser" class="auth-screen">
      <div class="auth-card">
        <div class="eyebrow">STUDYCENTER</div>
        <h1>{{ authMode === 'login' ? '欢迎回来' : '创建学习账号' }}</h1>
        <p>{{ authMode === 'login' ? '登录后继续你的学习空间。' : '使用邀请码加入 StudyCenter。' }}</p>
        <form @submit.prevent="submitAuth">
          <label>用户名<input v-model="authUsername" autocomplete="username" placeholder="用户名" required /></label>
          <label>密码<input v-model="authPassword" type="password" autocomplete="current-password" placeholder="至少 8 位" required /></label>
          <label v-if="authMode === 'register'">邀请码<input v-model="authInviteCode" placeholder="输入邀请码" required /></label>
          <button class="primary auth-submit" :disabled="authLoading">{{ authLoading ? '处理中…' : authMode === 'login' ? '登录' : '注册并登录' }}</button>
        </form>
        <p v-if="error" class="error">{{ error }}</p>
        <button class="auth-switch" @click="authMode = authMode === 'login' ? 'register' : 'login'; error = ''">
          {{ authMode === 'login' ? '还没有账号？使用邀请码注册' : '已有账号？返回登录' }}
        </button>
      </div>
    </section>
    <template v-else-if="authUser">
    <header class="topbar">
      <button class="brand" @click="goHome" title="返回首页">Study<span>Center</span></button>
      <div v-if="space" class="crumb">学习空间 / {{ card?.title }} / {{ section?.title || '未开始' }}</div>
      <div class="status">{{ space ? `课程生成：${knowledgeCardModel}` : '已登录' }}</div>
      <button class="notes-button" @click="openNotes">笔记</button>
      <button class="theme-button" @click="toggleTheme" :title="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'">{{ theme === 'light' ? '深色' : '浅色' }}</button>
      <button class="settings-button" @click="openSettings">设置</button>
      <button class="settings-button" @click="logout">退出</button>
    </header>

    <section v-if="!space" class="welcome">
      <p class="eyebrow">AI LEARNING SPACE</p>
      <h1>从一个问题，开始一条属于你的学习路径。</h1>
      <p class="lead">课程设计 Agent 会先生成一张知识卡。之后的课程内容、问题讨论和学习笔记，都围绕它展开。</p>
      <form @submit.prevent="startLearning" class="start-form">
        <textarea v-model="goal" placeholder="例如：我想系统理解 Kubernetes 容器隔离，并能看懂 Namespace 和 cgroups 的关系" autofocus></textarea>
        <div class="start-options"><span class="route-hint">{{ editingFailedSpace ? `正在重新编辑：${editingFailedSpace.title}` : `课程生成使用：${knowledgeCardModel}` }}</span><button :disabled="creatingCard">{{ creatingCard ? '正在提交…' : editingFailedSpace ? '重新生成课程' : '创建知识卡' }}</button><button v-if="editingFailedSpace" type="button" class="secondary" @click="cancelFailedGenerationEdit">取消</button></div>
        <div v-if="creatingCard" class="create-card-status"><i class="status-spinner"></i><span>正在规划课程结构并生成章节内容…</span></div>
      </form>
      <p v-if="generationNotice" class="generation-notice">{{ generationNotice }}</p>
      <div v-if="homeCards.length || creatingSpaces.length" class="history">
        <div class="history-title">我的知识卡</div>
        <div v-for="item in creatingSpaces" :key="item.id" class="history-item generation-item">
          <div class="history-open">
            <span>{{ item.title }}</span>
            <small>{{ item.generationStatus === 'queued' ? '排队中' : item.generationStatus === 'failed' ? `生成失败：${item.generationError || '请重试'}` : '正在生成课程内容…' }}</small>
          </div>
          <button v-if="item.generationStatus === 'failed'" class="history-delete retry-generation" @click="editFailedGeneration(item)">重新编辑</button>
        </div>
        <div v-for="item in homeCards" :key="item.card.id" class="history-item">
          <button class="history-open" @click="openHomeCard(item)">
            <span>{{ item.card.title }}</span>
            <small>{{ new Date(item.space.createdAt).toLocaleDateString('zh-CN') }} · 开始学习 →</small>
          </button>
          <button class="history-delete" title="删除知识卡" @click.stop="deleteHomeCard(item)">删除</button>
        </div>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <div v-if="showSettings" class="modal-backdrop" @click.self="showSettings = false">
      <section class="settings-modal">
        <div class="settings-head"><div><div class="panel-title">模型设置</div><p>Key 会在后端加密保存，前端不会保存明文。</p></div><button @click="showSettings = false">×</button></div>
        <label>Provider<select v-model="selectedProvider" @change="changeProvider"><option value="deepseek">DeepSeek</option><option value="google">Google Gemini</option><option value="opencode">OpenCode Zen</option><option value="openrouter">OpenRouter</option><option value="anthropic">Anthropic</option><option value="chatgpt">ChatGPT (Plus/Pro)</option></select></label>
        <div v-if="isChatGpt" class="chatgpt-login">
          <div class="catalog-title">ChatGPT Plus/Pro 订阅登录（无需 API Key）</div>
          <div v-if="providerStatus.providers?.chatgpt" class="chatgpt-status">
            <span class="chatgpt-dot ok"></span>
            <span>已登录</span>
            <button class="model-fetch-button" :disabled="fetchingModels" @click="fetchModels">{{ fetchingModels ? '获取中…' : '获取模型' }}</button>
            <button class="secondary" @click="logoutChatgpt">退出登录</button>
          </div>
          <div v-else-if="chatgptLogin.status === 'pending'" class="chatgpt-pending">
            <p>在浏览器打开 <a :href="chatgptLogin.verificationUri" target="_blank" rel="noopener">{{ chatgptLogin.verificationUri }}</a> 并输入设备码：</p>
            <div class="device-code">{{ chatgptLogin.userCode }}</div>
            <p class="provider-hint">等待授权中…</p>
          </div>
          <div v-else-if="chatgptLogin.status === 'browser'" class="chatgpt-pending">
            <p>1. 打开 <a :href="chatgptLogin.authUrl" target="_blank" rel="noopener">授权链接</a> 完成登录。</p>
            <p>2. 页面会跳转到 <code>localhost:1455</code>（可能显示无法访问），复制地址栏里的完整 URL 粘到下面：</p>
            <input v-model="chatgptLogin.input" placeholder="http://localhost:1455/auth/callback?code=...&state=..." />
            <button class="primary" :disabled="!chatgptLogin.input.trim()" @click="completeChatgptLogin">完成授权</button>
            <p v-if="chatgptLogin.error" class="error">{{ chatgptLogin.error }}</p>
          </div>
          <div v-else>
            <div class="provider-actions">
              <button class="secondary" :disabled="chatgptLogin.status === 'starting'" @click="startChatgptLogin('browser')">浏览器授权</button>
              <button class="primary" :disabled="chatgptLogin.status === 'starting'" @click="startChatgptLogin('device_code')">设备码登录</button>
            </div>
            <p v-if="chatgptLogin.error" class="error">{{ chatgptLogin.error }}</p>
          </div>
        </div>
        <label v-if="!isChatGpt">API Key<div class="key-row"><input v-if="editingKey || !keyConfigured" v-model="apiKey" type="password" placeholder="输入 API Key" autocomplete="off" /><div v-else class="masked-key">*****</div><button v-if="keyConfigured && !editingKey" class="edit-key" @click="editingKey = true">编辑</button><button :disabled="fetchingModels || (!apiKey && !keyConfigured)" @click="fetchModels">{{ fetchingModels ? '获取中…' : '获取模型' }}</button></div></label>
        <div v-if="availableModels.length" class="model-catalog"><div class="catalog-title">选择此 Provider 可使用的模型</div><label v-for="model in availableModels" :key="model" class="model-check"><input v-model="selectedModels" type="checkbox" :value="model" /><span>{{ model }}</span></label></div>
        <div class="provider-actions"><button class="primary" :disabled="savingSettings || ((!apiKey && !keyConfigured) || !selectedModels.length)" @click="saveProvider">{{ savingSettings ? '保存中…' : '保存 Provider' }}</button></div>
        <section v-if="allModelOptions.length" class="model-assignments">
          <div class="default-model-setting">
            <div class="catalog-title">全局默认模型</div>
            <p>未单独指定的任务将使用此模型。</p>
            <select v-model="selectedDefaultModel"><option value="">请选择默认模型</option><option v-for="option in allModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
          </div>
          <div class="model-role-routes">
            <div class="catalog-title">模型分工</div>
            <p class="model-routing-hint">按学习流程选择模型；不设置则跟随全局默认模型。</p>
            <label v-for="role in modelRoleDefinitions" :key="role.id" class="model-role-route">
              <span><strong>{{ role.label }}</strong><small>{{ role.hint }}</small></span>
              <select :value="roleRouteValue(role)" @change="setRoleRoute(role, $event.target.value)">
                <option value="">跟随默认模型</option>
                <option v-if="roleRouteValue(role) === '__custom__'" value="__custom__" disabled>已在高级设置中分别配置</option>
                <option v-for="option in allModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <button class="advanced-routes-toggle" @click="showAdvancedRoutes = !showAdvancedRoutes">{{ showAdvancedRoutes ? '收起高级任务路由' : '高级任务路由' }} <span>{{ showAdvancedRoutes ? '⌃' : '⌄' }}</span></button>
            <div v-if="showAdvancedRoutes" class="task-routes">
              <div class="catalog-title">单项覆盖</div>
              <p class="model-routing-hint">只在确有需要时修改；单项设置会覆盖所属模型分工。</p>
              <label v-for="task in taskDefinitions" :key="task.id" class="task-route"><span>{{ task.label }}</span><select v-model="taskRoutes[task.id]"><option value="">跟随默认模型</option><option v-for="option in allModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            </div>
            <div class="model-assignment-actions"><button class="primary" :disabled="savingModelAssignments" @click="saveModelAssignments">{{ savingModelAssignments ? '保存中…' : '保存模型分工' }}</button></div>
          </div>
        </section>
        <div class="provider-hint">已配置：{{ Object.entries(providerStatus.providers).filter(([, value]) => value).map(([key]) => key).join('、') || '暂无' }}</div>
      </section>
    </div>

    <div v-if="showNotes" class="notes-backdrop" @click.self="closeNotes">
      <aside class="notes-drawer">
        <div class="notes-drawer-head"><div><div class="panel-title">{{ noteEditorMode === 'list' ? '我的笔记' : noteEditorMode === 'create' ? '记笔记' : '编辑笔记' }}</div><p>{{ noteEditorMode === 'list' ? '记录、整理和回看学习过程中的重要内容。' : noteEditorSource }}</p></div><button @click="closeNotes">×</button></div>
        <div v-if="noteEditorMode !== 'list'" class="note-editor">
          <div v-if="noteEditorMode === 'create'" class="note-target-fields">
            <label>知识卡<select v-model="noteTargetCardId" @change="noteTargetSectionId = ''"><option v-for="cardItem in noteCardOptions" :key="cardItem.id" :value="cardItem.id">{{ cardItem.title }}</option></select></label>
            <label>章节<select v-model="noteTargetSectionId"><option value="">整张知识卡</option><option v-for="sectionItem in noteTargetSections" :key="sectionItem.id" :value="sectionItem.id">{{ sectionItem.title }}</option></select></label>
          </div>
          <input v-model="noteEditorTitle" placeholder="笔记标题" />
          <textarea v-model="noteEditorContent" placeholder="写下你的理解…"></textarea>
          <div class="note-editor-actions"><button class="secondary" @click="closeNoteEditor">取消</button><button class="primary" :disabled="!noteEditorContent.trim()" @click="noteEditorMode === 'create' ? createNote() : updateNote()">{{ noteEditorMode === 'create' ? '保存笔记' : '保存修改' }}</button></div>
        </div>
        <div v-else class="notes-list">
          <div class="notes-list-toolbar"><button :disabled="!noteCardOptions.length" @click="startNote">＋ 新建笔记</button></div>
          <div v-if="!notesList.length" class="notes-empty">还没有笔记。<br />在学习页面记录第一条笔记吧。</div>
          <article v-for="item in notesList" :key="item.id" class="note-item">
            <div class="note-item-head"><strong>{{ item.title }}</strong><div><button @click="editNote(item)">编辑</button><button @click="removeNote(item)">删除</button></div></div>
            <p>{{ item.content }}</p>
            <small>{{ noteSource(item) }} · {{ new Date(item.updatedAt).toLocaleString('zh-CN') }}</small>
          </article>
        </div>
      </aside>
    </div>

    <div v-if="selectedRecommendation" class="recommendation-backdrop" @click.self="selectedRecommendation = null">
      <section class="recommendation-modal">
        <div class="recommendation-modal-head"><div><span class="recommendation-kicker">{{ proposalKicker(selectedRecommendation) }}</span><h3>{{ selectedRecommendation.title }}</h3></div><button @click="selectedRecommendation = null">×</button></div>
        <p>{{ selectedRecommendation.reason }}</p>
        <div class="recommendation-source">来自：当前知识卡 · {{ section?.title }}</div>
            <div class="recommendation-actions"><button class="danger" :disabled="creatingBranch || startingDiscussion" @click="deleteRecommendation(selectedRecommendation)">删除建议</button><button class="secondary" :disabled="creatingBranch || startingDiscussion" @click="continueRecommendation(selectedRecommendation)">{{ startingDiscussion ? '正在创建讨论…' : '继续讨论' }}</button><button class="primary" :disabled="creatingBranch || startingDiscussion" @click="acceptProposal(selectedRecommendation)">{{ creatingBranch ? '正在创建分支…' : '创建学习分支' }}</button></div>
      </section>
    </div>

    <section v-if="space && !card" class="loading-state">
      正在恢复学习空间…
    </section>

    <section v-if="space && card" class="workspace" :class="{ 'sidebar-collapsed': !showKnowledgeSidebar, 'mobile-discussion-open': showMobileDiscussion }" :style="{ '--chat-width': `${chatWidth}px` }">
      <aside class="sidebar panel">
        <div class="sidebar-head"><div class="panel-title">学习导航</div><button class="sidebar-toggle" title="收起学习导航" @click="toggleKnowledgeSidebar">‹</button></div>
        <div class="tree-label">章节目录</div>
        <button v-for="(item, index) in card.sections" :key="item.id" class="tree-item" :class="{ active: index === activeSection }" @click="selectSection(index)">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>{{ item.title }}
        </button>
        <button class="activity-nav-item" :class="{ active: learningView === 'activity' }" @click="openQuiz()">
          <span>✓</span>理解检查 <small>{{ quizStatusLabel }}</small>
        </button>
        <div class="tree-label related">本节学习分支</div>
        <button v-for="related in relatedCards" :key="related.id" class="related-card" :class="{ active: card.id === related.id }" @click="openRelatedCard(related)">
          <span>↳ {{ relationLabel(related.relationType) }} · </span>{{ related.title }}
        </button>
        <div v-if="!relatedCards.length" class="empty-related">从问题讨论中生成<br />新的学习分支</div>
        <div v-if="recommendations.length" class="tree-label related">{{ recommendationGroupLabel }}</div>
        <button v-for="item in recommendations" :key="item.id || item.proposalId" class="recommendation-link" @click="selectedRecommendation = item">
          <span>＋ {{ relationLabel(item.relationType || 'prerequisite') }} · </span>{{ item.title }}
        </button>
      </aside>

      <section class="board panel">
        <div class="board-meta"><div class="board-location"><button v-if="!showKnowledgeSidebar" class="sidebar-toggle collapsed-toggle" title="展开学习导航" @click="toggleKnowledgeSidebar">› <span>学习导航</span></button><span>第 {{ activeSection + 1 }} 节</span></div><div class="board-actions"><span>{{ learningView === 'activity' ? '理解检查' : sectionTypeLabel }}</span><button @click="startNote">＋ 记笔记</button><button class="mobile-discussion-toggle" @click="showMobileDiscussion = true">讨论</button></div></div>
        <div class="board-scroll">
          <button v-if="isRelatedCard" class="back-main" @click="returnToMain">← 返回来源知识卡</button>
          <section v-if="learningView === 'activity'" class="quiz-screen">
            <div v-if="activityLoading" class="activity-loading"><i class="status-spinner"></i>正在根据本节内容准备理解检查…</div>
            <template v-else-if="activeActivity">
              <div class="quiz-intro"><div><span class="quiz-kicker">学习活动</span><h2>{{ activeActivity.title }}</h2><p>{{ activeActivity.objective }}</p></div><button class="quiz-close" @click="closeQuiz">返回课程内容</button></div>
              <div v-if="!activityResult" class="quiz-questions">
                <article v-for="(question, index) in activeActivity.questions" :key="question.id" class="quiz-question">
                  <h3>{{ index + 1 }}. {{ question.prompt }}</h3>
                  <div v-if="question.type === 'short_answer'" class="quiz-options"><textarea v-model="activityAnswers[question.id]" placeholder="用一两句话写下你的理解…"></textarea></div>
                  <div v-else class="quiz-options">
                    <label v-for="option in (question.options?.length ? question.options : [{ id: true, text: '正确' }, { id: false, text: '错误' }])" :key="String(option.id)"><input v-model="activityAnswers[question.id]" :name="question.id" :type="question.type === 'true_false' ? 'radio' : 'radio'" :value="option.id" /><span>{{ option.text }}</span></label>
                  </div>
                </article>
                <button class="primary quiz-submit" :disabled="activitySubmitting" @click="submitQuiz">{{ activitySubmitting ? '正在分析你的回答…' : '提交答案' }}</button>
              </div>
              <section v-else class="quiz-result">
                <div class="quiz-score"><strong>{{ activityResult.score }}</strong><span>分</span><em>{{ activityResult.masteryLevel === 'mastered' ? '已掌握' : activityResult.masteryLevel === 'developing' ? '掌握中' : '需要复习' }}</em></div>
                <p class="quiz-diagnostic">{{ activityResult.diagnosticSummary }}</p>
                <article v-for="(result, index) in activityResult.results" :key="result.questionId" class="quiz-result-item" :class="{ correct: result.correct }"><div><b>{{ result.correct ? '✓' : '!' }}</b><strong>第 {{ index + 1 }} 题</strong></div><p>{{ result.feedback }}</p><small v-if="result.referenceAnswer">参考答案：{{ result.referenceAnswer }}</small></article>
                <section v-if="activityResult.followUp" class="quiz-follow-up">
                  <div class="quiz-follow-up-head"><span class="quiz-kicker">针对性追问</span><span v-if="activityResult.followUp.status === 'completed'" class="quiz-follow-up-status">已完成</span></div>
                  <p class="quiz-follow-up-prompt">{{ activityResult.followUp.prompt }}</p>
                  <template v-if="activityResult.followUp.status === 'pending'">
                    <textarea v-model="followUpAnswer" class="quiz-follow-up-input" maxlength="4000" placeholder="补充说明你的理解…"></textarea>
                    <div class="quiz-follow-up-meta"><span>{{ followUpAnswer.length }} / 4000</span><button class="primary" :disabled="followUpSubmitting" @click="submitFollowUp">{{ followUpSubmitting ? '正在分析…' : '提交追问回答' }}</button></div>
                  </template>
                  <div v-else-if="activityResult.followUp.result" class="quiz-follow-up-feedback" :class="{ correct: activityResult.followUp.result.correct }">
                    <strong>{{ activityResult.followUp.result.correct ? '回答通过' : '还需要补充' }}</strong>
                    <p>{{ activityResult.followUp.result.feedback }}</p>
                    <small v-if="activityResult.postFollowUpMastery">当前掌握状态：{{ masteryLabel(activityResult.postFollowUpMastery) }}</small>
                  </div>
                </section>
                <div class="quiz-result-actions"><button class="secondary" @click="retryQuiz">重新尝试</button><button class="primary" @click="closeQuiz">返回课程内容</button></div>
              </section>
            </template>
          </section>
          <article v-else class="markdown">
            <h2>{{ section?.title }}</h2>
            <div class="content" v-html="renderedContent"></div>
          </article>
        </div>
        <nav class="section-navigation" aria-label="章节导航">
          <button :disabled="activeSection === 0" @click="previousSection">← 上一节</button>
          <span>第 {{ activeSection + 1 }} / {{ card.sections.length }} 节</span>
          <button :disabled="activeSection === card.sections.length - 1" @click="nextSection">下一节 →</button>
        </nav>
        <section class="teacher-guidance" :class="{ collapsed: !showTeacherGuidance }">
          <div class="teacher-guidance-head">
            <div><span class="teacher-label">导师引导</span><span v-if="teacherGuidance.length" class="teacher-count">{{ teacherGuidance.length }} 条</span></div>
            <button @click="showTeacherGuidance = !showTeacherGuidance">{{ showTeacherGuidance ? '收起' : '展开' }}</button>
          </div>
          <div v-if="showTeacherGuidance" class="teacher-guidance-body">
            <article v-for="item in teacherGuidance" :key="item.id" class="teacher-guidance-item">
              <button v-if="item.trigger === 'side_question' && item.sourceConversationId" class="teacher-guidance-trigger teacher-guidance-link" @click="openGuidanceDiscussion(item)">讨论后归位 · {{ guidanceQuestion(item) }}</button>
              <span v-else class="teacher-guidance-trigger">{{ item.trigger === 'section_enter' ? '进入本节' : item.trigger === 'activity_result' ? '理解检查后' : '讨论后归位' }}</span>
              <p>{{ item.content }}</p>
            </article>
            <div v-if="!teacherGuidance.length" class="teacher-guidance-empty">正在准备本节的学习引导…</div>
          </div>
        </section>
      </section>

      <div class="resize-handle" role="separator" aria-label="调整会话宽度" :aria-valuenow="chatWidth" aria-valuemin="280" aria-valuemax="560" tabindex="0" @pointerdown="startChatResize" @keydown.left.prevent="adjustChatWidth(20)" @keydown.right.prevent="adjustChatWidth(-20)"></div>

      <aside class="chat panel">
        <div class="chat-head">
          <div class="chat-heading"><span class="chat-region-label">讨论区</span><button class="conversation-trigger" :disabled="sideRun.active" @click="showConversationList = !showConversationList" :aria-expanded="showConversationList"><span class="panel-title">{{ activeConversation?.title || '新问题讨论' }}</span><span class="conversation-trigger-icon">⌄</span></button></div>
          <div class="chat-head-actions"><button class="new-chat" :disabled="sideRun.active" @click="activeConversation = null; messages = []; showConversationList = false">＋ 新建讨论</button><button class="mobile-chat-close" aria-label="关闭讨论区" @click="showMobileDiscussion = false">×</button></div>
        </div>
        <div v-if="showConversationList" class="conversation-menu-backdrop" @click="showConversationList = false">
          <div class="conversation-list" @click.stop>
            <div class="conversation-list-title">本节历史会话</div>
            <button v-for="item in conversations" :key="item.id" @click="selectConversation(item)" :class="{ selected: activeConversation?.id === item.id }">
              <small>{{ item.conversationType === 'main' ? '导师' : '讨论' }}</small>{{ item.title }}
            </button>
            <div v-if="!conversations.length" class="conversation-list-empty">本节暂无讨论</div>
          </div>
        </div>
        <div class="messages">
          <div v-for="(message, index) in messages" :id="message.id ? `discussion-message-${message.id}` : undefined" :key="message.id || index" class="message" :class="[message.role, { pending: message.pending, highlighted: highlightedMessageIds.includes(message.id) }]">
            <span>{{ message.senderName || (message.role === 'user' ? '你' : 'AI') }}</span><i v-if="message.pending" class="typing-dots"><b></b><b></b><b></b></i>
            <div v-if="message.role === 'assistant'" class="message-markdown" v-html="renderMessage(message.content)"></div>
            <div v-else class="message-plain">{{ message.content }}</div>
          </div>
          <div v-if="!messages.length" class="chat-empty">从当前章节提出一个问题，开始独立讨论。</div>
          <div v-if="proposal" class="proposal-card">
            <div class="proposal-kicker">{{ proposalKicker(proposal) }}</div>
            <strong>{{ proposal.title }}</strong>
            <p>{{ proposal.reason }}</p>
            <div class="proposal-actions"><button @click="selectedRecommendation = proposal">查看建议</button><button :disabled="creatingBranch" @click="acceptProposal()">{{ creatingBranch ? '正在创建…' : '创建学习分支' }}</button></div>
          </div>
        </div>
        <div v-if="sideRun.active" class="chat-run-status"><i class="status-spinner"></i>{{ sideRun.label }}</div>
        <p v-if="error" class="error chat-error">{{ error }}</p>
        <form class="composer" @submit.prevent="activeConversation ? sendMessage() : openSideConversation()">
          <textarea ref="composerInput" v-model="input" :disabled="sideRun.active" placeholder="问问当前内容…（Shift / Ctrl / ⌘ + Enter 发送）" @input="resizeComposer" @keydown="handleComposerKeydown"></textarea>
          <button :disabled="sideRun.active">{{ sideRun.active ? '回答中…' : '发送 ↗' }}</button>
        </form>
      </aside>
    </section>
    </template>
  </main>
</template>
