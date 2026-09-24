import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MultiSelectQuestion from './MultiSelectQuestion.vue'

const question = {
  id: 'goal-1', stage: 'collecting_goals' as const, target: 'learningGoals' as const,
  type: 'multi_select_with_text' as const, title: '你希望获得哪些能力？', description: '可以多选', allowCustom: true,
  minimumSelections: 0, options: [{ id: 'a', label: '理解原理' }, { id: 'b', label: '完成实践' }],
}

describe('MultiSelectQuestion', () => {
  it('keeps chip selection local until Next is clicked', async () => {
    const wrapper = mount(MultiSelectQuestion, { props: { question } })
    await wrapper.get('button.course-option-chip').trigger('click')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('submit')).toEqual([[['a'], '']])
  })

  it('submits multiple options and custom text together', async () => {
    const wrapper = mount(MultiSelectQuestion, { props: { question } })
    await wrapper.findAll('button.course-option-chip')[0].trigger('click')
    await wrapper.findAll('button.course-option-chip')[1].trigger('click')
    await wrapper.get('textarea').setValue('希望独立开发 Operator')
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('submit')?.[0]).toEqual([['a', 'b'], '希望独立开发 Operator'])
  })

  it('restores local draft when the question changes', async () => {
    const wrapper = mount(MultiSelectQuestion, { props: { question, selected: ['a'], customText: '目标补充' } })
    expect(wrapper.get('button.course-option-chip').classes()).toContain('selected')
    await wrapper.setProps({ question: { ...question, id: 'background-1', stage: 'collecting_background', target: 'priorKnowledgeLevels', title: '你有哪些基础？' }, selected: ['b'], customText: '基础补充' })
    expect(wrapper.findAll('button.course-option-chip')[0].classes()).not.toContain('selected')
    expect(wrapper.findAll('button.course-option-chip')[1].classes()).toContain('selected')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('基础补充')
  })

  it('uses the server stage for the step number', async () => {
    const wrapper = mount(MultiSelectQuestion, { props: { question, stage: 'collecting_background' } })
    expect(wrapper.text()).toContain('2 / 3')
  })

  it('disables back, complete, next, chips, and textarea while busy', () => {
    const wrapper = mount(MultiSelectQuestion, {
      props: { question, busy: true, activeCommand: 'complete_with_ai', selected: ['a'], customText: '目标' },
    })

    const actions = wrapper.findAll('.course-design-actions button')
    expect(actions).toHaveLength(3)
    expect(actions.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('.course-option-chip').every((chip) => chip.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
  })
})
