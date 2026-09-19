<script setup>
import { computed } from 'vue'

const props = defineProps({
  providerStatus: { type: Object, required: true },
  selectedProvider: { type: String, required: true },
  apiKey: { type: String, default: '' },
  availableModels: { type: Array, default: () => [] },
  selectedModels: { type: Array, default: () => [] },
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
})

const emit = defineEmits([
  'close', 'change-provider', 'fetch-models', 'save-provider', 'save-model-assignments',
  'start-chatgpt-login', 'complete-chatgpt-login', 'logout-chatgpt',
  'update:selectedProvider', 'update:apiKey', 'update:selectedModels',
  'update:selectedDefaultModel', 'update:taskRoutes', 'update:showAdvancedRoutes', 'update:chatgptLogin',
  'update:editingKey',
])

const isChatGpt = computed(() => props.selectedProvider === 'chatgpt')

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
</script>

<template>
  <div
    class="modal-backdrop"
    @click.self="emit('close')"
  >
    <section class="settings-modal">
      <div class="settings-head">
        <div>
          <div class="panel-title">
            模型设置
          </div><p>Key 会在后端加密保存，前端不会保存明文。</p>
        </div><button @click="emit('close')">
          ×
        </button>
      </div>
      <label>Provider<select
        :value="selectedProvider"
        @change="emit('update:selectedProvider', $event.target.value); emit('change-provider')"
      ><option value="deepseek">DeepSeek</option><option value="google">Google Gemini</option><option value="opencode">OpenCode Zen</option><option value="openrouter">OpenRouter</option><option value="anthropic">Anthropic</option><option value="chatgpt">ChatGPT (Plus/Pro)</option></select></label>
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
            {{ fetchingModels ? '获取中…' : '获取模型' }}
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
          </p><div class="device-code">
            {{ chatgptLogin.userCode }}
          </div><p class="provider-hint">
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
          </p><p>2. 页面会跳转到 <code>localhost:1455</code>（可能显示无法访问），复制地址栏里的完整 URL 粘到下面：</p><input
            :value="chatgptLogin.input"
            placeholder="http://localhost:1455/auth/callback?code=...&state=..."
            @input="emit('update:chatgptLogin', { ...chatgptLogin, input: $event.target.value })"
          ><button
            class="primary"
            :disabled="!chatgptLogin.input.trim()"
            @click="emit('complete-chatgpt-login')"
          >
            完成授权
          </button><p
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
            </button><button
              class="primary"
              :disabled="chatgptLogin.status === 'starting'"
              @click="emit('start-chatgpt-login', 'device_code')"
            >
              设备码登录
            </button>
          </div><p
            v-if="chatgptLogin.error"
            class="error"
          >
            {{ chatgptLogin.error }}
          </p>
        </div>
      </div>
      <label v-if="!isChatGpt">API Key<div class="key-row"><input
        v-if="editingKey || !keyConfigured"
        :value="apiKey"
        type="password"
        placeholder="输入 API Key"
        autocomplete="off"
        @input="emit('update:apiKey', $event.target.value)"
      ><div
        v-else
        class="masked-key"
      >*****</div><button
        v-if="keyConfigured && !editingKey"
        class="edit-key"
        @click="emit('update:editingKey', true)"
      >编辑</button><button
        :disabled="fetchingModels || (!apiKey && !keyConfigured)"
        @click="emit('fetch-models')"
      >{{ fetchingModels ? '获取中…' : '获取模型' }}</button></div></label>
      <div
        v-if="availableModels.length"
        class="model-catalog"
      >
        <div class="catalog-title">
          选择此 Provider 可使用的模型
        </div><label
          v-for="model in availableModels"
          :key="model"
          class="model-check"
        ><input
          :checked="selectedModels.includes(model)"
          type="checkbox"
          :value="model"
          @change="emit('update:selectedModels', $event.target.checked ? [...selectedModels, model] : selectedModels.filter((item) => item !== model))"
        ><span>{{ model }}</span></label>
      </div>
      <div class="provider-actions">
        <button
          class="primary"
          :disabled="savingSettings || ((!apiKey && !keyConfigured) || !selectedModels.length)"
          @click="emit('save-provider')"
        >
          {{ savingSettings ? '保存中…' : '保存 Provider' }}
        </button>
      </div>
      <section
        v-if="allModelOptions.length"
        class="model-assignments"
      >
        <div class="default-model-setting">
          <div class="catalog-title">
            全局默认模型
          </div><p>未单独指定的任务将使用此模型。</p><select
            :value="selectedDefaultModel"
            @change="emit('update:selectedDefaultModel', $event.target.value)"
          >
            <option value="">
              请选择默认模型
            </option><option
              v-for="option in allModelOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </div>
        <div class="model-role-routes">
          <div class="catalog-title">
            模型分工
          </div><p class="model-routing-hint">
            按学习流程选择模型；不设置则跟随全局默认模型。
          </p><label
            v-for="role in modelRoleDefinitions"
            :key="role.id"
            class="model-role-route"
          ><span><strong>{{ role.label }}</strong><small>{{ role.hint }}</small></span><select
            :value="roleRouteValue(role)"
            @change="setRoleRoute(role, $event.target.value)"
          ><option value="">跟随默认模型</option><option
            v-if="roleRouteValue(role) === '__custom__'"
            value="__custom__"
            disabled
          >已在高级设置中分别配置</option><option
            v-for="option in allModelOptions"
            :key="option.value"
            :value="option.value"
          >{{ option.label }}</option></select></label><button
            class="advanced-routes-toggle"
            @click="emit('update:showAdvancedRoutes', !showAdvancedRoutes)"
          >
            {{ showAdvancedRoutes ? '收起高级任务路由' : '高级任务路由' }} <span>{{ showAdvancedRoutes ? '⌃' : '⌄' }}</span>
          </button><div
            v-if="showAdvancedRoutes"
            class="task-routes"
          >
            <div class="catalog-title">
              单项覆盖
            </div><p class="model-routing-hint">
              只在确有需要时修改；单项设置会覆盖所属模型分工。
            </p><label
              v-for="task in taskDefinitions"
              :key="task.id"
              class="task-route"
            ><span>{{ task.label }}</span><select
              :value="taskRoutes[task.id] || ''"
              @change="updateTaskRoute(task.id, $event.target.value)"
            ><option value="">跟随默认模型</option><option
              v-for="option in allModelOptions"
              :key="option.value"
              :value="option.value"
            >{{ option.label }}</option></select></label>
          </div><div class="model-assignment-actions">
            <button
              class="primary"
              :disabled="savingModelAssignments"
              @click="emit('save-model-assignments')"
            >
              {{ savingModelAssignments ? '保存中…' : '保存模型分工' }}
            </button>
          </div>
        </div>
      </section>
      <div class="provider-hint">
        已配置：{{ Object.entries(providerStatus.providers || {}).filter(([, value]) => value).map(([key]) => key).join('、') || '暂无' }}
      </div>
    </section>
  </div>
</template>
