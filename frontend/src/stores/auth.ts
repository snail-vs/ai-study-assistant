import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const checked = ref(false)
  const user = ref(null)
  const mode = ref('login')
  const username = ref('')
  const password = ref('')
  const inviteCode = ref('')
  const loading = ref(false)

  async function check() {
    try {
      user.value = await request('/auth/me')
    } catch (_) {
      user.value = null
    } finally {
      checked.value = true
    }
    return user.value
  }

  async function submit() {
    loading.value = true
    try {
      const path = mode.value === 'login' ? '/auth/login' : '/auth/register'
      const body = mode.value === 'login'
        ? { username: username.value, password: password.value }
        : { username: username.value, password: password.value, inviteCode: inviteCode.value }
      user.value = await request(path, { method: 'POST', body: JSON.stringify(body) })
      password.value = ''
      inviteCode.value = ''
      return user.value
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    await request('/auth/logout', { method: 'POST' }).catch(() => {})
    user.value = null
  }

  return { checked, user, mode, username, password, inviteCode, loading, check, submit, logout }
})
