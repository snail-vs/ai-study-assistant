// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import NotesDrawer from './NotesDrawer.vue'

const cards = [
  { id: 'card-1', title: '微积分', sections: [{ id: 'section-1', title: '导数' }] },
  { id: 'card-2', title: '线性代数', sections: [] },
]

const notes = [
  { id: 'note-1', cardId: 'card-1', sectionId: 'section-1', title: '链式法则', content: '复合函数求导', updatedAt: '2026-09-20T10:00:00Z' },
  { id: 'note-2', cardId: 'card-2', title: '矩阵', content: '线性变换的表示', updatedAt: '2026-09-21T10:00:00Z' },
]

const source = (note: Record<string, string>) => note.cardId === 'card-1' ? '微积分 · 导数' : '线性代数'

function mountDrawer(overrides = {}) {
  return mount(NotesDrawer, {
    props: {
      editorMode: 'list',
      notesList: notes,
      cardOptions: cards,
      targetSections: cards[0].sections,
      noteSource: source,
      ...overrides,
    },
  })
}

describe('NotesDrawer', () => {
  afterEach(() => document.body.innerHTML = '')

  it('searches note title, content and source and can clear the filter', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[aria-label="搜索笔记"]').setValue('导数')

    expect(wrapper.text()).toContain('链式法则')
    expect(wrapper.text()).not.toContain('矩阵')
    expect(wrapper.text()).toContain('1 条结果')
    await wrapper.find('.notes-list-summary button').trigger('click')
    expect(wrapper.text()).toContain('矩阵')
  })

  it('opens a note from the library and exposes loading and deletion states', async () => {
    const wrapper = mountDrawer({ deletingNoteId: 'note-1' })

    await wrapper.findAll('.note-item-main')[0].trigger('click')

    expect(wrapper.emitted('edit')?.[0]).toEqual([notes[1]])
    expect(wrapper.find('[aria-label="删除链式法则"]').text()).toBe('…')
    await wrapper.setProps({ loading: true })
    expect(wrapper.find('.notes-loading').exists()).toBe(true)
  })

  it('saves with the keyboard shortcut and reports editor state', async () => {
    const wrapper = mountDrawer({
      editorMode: 'edit',
      editingNote: notes[0],
      editorTitle: '链式法则',
      editorContent: '更新后的内容',
      editorSource: '微积分 · 导数',
      dirty: true,
    })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update')).toHaveLength(1)
    expect(wrapper.text()).toContain('有未保存修改')
    expect(wrapper.text()).toContain('6 字')
  })

  it('disables save while content is blank or a request is in progress', async () => {
    const wrapper = mountDrawer({ editorMode: 'create', editorContent: '   ', saving: false })
    expect(wrapper.find('.note-editor-actions .primary').attributes('disabled')).toBeDefined()

    await wrapper.setProps({ editorContent: '正文', saving: true })
    expect(wrapper.find('.note-editor-actions .primary').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在保存')
  })
})
