import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CourseOutlineReview from './CourseOutlineReview.vue'

const session = { sessionId: 's', state: 'reviewing_outline' as const, revision: 5, briefRevision: 2, brief: { topic: 'Git' }, currentQuestion: null, recommendedScale: 'quick' as const, selectedScale: 'quick' as const, outline: [{ title: '基础', objective: '理解' }], outlineConfirmed: false, allowedActions: ['revise_outline', 'confirm_outline'], operation: {}, outlineRevisionMessages: [] }

describe('CourseOutlineReview', () => {
  it('keeps the outline readable and shows revise progress beside the feedback controls', async () => {
    const wrapper = mount(CourseOutlineReview, { props: { session, busy: false, activeCommand: null } })
    const input = wrapper.get('input')
    await input.setValue('增加一个实战项目')
    await wrapper.setProps({ busy: true, activeCommand: 'revise_outline' })

    expect(wrapper.get('.course-outline-list').text()).toContain('基础')
    expect(wrapper.find('.course-outline-loading').exists()).toBe(false)
    const progress = wrapper.get('.course-outline-conversation > .course-operation-status')
    expect(progress.text()).toContain('正在根据你的建议修改大纲…')
    expect(progress.element.previousElementSibling?.tagName).toBe('FORM')
    expect(wrapper.get('form button').text()).toContain('正在修改…')
    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('form button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('form').attributes('aria-busy')).toBe('true')
  })

  it('requires explicit outline confirmation before showing course generation', async () => {
    const wrapper = mount(CourseOutlineReview, { props: { session } })
    expect(wrapper.text()).not.toContain('确认并生成课程')
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.setProps({ session: { ...session, state: 'outline_confirmed', outlineConfirmed: true } })
    expect(wrapper.text()).toContain('确认并生成课程')
  })
})
