import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'

const initialChatgptLogin = () => ({
  status: 'idle', method: 'device_code', userCode: '', verificationUri: '', authUrl: '', input: '', sessionId: '', error: '',
})

export const useSettingsStore = defineStore('settings', () => {
  const status = ref<any>({ activeProvider: null, providers: {} })
  const selectedProvider = ref('deepseek')
  const apiKey = ref('')
  const availableModels = ref<string[]>([])
  const selectedModels = ref<string[]>([])
  const modelDiscovery = ref({ source: '', warning: '', keyValidated: false })
  const selectedDefaultModel = ref('')
  const taskRoutes = ref({})
  const showAdvancedRoutes = ref(false)
  const saving = ref(false)
  const fetchingModels = ref(false)
  const editingKey = ref(false)
  const savingModelAssignments = ref(false)
  const chatgptLogin = ref(initialChatgptLogin())
  let chatgptPollTimer = null

  async function load() {
    try {
      status.value = await request<any>('/settings/providers')
    } catch (_) {
      // Keep settings usable when the provider endpoint is temporarily unavailable.
    }
    return status.value
  }

  async function open() {
    await load()
    selectedProvider.value = ['deepseek', 'google', 'opencode', 'openrouter', 'anthropic', 'glm', 'zai', 'chatgpt'].includes(status.value.activeProvider)
      ? status.value.activeProvider : 'deepseek'
    selectedModels.value = [...(status.value.models?.[selectedProvider.value] || [])]
    selectedDefaultModel.value = status.value.activeModel
      ? `${status.value.activeProvider}:${status.value.activeModel}` : ''
    taskRoutes.value = { ...(status.value.taskRoutes || {}) }
    availableModels.value = [...selectedModels.value]
    modelDiscovery.value = { source: '', warning: '', keyValidated: false }
    apiKey.value = ''
    editingKey.value = false
    showAdvancedRoutes.value = false
  }

  function changeProvider() {
    availableModels.value = [...(status.value.models?.[selectedProvider.value] || [])]
    selectedModels.value = [...availableModels.value]
    modelDiscovery.value = { source: '', warning: '', keyValidated: false }
    apiKey.value = ''
    editingKey.value = false
    stopChatgptPolling()
    resetChatgptLogin()
  }

  function resetChatgptLogin() { chatgptLogin.value = initialChatgptLogin() }

  function stopChatgptPolling() {
    if (chatgptPollTimer) {
      clearInterval(chatgptPollTimer)
      chatgptPollTimer = null
    }
  }

  async function startChatgptLogin(method = 'device_code') {
    stopChatgptPolling()
    chatgptLogin.value = { ...initialChatgptLogin(), status: 'starting', method }
    try {
      const result = await request<any>('/settings/providers/chatgpt/oauth/login', { method: 'POST', body: JSON.stringify({ method }) })
      if (method === 'browser') {
        chatgptLogin.value = { ...initialChatgptLogin(), status: 'browser', method, authUrl: result.authUrl, sessionId: result.sessionId }
        return
      }
      chatgptLogin.value = { ...initialChatgptLogin(), status: 'pending', method, userCode: result.userCode, verificationUri: result.verificationUri, sessionId: result.sessionId }
      chatgptPollTimer = setInterval(pollChatgptLogin, Math.max(2, result.intervalSeconds || 5) * 1000)
    } catch (err) {
      chatgptLogin.value = { ...chatgptLogin.value, status: 'failed', error: err.message }
    }
  }

  async function completeChatgptLogin() {
    const sessionId = chatgptLogin.value.sessionId
    const input = chatgptLogin.value.input.trim()
    if (!sessionId || !input) return
    chatgptLogin.value = { ...chatgptLogin.value, error: '' }
    try {
      const result = await request<any>('/settings/providers/chatgpt/oauth/complete', { method: 'POST', body: JSON.stringify({ sessionId, input }) })
      if (result.state === 'done') {
        resetChatgptLogin()
        chatgptLogin.value = { ...chatgptLogin.value, status: 'done' }
        await load()
      } else chatgptLogin.value = { ...chatgptLogin.value, error: result.error || '授权失败' }
    } catch (err) { chatgptLogin.value = { ...chatgptLogin.value, error: err.message } }
  }

  async function pollChatgptLogin() {
    const sessionId = chatgptLogin.value.sessionId
    if (!sessionId) return
    try {
      const result = await request<any>('/settings/providers/chatgpt/oauth/status', { method: 'POST', body: JSON.stringify({ sessionId }) })
      if (result.state === 'pending') return
      stopChatgptPolling()
      if (result.state === 'done') {
        resetChatgptLogin()
        chatgptLogin.value = { ...chatgptLogin.value, status: 'done' }
        await load()
      } else if (result.state === 'failed') chatgptLogin.value = { ...chatgptLogin.value, status: 'failed', error: result.error || '登录失败' }
    } catch (err) {
      stopChatgptPolling()
      chatgptLogin.value = { ...chatgptLogin.value, status: 'failed', error: err.message }
    }
  }

  async function logoutChatgpt() {
    stopChatgptPolling()
    status.value = await request<any>('/settings/providers/chatgpt/oauth/logout', { method: 'POST', body: JSON.stringify({}) })
    resetChatgptLogin()
  }

  async function fetchModels() {
    if (!apiKey.value.trim() && !status.value.providers?.[selectedProvider.value]) return
    fetchingModels.value = true
    try {
      const body = apiKey.value.trim() ? { apiKey: apiKey.value.trim() } : {}
      const result = await request<any>(`/settings/providers/${selectedProvider.value}/models`, { method: 'POST', body: JSON.stringify(body) })
      availableModels.value = [...new Set([...availableModels.value, ...(result.models || [])])]
      modelDiscovery.value = {
        source: result.source || 'conventional',
        warning: result.warning || '',
        keyValidated: Boolean(result.keyValidated),
      }
    } finally { fetchingModels.value = false }
  }

  function addManualModel(model: string) {
    const value = model.trim()
    if (!value) return false
    if (!availableModels.value.includes(value)) availableModels.value = [...availableModels.value, value]
    if (!selectedModels.value.includes(value)) selectedModels.value = [...selectedModels.value, value]
    selectedDefaultModel.value = `${selectedProvider.value}:${value}`
    modelDiscovery.value = { ...modelDiscovery.value, source: 'manual' }
    return true
  }

  async function saveProvider() {
    if ((!apiKey.value.trim() && !status.value.providers?.[selectedProvider.value]) || !selectedModels.value.length) return
    saving.value = true
    try {
      const defaultModel = selectedDefaultModel.value.startsWith(`${selectedProvider.value}:`)
        ? selectedDefaultModel.value.slice(selectedProvider.value.length + 1) : undefined
      status.value = await request<any>(`/settings/providers/${selectedProvider.value}`, { method: 'PUT', body: JSON.stringify({ ...(apiKey.value.trim() ? { apiKey: apiKey.value.trim() } : {}), models: selectedModels.value, ...(defaultModel ? { defaultModel } : {}) }) })
      apiKey.value = ''
      editingKey.value = false
    } finally { saving.value = false }
  }

  async function saveModelAssignments() {
    if (!selectedDefaultModel.value) throw new Error('请先选择全局默认模型')
    savingModelAssignments.value = true
    try {
      const routes = Object.fromEntries(Object.entries(taskRoutes.value).filter(([, model]) => model))
      await request<any>('/settings/model-routes', { method: 'PUT', body: JSON.stringify({ routes }) })
      status.value = await request<any>('/settings/model', { method: 'PUT', body: JSON.stringify({ model: selectedDefaultModel.value }) })
      taskRoutes.value = { ...(status.value.taskRoutes || {}) }
    } finally { savingModelAssignments.value = false }
  }

  return { status, selectedProvider, apiKey, availableModels, selectedModels, modelDiscovery, selectedDefaultModel, taskRoutes, showAdvancedRoutes, saving, fetchingModels, editingKey, savingModelAssignments, chatgptLogin, load, open, changeProvider, resetChatgptLogin, stopChatgptPolling, startChatgptLogin, completeChatgptLogin, pollChatgptLogin, logoutChatgpt, fetchModels, addManualModel, saveProvider, saveModelAssignments }
})
