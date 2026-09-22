<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  providerStatus: { type: Object, required: true },
  selectedProvider: { type: String, required: true },
  apiKey: { type: String, default: '' },
  availableModels: { type: Array, default: () => [] },
  selectedModels: { type: Array, default: () => [] },
  modelDiscovery: { type: Object, default: () => ({}) },
  selectedDefaultModel: { type: String, default: '' },
  taskRoutes: { type: Object, default: () => ({}) },
  showAdvancedRoutes: Boolean,
  savingSettings: Boolean,
  fetchingModels: Boolean,
  editingKey: Boolean,
  savingModelAssignments: Boolean,
  chatgptLogin: { type: Object, required: true },
  allModelOptions: { type: Array, default: () => [] },
  keyConfigured: Boolean,
  taskDefinitions: { type: Array, default: () => [] },
  modelRoleDefinitions: { type: Array, default: () => [] },
  roleRouteValue: { type: Function, required: true },
  usageSummary: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'close', 'change-provider', 'fetch-models', 'save-provider', 'save-model-assignments',
  'start-chatgpt-login', 'complete-chatgpt-login', 'logout-chatgpt',
  'update:selectedProvider', 'update:apiKey', 'update:selectedModels',
  'update:selectedDefaultModel', 'update:taskRoutes', 'update:showAdvancedRoutes', 'update:chatgptLogin',
  'update:editingKey',
  'add-manual-model',
])

const isChatGpt = computed(() => props.selectedProvider === 'chatgpt')
const manualModel = ref('')
const activeAiTab = ref('providers')

const providerOptions = [
  { id: 'deepseek', label: 'DeepSeek' },
  { id: 'google', label: 'Google Gemini' },
  { id: 'opencode', label: 'OpenCode Zen' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'glm', label: '智谱 GLM（中国大陆）' },
  { id: 'zai', label: 'Z.AI GLM（海外）' },
  { id: 'chatgpt', label: 'ChatGPT (Plus/Pro)' },
]
const aiTabs = [
  { id: 'providers', label: '模型服务' },
  { id: 'default', label: '默认模型' },
  { id: 'roles', label: '模型分工' },
  { id: 'advanced', label: '高级路由' },
  { id: 'usage', label: '用量摘要' },
]
const selectedProviderLabel = computed(() => (
  providerOptions.find((provider) => provider.id === props.selectedProvider)?.label
  || props.selectedProvider
))
const configuredProviders = computed(() => (
  providerOptions.filter((provider) => props.providerStatus.providers?.[provider.id])
))

function addManualModel() {
  const value = manualModel.value.trim()
  if (!value) return
  emit('add-manual-model', value)
  manualModel.value = ''
}

function updateTaskRoute(id, value) {
  const next = { ...props.taskRoutes }
  if (value) next[id] = value
  else delete next[id]
  emit('update:taskRoutes', next)
}

function setRoleRoute(role, model) {
  if (model === '__custom__') return
  const next = { ...props.taskRoutes }
  for (const task of role.tasks) {
    if (model) next[task] = model
    else delete next[task]
  }
  emit('update:taskRoutes', next)
}

function selectAiTab(tab) {
  activeAiTab.value = tab
  emit('update:showAdvancedRoutes', tab === 'advanced')
}
</script>

<template>
  <div
    class="modal-backdrop"
    @click.self="emit('close')"
  >
    <section class="settings-modal settings-center">
      <aside class="settings-sidebar">
        <div class="settings-brand">
          <span>SETTINGS</span>
          <strong>设置中心</strong>
        </div>
        <nav aria-label="设置分类">
          <div class="settings-nav-group">
            智能服务
          </div>
          <button
            class="settings-nav-item active"
            type="button"
          >
            <span class="settings-nav-icon">AI</span>
            <span><strong>AI 与模型</strong><small>服务、模型与任务路由</small></span>
          </button>
        </nav>
        <div class="settings-sidebar-footer">
          <span>已配置 {{ configuredProviders.length }} 个模型服务</span>
          <small>更多设置项将在这里集中管理</small>
        </div>
      </aside>

      <div class="settings-main">
        <header class="settings-main-head">
          <div>
            <div class="panel-title">
              AI 与模型
            </div>
            <p>管理模型服务、默认模型和学习任务分工。</p>
          </div>
          <button
            class="settings-close"
            type="button"
            aria-label="关闭设置"
            @click="emit('close')"
          >
            ×
          </button>
        </header>

        <nav
          class="settings-tabs"
          aria-label="AI 设置"
        >
          <button
            v-for="tab in aiTabs"
            :key="tab.id"
            type="button"
            :class="{ active: activeAiTab === tab.id }"
            @click="selectAiTab(tab.id)"
          >
            {{ tab.label }}
          </button>
        </nav>

        <div class="settings-content">
          <section
            v-if="activeAiTab === 'providers'"
            class="settings-pane provider-pane"
          >
            <div class="settings-section-head">
              <div><span>模型服务</span><h2>{{ selectedProviderLabel }}</h2><p>配置访问凭据并选择这个服务可使用的模型。</p></div>
              <span
                class="provider-state"
                :class="{ configured: keyConfigured }"
              ><i />{{ keyConfigured ? '已配置' : '未配置' }}</span>
            </div>

            <div class="settings-field provider-picker">
              <label for="settings-provider">Provider</label>
              <select
                id="settings-provider"
                :value="selectedProvider"
                @change="emit('update:selectedProvider', $event.target.value); emit('change-provider')"
              >
                <option
                  v-for="provider in providerOptions"
                  :key="provider.id"
                  :value="provider.id"
                >
                  {{ provider.label }}
                </option>
              </select>
            </div>

            <div
              v-if="isChatGpt"
              class="chatgpt-login"
            >
              <div class="catalog-title">
                ChatGPT Plus/Pro 订阅登录（无需 API Key）
              </div>
              <div
                v-if="providerStatus.providers?.chatgpt"
                class="chatgpt-status"
              >
                <span class="chatgpt-dot ok" /><span>已登录</span>
                <button
                  class="model-fetch-button"
                  :disabled="fetchingModels"
                  @click="emit('fetch-models')"
                >
                  {{ fetchingModels ? '获取中…' : '刷新模型' }}
                </button>
                <button
                  class="secondary"
                  @click="emit('logout-chatgpt')"
                >
                  退出登录
                </button>
              </div>
              <div
                v-else-if="chatgptLogin.status === 'pending'"
                class="chatgpt-pending"
              >
                <p>
                  在浏览器打开 <a
                    :href="chatgptLogin.verificationUri"
                    target="_blank"
                    rel="noopener"
                  >{{ chatgptLogin.verificationUri }}</a> 并输入设备码：
                </p>
                <div class="device-code">
                  {{ chatgptLogin.userCode }}
                </div>
                <p class="provider-hint">
                  等待授权中…
                </p>
              </div>
              <div
                v-else-if="chatgptLogin.status === 'browser'"
                class="chatgpt-pending"
              >
                <p>
                  1. 打开 <a
                    :href="chatgptLogin.authUrl"
                    target="_blank"
                    rel="noopener"
                  >授权链接</a> 完成登录。
                </p>
                <p>2. 页面跳转到 <code>localhost:1455</code> 后，复制完整 URL 粘贴到下面。</p>
                <input
                  :value="chatgptLogin.input"
                  placeholder="http://localhost:1455/auth/callback?code=...&state=..."
                  @input="emit('update:chatgptLogin', { ...chatgptLogin, input: $event.target.value })"
                >
                <button
                  class="primary"
                  :disabled="!chatgptLogin.input.trim()"
                  @click="emit('complete-chatgpt-login')"
                >
                  完成授权
                </button>
                <p
                  v-if="chatgptLogin.error"
                  class="error"
                >
                  {{ chatgptLogin.error }}
                </p>
              </div>
              <div v-else>
                <div class="provider-actions">
                  <button
                    class="secondary"
                    :disabled="chatgptLogin.status === 'starting'"
                    @click="emit('start-chatgpt-login', 'browser')"
                  >
                    浏览器授权
                  </button>
                  <button
                    class="primary"
                    :disabled="chatgptLogin.status === 'starting'"
                    @click="emit('start-chatgpt-login', 'device_code')"
                  >
                    设备码登录
                  </button>
                </div>
                <p
                  v-if="chatgptLogin.error"
                  class="error"
                >
                  {{ chatgptLogin.error }}
                </p>
              </div>
            </div>

            <template v-else>
              <div class="settings-field">
                <label>API Key</label>
                <div class="key-row">
                  <input
                    v-if="editingKey || !keyConfigured"
                    :value="apiKey"
                    type="password"
                    placeholder="输入 API Key"
                    autocomplete="off"
                    @input="emit('update:apiKey', $event.target.value)"
                  >
                  <div
                    v-else
                    class="masked-key"
                  >
                    ••••••••••••••••••••
                  </div>
                  <button
                    v-if="keyConfigured && !editingKey"
                    class="settings-secondary-button"
                    @click="emit('update:editingKey', true)"
                  >
                    更换
                  </button>
                  <button
                    class="settings-primary-button"
                    :disabled="fetchingModels || (!apiKey && !keyConfigured)"
                    @click="emit('fetch-models')"
                  >
                    {{ fetchingModels ? '获取中…' : '刷新模型' }}
                  </button>
                </div>
                <p>Key 只会加密保存在后端，前端不会保存明文。</p>
              </div>
              <p
                v-if="modelDiscovery.warning"
                class="settings-notice"
              >
                {{ modelDiscovery.warning }}
              </p>
              <details
                class="manual-model-entry"
                :open="modelDiscovery.source === 'manual'"
              >
                <summary>手动添加模型</summary>
                <div class="key-row">
                  <input
                    v-model="manualModel"
                    placeholder="例如 glm-5.2"
                    @keydown.enter.prevent="addManualModel"
                  >
                  <button
                    class="settings-primary-button"
                    :disabled="!manualModel.trim()"
                    @click="addManualModel"
                  >
                    添加
                  </button>
                </div>
                <p>手动指定的模型优先；远程目录只用于补充候选项。</p>
              </details>
            </template>

            <div class="model-catalog service-model-list">
              <div class="catalog-title">
                可用模型 <span>{{ availableModels.length }} 个候选项</span>
              </div>
              <div
                v-if="!availableModels.length"
                class="settings-empty"
              >
                刷新模型或手动添加模型后，可在这里选择。
              </div>
              <label
                v-for="model in availableModels"
                :key="model"
                class="model-check"
              >
                <input
                  :checked="selectedModels.includes(model)"
                  type="checkbox"
                  :value="model"
                  @change="emit('update:selectedModels', $event.target.checked ? [...selectedModels, model] : selectedModels.filter((item) => item !== model))"
                >
                <span>{{ model }}</span>
              </label>
            </div>
            <div class="settings-pane-actions">
              <button
                class="settings-primary-button"
                :disabled="savingSettings || ((!apiKey && !keyConfigured && !isChatGpt) || !selectedModels.length)"
                @click="emit('save-provider')"
              >
                {{ savingSettings ? '保存中…' : '保存服务配置' }}
              </button>
            </div>
          </section>

          <section
            v-else-if="activeAiTab === 'default'"
            class="settings-pane"
          >
            <div class="settings-section-head">
              <div><span>默认模型</span><h2>全局默认模型</h2><p>没有单独指定模型的任务将使用此模型。</p></div>
            </div>
            <div
              v-if="allModelOptions.length"
              class="settings-choice-card"
            >
              <label for="settings-default-model">默认使用</label>
              <select
                id="settings-default-model"
                :value="selectedDefaultModel"
                @change="emit('update:selectedDefaultModel', $event.target.value)"
              >
                <option value="">
                  请选择默认模型
                </option>
                <option
                  v-for="option in allModelOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
              <p>任务没有单独覆盖时，会自动跟随这里的选择。</p>
            </div>
            <div
              v-else
              class="settings-empty large"
            >
              请先在“模型服务”中配置至少一个模型。
            </div>
            <div class="settings-pane-actions">
              <button
                class="settings-primary-button"
                :disabled="savingModelAssignments || !selectedDefaultModel"
                @click="emit('save-model-assignments')"
              >
                {{ savingModelAssignments ? '保存中…' : '保存默认模型' }}
              </button>
            </div>
          </section>

          <section
            v-else-if="activeAiTab === 'roles'"
            class="settings-pane"
          >
            <div class="settings-section-head">
              <div><span>模型分工</span><h2>按学习流程选择模型</h2><p>不设置的工作类型将跟随全局默认模型。</p></div>
            </div>
            <div
              v-if="allModelOptions.length"
              class="model-role-routes role-table"
            >
              <label
                v-for="role in modelRoleDefinitions"
                :key="role.id"
                class="model-role-route"
              >
                <span><strong>{{ role.label }}</strong><small>{{ role.hint }}</small></span>
                <select
                  :value="roleRouteValue(role)"
                  @change="setRoleRoute(role, $event.target.value)"
                >
                  <option value="">跟随默认模型</option>
                  <option
                    v-if="roleRouteValue(role) === '__custom__'"
                    value="__custom__"
                    disabled
                  >已在高级路由中分别配置</option>
                  <option
                    v-for="option in allModelOptions"
                    :key="option.value"
                    :value="option.value"
                  >{{ option.label }}</option>
                </select>
              </label>
            </div>
            <div
              v-else
              class="settings-empty large"
            >
              请先配置模型，再设置模型分工。
            </div>
            <div class="settings-pane-actions">
              <button
                class="settings-primary-button"
                :disabled="savingModelAssignments || !selectedDefaultModel"
                @click="emit('save-model-assignments')"
              >
                {{ savingModelAssignments ? '保存中…' : '保存模型分工' }}
              </button>
            </div>
          </section>

          <section v-else-if="activeAiTab === 'usage'" class="settings-pane">
            <div class="settings-section-head"><div><span>任务级用量</span><h2>调用与 token 摘要</h2><p>仅记录任务、模型、结果、耗时和 token；不会保存提示词或生成内容。</p></div></div>
            <div v-if="usageSummary.length" class="advanced-route-grid">
              <div v-for="row in usageSummary" :key="`${row.task}-${row.provider}-${row.model}`" class="settings-choice-card">
                <strong>{{ row.task }}</strong><small>{{ row.provider }} · {{ row.model || '默认模型' }}</small>
                <p>{{ row.calls }} 次调用 · 成功 {{ row.successes }} · 失败 {{ row.failures }} · {{ row.totalTokens ?? '—' }} tokens · {{ row.averageDurationMs }} ms</p>
              </div>
            </div>
            <div v-else class="settings-empty large">暂无调用记录。完成一次 AI 任务后会显示汇总。</div>
          </section>

          <section
            v-else
            class="settings-pane"
          >
            <div class="settings-section-head">
              <div><span>高级路由</span><h2>单项任务覆盖</h2><p>任务级设置会覆盖模型分工和全局默认模型。</p></div>
            </div>
            <div
              v-if="allModelOptions.length"
              class="task-routes advanced-route-grid"
            >
              <label
                v-for="task in taskDefinitions"
                :key="task.id"
                class="task-route"
              >
                <span>{{ task.label }}</span>
                <select
                  :value="taskRoutes[task.id] || ''"
                  @change="updateTaskRoute(task.id, $event.target.value)"
                >
                  <option value="">跟随上级设置</option>
                  <option
                    v-for="option in allModelOptions"
                    :key="option.value"
                    :value="option.value"
                  >{{ option.label }}</option>
                </select>
              </label>
            </div>
            <div
              v-else
              class="settings-empty large"
            >
              请先配置模型，再设置高级任务路由。
            </div>
            <div class="settings-pane-actions">
              <button
                class="settings-primary-button"
                :disabled="savingModelAssignments || !selectedDefaultModel"
                @click="emit('save-model-assignments')"
              >
                {{ savingModelAssignments ? '保存中…' : '保存高级路由' }}
              </button>
            </div>
          </section>
        </div>
      </div>
    </section>
  </div>
</template>
