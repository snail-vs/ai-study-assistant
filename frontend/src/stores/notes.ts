import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { request } from '../api/client'

type Note = Record<string, any>
type Card = Record<string, any>
type Section = Record<string, any>

/** Note list and editor state for the learning workspace notes drawer. */
export const useNotesStore = defineStore('notes', () => {
  const notesList = ref<Note[]>([])
  const showNotes = ref(false)
  const editingNote = ref<Note | null>(null)
  const editorMode = ref('list')
  const editorTitle = ref('')
  const editorContent = ref('')
  const editorInitial = ref({ title: '', content: '' })
  const targetCardId = ref('')
  const targetSectionId = ref('')
  const loading = ref(false)

  const editorDirty = computed(() => editorMode.value !== 'list' && (
    editorTitle.value !== editorInitial.value.title
    || editorContent.value !== editorInitial.value.content
  ))

  function noteSource(item: Note, cards: Card[] = []) {
    const owner = cards.find((entry) => entry.id === item.cardId)
    if (!owner) return '学习笔记'
    const section = owner.sections?.find((entry: Section) => entry.id === item.sectionId)
    return section ? `${owner.title} · ${section.title}` : owner.title
  }

  async function loadNotes() {
    loading.value = true
    try {
      notesList.value = await request<Note[]>('/notes')
    } catch (_) {
      // Notes remain optional if the API is temporarily unavailable.
    } finally {
      loading.value = false
    }
    return notesList.value
  }

  function resetEditor() {
    editingNote.value = null
    editorMode.value = 'list'
    editorTitle.value = ''
    editorContent.value = ''
    editorInitial.value = { title: '', content: '' }
    targetCardId.value = ''
    targetSectionId.value = ''
  }

  async function openNotes() {
    await loadNotes()
    resetEditor()
    showNotes.value = true
  }

  function startNote(card: Card | null, section: Section | null) {
    if (!card) return false
    editingNote.value = null
    editorMode.value = 'create'
    targetCardId.value = card.id
    targetSectionId.value = section?.id || ''
    editorTitle.value = ''
    editorContent.value = ''
    editorInitial.value = { title: '', content: '' }
    showNotes.value = true
    return true
  }

  function editNote(item: Note) {
    editingNote.value = item
    editorMode.value = 'edit'
    editorTitle.value = item.title || ''
    editorContent.value = item.content || ''
    editorInitial.value = { title: editorTitle.value, content: editorContent.value }
  }

  async function createNote() {
    if (!targetCardId.value || !editorContent.value.trim()) return null
    const created = await request<Note>(`/cards/${targetCardId.value}/notes`, {
      method: 'POST',
      body: JSON.stringify({
        title: editorTitle.value.trim() || null,
        sectionId: targetSectionId.value || null,
        content: editorContent.value.trim(),
        sourceType: 'manual',
      }),
    })
    await loadNotes()
    resetEditor()
    return created
  }

  async function updateNote() {
    if (!editingNote.value || !editorContent.value.trim()) return null
    const updated = await request<Note>(`/notes/${editingNote.value.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        title: editorTitle.value.trim() || '未命名笔记',
        content: editorContent.value.trim(),
      }),
    })
    notesList.value = notesList.value.map((item) => item.id === updated.id ? updated : item)
    resetEditor()
    return updated
  }

  async function removeNote(item: Note) {
    await request(`/notes/${item.id}`, { method: 'DELETE' })
    notesList.value = notesList.value.filter((entry) => entry.id !== item.id)
    if (editingNote.value?.id === item.id) resetEditor()
  }

  function closeNotes() {
    showNotes.value = false
    resetEditor()
  }

  return {
    notesList, showNotes, editingNote, editorMode, editorTitle, editorContent,
    editorInitial, targetCardId, targetSectionId, loading, editorDirty,
    loadNotes, openNotes, startNote, editNote, resetEditor, createNote,
    updateNote, removeNote, closeNotes, noteSource,
  }
})
