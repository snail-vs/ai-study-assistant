import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CourseBriefReview from './CourseBriefReview.vue'

const session = { sessionId: 's', state: 'reviewing_brief' as const, revision: 3, briefRevision: 2, brief: { topic: 'Kubernetes', learningOutcome: '掌握原理', priorKnowledge: '有基础', learningGoals: ['理解原理'], priorKnowledgeLevels: ['有基础'] }, currentQuestion: null, recommendedScale: 'standard' as const, selectedScale: null, outline: [], outlineConfirmed: false, allowedActions: ['select_scale'], operation: {}, outlineRevisionMessages: [] }
const scales = [{ id: 'quick' as const, label: '快速了解', hint: '15 分钟', detail: '核心概念' }, { id: 'standard' as const, label: '标准课程', hint: '2 小时', detail: '完整路径' }, { id: 'series' as const, label: '系列课程', hint: '数周', detail: '分阶段' }]

describe('CourseBriefReview', () => {
  it('shows recommendation without selecting it and separates scale from generation', async () => {
    const wrapper = mount(CourseBriefReview, { props: { session, brief: session.brief, scales } })
    expect(wrapper.find('.course-scale-card.selected').exists()).toBe(false)
    expect(wrapper.text()).toContain('AI 推荐：标准课程')
    await wrapper.findAll('.course-scale-card')[1].trigger('click')
    expect(wrapper.emitted('scale')).toEqual([['standard']])
    expect(wrapper.emitted('generate')).toBeUndefined()
  })

  it('shows loading state in the generate button while producing the outline', () => {
    const wrapper = mount(CourseBriefReview, {
      props: {
        session: { ...session, selectedScale: 'standard' },
        brief: session.brief,
        scales,
        busy: true,
        activeCommand: 'generate_outline',
      },
    })

    const generateButton = wrapper.find('.course-design-actions .primary')
    expect(generateButton.attributes('aria-busy')).toBe('true')
    expect(generateButton.find('.status-spinner').exists()).toBe(true)
    expect(generateButton.text()).toContain('正在生成课程大纲…')
  })

  it('disables restart, back, scale, and generate controls while busy', () => {
    const wrapper = mount(CourseBriefReview, {
      props: {
        session: { ...session, selectedScale: 'standard' },
        brief: session.brief,
        scales,
        busy: true,
        activeCommand: 'generate_outline',
      },
    })

    expect(wrapper.find('.course-design-head button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.course-design-actions .secondary').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.course-design-actions .primary').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.course-scale-card').every((card) => card.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('textarea').every((area) => area.attributes('disabled') !== undefined)).toBe(true)
  })
})
