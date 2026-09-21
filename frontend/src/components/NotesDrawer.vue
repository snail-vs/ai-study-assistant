<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  editorMode: { type: String, required: true },
  notesList: { type: Array, default: () => [] },
  editingNote: { type: Object, default: null },
  editorTitle: { type: String, default: '' },
  editorContent: { type: String, default: '' },
  targetCardId: { type: String, default: '' },
  targetSectionId: { type: String, default: '' },
  editorSource: { type: String, default: '' },
  cardOptions: { type: Array, default: () => [] },
  targetSections: { type: Array, default: () => [] },
  noteSource: { type: Function, required: true },
  loading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  deletingNoteId: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

const emit = defineEmits([
  'close', 'close-editor', 'start', 'edit', 'remove', 'create', 'update',
  'update:editorTitle', 'update:editorContent', 'update:targetCardId',
  'update:targetSectionId',
])

const query = ref('')
const cardFilter = ref('')
const libraryCollapsed = ref(false)

const filteredNotes = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  return [...props.notesList]
    .filter((item) => !cardFilter.value || item.cardId === cardFilter.value)
    .filter((item) => {
      if (!needle) return true
      return [item.title, item.content, props.noteSource(item)]
        .some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(needle))
    })
    .sort((left, right) => new Date(right.updatedAt || 0).getTime() - new Date(left.updatedAt || 0).getTime())
})

const contentCount = computed(() => props.editorContent.trim().length)
const isEditing = computed(() => props.editorMode !== 'list')
const canSave = computed(() => Boolean(props.editorContent.trim()) && !props.saving)
const shortcutModifier = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
  ? '⌘'
  : 'Ctrl'

function formatUpdatedAt(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  }
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function notePreview(item) {
  return String(item.content || '').replace(/\s+/g, ' ').trim() || '暂无正文'
}

function save() {
  if (!canSave.value) return
  emit(props.editorMode === 'create' ? 'create' : 'update')
}

function handleKeydown(event) {
  if (!isEditing.value) return
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    save()
  } else if (event.key === 'Escape') {
    emit('close-editor')
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="notes-backdrop" @click.self="emit('close')">
    <aside class="notes-drawer" :class="{ 'is-editing': isEditing, 'library-collapsed': libraryCollapsed }" aria-label="我的笔记">
      <header class="notes-drawer-head">
        <div class="notes-heading-copy">
          <span class="notes-kicker">LEARNING NOTES</span>
          <div class="notes-heading-line">
            <h2>我的笔记</h2>
            <span v-if="notesList.length" class="notes-count">{{ notesList.length }}</span>
          </div>
        </div>
        <div class="notes-head-actions">
          <button
            class="notes-library-toggle"
            type="button"
            :aria-expanded="!libraryCollapsed"
            :aria-label="libraryCollapsed ? '展开笔记列表' : '收起笔记列表'"
            @click="libraryCollapsed = !libraryCollapsed"
          >
            <span aria-hidden="true">{{ libraryCollapsed ? '→' : '←' }}</span>
            <span class="notes-library-toggle-label">{{ libraryCollapsed ? '展开列表' : '收起列表' }}</span>
          </button>
          <button class="notes-close" type="button" aria-label="关闭笔记" @click="emit('close')">×</button>
        </div>
      </header>

      <div v-if="errorMessage" class="notes-error" role="alert">
        <span>!</span>{{ errorMessage }}
      </div>

      <div class="notes-workspace">
        <section class="notes-library" aria-label="笔记列表">
          <div class="notes-library-actions">
            <button class="notes-new" type="button" :disabled="!cardOptions.length" @click="emit('start')">
              <span>＋</span> 新建笔记
            </button>
            <label class="notes-search">
              <span aria-hidden="true">⌕</span>
              <input v-model="query" type="search" placeholder="搜索标题、正文或来源" aria-label="搜索笔记">
            </label>
            <select v-model="cardFilter" class="notes-filter" aria-label="按知识卡筛选">
              <option value="">全部知识卡</option>
              <option v-for="card in cardOptions" :key="card.id" :value="card.id">{{ card.title }}</option>
            </select>
          </div>

          <div class="notes-list-summary">
            <span>{{ query || cardFilter ? `${filteredNotes.length} 条结果` : '最近更新' }}</span>
            <button v-if="query || cardFilter" type="button" @click="query = ''; cardFilter = ''">清除筛选</button>
          </div>

          <div class="notes-list">
            <div v-if="loading" class="notes-loading" role="status">
              <i v-for="index in 3" :key="index" />
              <span>正在加载笔记…</span>
            </div>
            <div v-else-if="!notesList.length" class="notes-empty">
              <span class="notes-empty-icon">✎</span>
              <strong>把理解留下来</strong>
              <p>记录概念、疑问和灵感，之后复习时会更轻松。</p>
              <button type="button" :disabled="!cardOptions.length" @click="emit('start')">写第一条笔记</button>
            </div>
            <div v-else-if="!filteredNotes.length" class="notes-empty notes-no-results">
              <strong>没有找到匹配的笔记</strong>
              <p>换个关键词，或者清除筛选条件试试。</p>
            </div>
            <article
              v-for="item in filteredNotes"
              v-else
              :key="item.id"
              class="note-item"
              :class="{ active: editingNote?.id === item.id }"
            >
              <button class="note-item-main" type="button" @click="emit('edit', item)">
                <span class="note-item-source">{{ noteSource(item) }}</span>
                <strong>{{ item.title || '未命名笔记' }}</strong>
                <p>{{ notePreview(item) }}</p>
                <small>{{ formatUpdatedAt(item.updatedAt) }}</small>
              </button>
              <button
                class="note-delete"
                type="button"
                :disabled="Boolean(deletingNoteId)"
                :aria-label="`删除${item.title || '未命名笔记'}`"
                @click="emit('remove', item)"
              >{{ deletingNoteId === item.id ? '…' : '删除' }}</button>
            </article>
          </div>
        </section>

        <section v-if="isEditing" class="note-editor" aria-label="笔记编辑器">
          <header class="note-editor-head">
            <button class="note-editor-back" type="button" @click="emit('close-editor')">← <span>返回笔记库</span></button>
            <div class="note-save-state" :class="{ dirty }">
              <i />{{ saving ? '正在保存…' : dirty ? '有未保存修改' : '已保存' }}
            </div>
          </header>

          <div class="note-editor-scroll">
            <div class="note-editor-context">
              <span>{{ editorMode === 'create' ? '新笔记' : '编辑笔记' }}</span>
              <strong>{{ editorSource }}</strong>
            </div>

            <div v-if="editorMode === 'create'" class="note-target-fields">
              <label>知识卡
                <select :value="targetCardId" @change="emit('update:targetCardId', $event.target.value); emit('update:targetSectionId', '')">
                  <option v-for="card in cardOptions" :key="card.id" :value="card.id">{{ card.title }}</option>
                </select>
              </label>
              <label>记录到
                <select :value="targetSectionId" @change="emit('update:targetSectionId', $event.target.value)">
                  <option value="">整张知识卡</option>
                  <option v-for="section in targetSections" :key="section.id" :value="section.id">{{ section.title }}</option>
                </select>
              </label>
            </div>

            <input
              class="note-title-input"
              :value="editorTitle"
              placeholder="给这条笔记一个标题"
              aria-label="笔记标题"
              @input="emit('update:editorTitle', $event.target.value)"
            >
            <textarea
              class="note-content-input"
              :value="editorContent"
              placeholder="写下你的理解、疑问或灵感…\n\n不必追求完整，先把此刻最重要的想法记下来。"
              autofocus
              aria-label="笔记正文"
              @input="emit('update:editorContent', $event.target.value)"
            />
          </div>

          <footer class="note-editor-actions">
            <span>{{ contentCount }} 字</span>
            <span class="note-shortcut">{{ shortcutModifier }} + S 保存</span>
            <button class="secondary" type="button" :disabled="saving" @click="emit('close-editor')">取消</button>
            <button class="primary" type="button" :disabled="!canSave" @click="save">
              {{ saving ? '保存中…' : editorMode === 'create' ? '保存笔记' : '保存修改' }}
            </button>
          </footer>
        </section>

        <section v-else class="notes-welcome" aria-label="笔记使用提示">
          <div class="notes-welcome-mark">✦</div>
          <span>你的学习记忆</span>
          <h3>{{ notesList.length ? '选择一条笔记继续整理' : '从一条笔记开始' }}</h3>
          <p>左侧可以按关键词和知识卡查找。打开笔记后直接编辑，按 Ctrl / ⌘ + S 即可保存。</p>
          <button type="button" :disabled="!cardOptions.length" @click="emit('start')">新建笔记</button>
        </section>
      </div>
    </aside>
  </div>
</template>
