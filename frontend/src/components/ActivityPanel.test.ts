// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ActivityPanel from './ActivityPanel.vue'

const activity = {
  id: 'quiz-1',
  title: '理解检查',
  objective: '检查本节掌握情况',
  questions: [{ id: 'q-1', type: 'short_answer', prompt: '什么是测试？' }],
}

const result = {
  id: 'attempt-1',
  score: 90,
  masteryLevel: 'mastered',
  diagnosticSummary: '掌握良好',
  results: [{ questionId: 'q-1', correct: true, feedback: '回答正确' }],
  followUp: { status: 'pending', prompt: '请补充一个例子' },
}

const masteryLabel = (level: string) => level === 'mastered' ? '已掌握' : level

describe('ActivityPanel', () => {
  it('forwards answer and submit events from the active quiz', async () => {
    const wrapper = mount(ActivityPanel, {
      props: {
        activeActivity: activity,
        activityAnswers: { 'q-1': '' },
        masteryLabel,
      },
    })

    await wrapper.find('textarea').setValue('测试是对行为的自动验证')
    await wrapper.find('.quiz-submit').trigger('click')

    expect(wrapper.emitted('update:answer')).toEqual([[{ id: 'q-1', value: '测试是对行为的自动验证' }]])
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('shows submitting state and forwards follow-up events after a result', async () => {
    const wrapper = mount(ActivityPanel, {
      props: {
        activeActivity: activity,
        activityResult: result,
        followUpAnswer: '我会用单元测试验证函数输出',
        followUpSubmitting: true,
        masteryLabel,
      },
    })

    expect(wrapper.text()).toContain('已掌握')
    expect(wrapper.text()).toContain('正在分析…')
    expect(wrapper.find('.quiz-follow-up-meta button').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ followUpSubmitting: false })
    await wrapper.find('.quiz-follow-up-input').setValue('我会用集成测试验证模块协作')
    await wrapper.find('.quiz-follow-up-meta button').trigger('click')

    expect(wrapper.emitted('update:followUpAnswer')).toEqual([['我会用集成测试验证模块协作']])
    expect(wrapper.emitted('submit-follow-up')).toHaveLength(1)
  })
})
