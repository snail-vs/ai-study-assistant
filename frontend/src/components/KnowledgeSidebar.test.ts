import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import KnowledgeSidebar from './KnowledgeSidebar.vue'

describe('KnowledgeSidebar', () => {
  const card = {
    id: 'card-1',
    sections: [
      { id: 'ready', title: '已经生成', generationStatus: 'completed' },
      { id: 'pending', title: '等待生成', generationStatus: 'pending' },
      { id: 'generating', title: '正在生成', generationStatus: 'generating' },
      { id: 'failed', title: '生成出错', generationStatus: 'failed' },
    ],
  }

  function mountSidebar() {
    return mount(KnowledgeSidebar, {
      props: {
        card,
        activeSection: 0,
        learningView: 'content',
        relationLabel: (value: string) => value,
      },
    })
  }

  it('disables unfinished sections and shows their generation states', () => {
    const wrapper = mountSidebar()
    const sections = wrapper.findAll('.tree-item')

    expect(sections[0].attributes('disabled')).toBeUndefined()
    expect(sections[1].attributes('disabled')).toBeDefined()
    expect(sections[2].attributes('disabled')).toBeDefined()
    expect(sections[3].attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.tree-status').map((item) => item.text())).toEqual(['待生成', '生成中', '生成失败'])
  })

  it('only emits selection for an available section', async () => {
    const wrapper = mountSidebar()
    const sections = wrapper.findAll('.tree-item')

    await sections[0].trigger('click')
    await sections[1].trigger('click')

    expect(wrapper.emitted('select-section')).toEqual([[0]])
  })
})
