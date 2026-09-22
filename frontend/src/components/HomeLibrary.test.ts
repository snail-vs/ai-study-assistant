import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import HomeLibrary from './HomeLibrary.vue'

describe('HomeLibrary', () => {
  beforeEach(() => localStorage.clear())

  const history = [
    { id: 'space-1', title: 'Kubernetes', createdAt: '2026-09-21T00:00:00Z', generationStatus: 'completed', rootCardId: 'card-1' },
    { id: 'space-2', title: '失败课程', createdAt: '2026-09-21T00:00:00Z', generationStatus: 'failed', generationError: 'provider unavailable', rootCardId: null },
  ]

  it('switches between card and space views and persists the choice', async () => {
    const wrapper = mount(HomeLibrary, {
      props: { history, historyCards: { 'space-1': [{ id: 'card-1', title: '主卡', cardType: 'root' }], 'space-2': [] } },
    })

    expect(wrapper.text()).toContain('我的知识卡')
    expect(wrapper.text()).toContain('主卡')
    await wrapper.findAll('[role="tab"]')[1].trigger('click')

    expect(wrapper.text()).toContain('我的学习空间')
    expect(wrapper.text()).toContain('Kubernetes')
    expect(wrapper.text()).toContain('1 张知识卡')
    expect(localStorage.getItem('studycenter.homeViewMode')).toBe('spaces')
  })

  it('emits space navigation and failed-course actions', async () => {
    const wrapper = mount(HomeLibrary, {
      props: { history, historyCards: { 'space-1': [{ id: 'card-1', title: '主卡', cardType: 'root' }], 'space-2': [] } },
    })
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await wrapper.find('.space-history-item .history-open').trigger('click')
    await wrapper.find('.retry-generation').trigger('click')
    await wrapper.find('.space-history-item .history-delete:not(.retry-generation)').trigger('click')

    expect(wrapper.emitted('open-space')?.[0]).toEqual([history[0]])
    expect(wrapper.emitted('retry-failed')?.[0]).toEqual([history[1]])
    expect(wrapper.emitted('delete-failed')?.[0]).toEqual([history[1]])
  })

  it('shows one clickable generating item when partial card content is available', async () => {
    const runningSpace = {
      id: 'space-running',
      title: '生成中的课程',
      createdAt: '2026-09-22T00:00:00Z',
      generationStatus: 'running',
      rootCardId: 'card-running',
    }
    const wrapper = mount(HomeLibrary, {
      props: {
        history: [runningSpace],
        historyCards: {
          'space-running': [{ id: 'card-running', title: '生成中的课程', cardType: 'root' }],
        },
      },
    })

    expect(wrapper.find('.generation-item').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在生成')
    expect(wrapper.text()).toContain('查看已生成内容')
    expect(wrapper.text()).not.toContain('开始学习')
    expect(wrapper.findAll('.history-item')).toHaveLength(1)
    await wrapper.find('.generation-item .history-open').trigger('click')
    expect(wrapper.emitted('open-card')?.[0]).toEqual([{
      card: { id: 'card-running', title: '生成中的课程', cardType: 'root' },
      space: runningSpace,
    }])
  })
})
