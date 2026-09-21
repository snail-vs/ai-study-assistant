import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { request } from '../api/client'
import { useNotesStore } from './notes'

vi.mock('../api/client', () => ({ request: vi.fn() }))

const mockedRequest = vi.mocked(request)

const card = {
  id: 'card-1',
  title: '函数',
  sections: [{ id: 'section-1', title: '导数' }],
}

describe('notes store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedRequest.mockReset()
  })

  it('loads notes and keeps the list usable when the endpoint fails', async () => {
    mockedRequest.mockResolvedValueOnce([{ id: 'note-1', title: '重点', content: '内容' }] as never)
    const store = useNotesStore()

    await store.loadNotes()

    expect(store.notesList).toHaveLength(1)
    expect(store.loading).toBe(false)
    mockedRequest.mockRejectedValueOnce(new Error('temporarily unavailable'))
    await expect(store.loadNotes()).resolves.toEqual(store.notesList)
    expect(store.loading).toBe(false)
    expect(store.operationError).toBe('temporarily unavailable')
  })

  it('starts and edits a note while preserving the initial snapshot for dirty state', () => {
    const store = useNotesStore()

    store.startNote(card, card.sections[0])
    expect(store.editorMode).toBe('create')
    expect(store.targetCardId).toBe('card-1')
    expect(store.targetSectionId).toBe('section-1')
    store.editorContent = 'new content'
    expect(store.editorDirty).toBe(true)

    const note = { id: 'note-1', title: '旧标题', content: '旧内容', cardId: 'card-1', sectionId: 'section-1' }
    store.editNote(note)
    expect(store.editorMode).toBe('edit')
    expect(store.editorTitle).toBe('旧标题')
    expect(store.editorDirty).toBe(false)
  })

  it('creates and updates notes, then resets the editor', async () => {
    mockedRequest
      .mockResolvedValueOnce({ id: 'note-1', title: '新笔记', content: '正文' } as never)
      .mockResolvedValueOnce([{ id: 'note-1', title: '新笔记', content: '正文' }] as never)
      .mockResolvedValueOnce({ id: 'note-1', title: '更新标题', content: '更新正文' } as never)
    const store = useNotesStore()
    store.startNote(card, card.sections[0])
    store.editorTitle = '新笔记'
    store.editorContent = '正文'

    await store.createNote()

    expect(mockedRequest).toHaveBeenNthCalledWith(1, '/cards/card-1/notes', expect.objectContaining({ method: 'POST' }))
    expect(store.editorMode).toBe('list')
    store.editNote(store.notesList[0])
    store.editorTitle = '更新标题'
    store.editorContent = '更新正文'
    await store.updateNote()

    expect(store.notesList[0]).toMatchObject({ title: '更新标题', content: '更新正文' })
    expect(store.editorMode).toBe('list')
  })

  it('deletes a note and resets an active editor for that note', async () => {
    mockedRequest.mockResolvedValueOnce({ status: 'deleted' } as never)
    const store = useNotesStore()
    const note = { id: 'note-1', title: '重点', content: '内容' }
    store.notesList = [note]
    store.editNote(note)

    await store.removeNote(note)

    expect(mockedRequest).toHaveBeenCalledWith('/notes/note-1', { method: 'DELETE' })
    expect(store.notesList).toEqual([])
    expect(store.editorMode).toBe('list')
  })

  it('exposes a save error and always releases the saving state', async () => {
    mockedRequest.mockRejectedValueOnce(new Error('保存服务不可用'))
    const store = useNotesStore()
    store.startNote(card, card.sections[0])
    store.editorContent = '不能丢失的内容'

    await expect(store.createNote()).rejects.toThrow('保存服务不可用')

    expect(store.saving).toBe(false)
    expect(store.operationError).toBe('保存服务不可用')
    expect(store.editorContent).toBe('不能丢失的内容')
    expect(store.editorDirty).toBe(true)
  })

  it('resets note context when opening a new notes drawer', async () => {
    mockedRequest.mockResolvedValueOnce([{ id: 'note-1' }] as never)
    const store = useNotesStore()
    store.startNote(card, card.sections[0])
    store.editorContent = '未保存'

    await store.openNotes()

    expect(store.showNotes).toBe(true)
    expect(store.editorMode).toBe('list')
    expect(store.targetCardId).toBe('')
    expect(store.editorContent).toBe('')
  })
})
