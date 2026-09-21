// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SettingsDialog from './SettingsDialog.vue'

const baseProps = {
  providerStatus: {
    providers: { deepseek: true, chatgpt: true },
    models: { deepseek: ['deepseek-chat'], chatgpt: ['gpt-5'] },
  },
  selectedProvider: 'deepseek',
  apiKey: '',
  availableModels: ['deepseek-chat'],
  selectedModels: ['deepseek-chat'],
  modelDiscovery: {},
  selectedDefaultModel: 'deepseek:deepseek-chat',
  taskRoutes: {},
  showAdvancedRoutes: false,
  savingSettings: false,
  fetchingModels: false,
  editingKey: false,
  savingModelAssignments: false,
  chatgptLogin: { status: 'idle', input: '' },
  allModelOptions: [{ value: 'deepseek:deepseek-chat', label: 'deepseek · deepseek-chat' }],
  keyConfigured: true,
  taskDefinitions: [{ id: 'course_plan', label: '课程规划' }],
  modelRoleDefinitions: [{ id: 'course', label: '课程生成', hint: '课程规划', tasks: ['course_plan'] }],
  roleRouteValue: () => '',
}

describe('SettingsDialog', () => {
  it('renders an application settings shell and separates AI settings into tabs', async () => {
    const wrapper = mount(SettingsDialog, { props: baseProps })

    expect(wrapper.find('.settings-sidebar').text()).toContain('设置中心')
    expect(wrapper.find('.settings-nav-item').text()).toContain('AI 与模型')
    expect(wrapper.find('.provider-pane').text()).toContain('DeepSeek')

    await wrapper.findAll('.settings-tabs button')[1].trigger('click')
    expect(wrapper.find('.settings-pane').text()).toContain('全局默认模型')
    expect(wrapper.find('.provider-pane').exists()).toBe(false)

    await wrapper.findAll('.settings-tabs button')[2].trigger('click')
    expect(wrapper.find('.role-table').text()).toContain('课程生成')

    await wrapper.findAll('.settings-tabs button')[3].trigger('click')
    expect(wrapper.find('.advanced-route-grid').text()).toContain('课程规划')
    const advancedEvents = wrapper.emitted('update:showAdvancedRoutes') || []
    expect(advancedEvents[advancedEvents.length - 1]).toEqual([true])
  })

  it('keeps manual model entry and provider saving in the model-service tab', async () => {
    const wrapper = mount(SettingsDialog, { props: baseProps })
    await wrapper.find('.manual-model-entry input').setValue('deepseek-custom')
    await wrapper.find('.manual-model-entry button').trigger('click')
    await wrapper.find('.settings-pane-actions .primary').trigger('click')

    expect(wrapper.emitted('add-manual-model')).toEqual([['deepseek-custom']])
    expect(wrapper.emitted('save-provider')).toHaveLength(1)
    expect(wrapper.emitted('save-model-assignments')).toBeUndefined()
  })
})
