import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CourseOutlineReview from './CourseOutlineReview.vue'

const session = { sessionId: 's', state: 'reviewing_outline' as const, revision: 5, briefRevision: 2, brief: { topic: 'Git' }, currentQuestion: null, recommendedScale: 'quick' as const, selectedScale: 'quick' as const, outline: [{ title: '基础', objective: '理解' }], outlineConfirmed: false, allowedActions: ['revise_outline', 'confirm_outline'], operation: {}, outlineRevisionMessages: [] }

describe('CourseOutlineReview', () => {
  it('requires explicit outline confirmation before showing course generation', async () => {
    const wrapper = mount(CourseOutlineReview, { props: { session } })
    expect(wrapper.text()).not.toContain('确认并生成课程')
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.setProps({ session: { ...session, state: 'outline_confirmed', outlineConfirmed: true } })
    expect(wrapper.text()).toContain('确认并生成课程')
  })
})
