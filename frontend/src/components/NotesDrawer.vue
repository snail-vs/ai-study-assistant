<script setup>
defineProps({
  editorMode: { type: String, required: true }, notesList: { type: Array, default: () => [] }, editingNote: { type: Object, default: null },
  editorTitle: { type: String, default: '' }, editorContent: { type: String, default: '' }, targetCardId: { type: String, default: '' }, targetSectionId: { type: String, default: '' }, editorSource: { type: String, default: '' }, cardOptions: { type: Array, default: () => [] }, targetSections: { type: Array, default: () => [] }, noteSource: { type: Function, required: true },
})
const emit = defineEmits(['close', 'close-editor', 'start', 'edit', 'remove', 'create', 'update', 'update:editorTitle', 'update:editorContent', 'update:targetCardId', 'update:targetSectionId'])
</script>

<template>
  <div
    class="notes-backdrop"
    @click.self="emit('close')"
  >
    <aside class="notes-drawer">
      <div class="notes-drawer-head">
        <div>
          <div class="panel-title">
            {{ editorMode === 'list' ? '我的笔记' : editorMode === 'create' ? '记笔记' : '编辑笔记' }}
          </div><p>{{ editorMode === 'list' ? '记录、整理和回看学习过程中的重要内容。' : editorSource }}</p>
        </div><button @click="emit('close')">
          ×
        </button>
      </div>
      <div
        v-if="editorMode !== 'list'"
        class="note-editor"
      >
        <div
          v-if="editorMode === 'create'"
          class="note-target-fields"
        >
          <label>知识卡<select
            :value="targetCardId"
            @change="emit('update:targetCardId', $event.target.value); emit('update:targetSectionId', '')"
          ><option
            v-for="card in cardOptions"
            :key="card.id"
            :value="card.id"
          >{{ card.title }}</option></select></label><label>章节<select
            :value="targetSectionId"
            @change="emit('update:targetSectionId', $event.target.value)"
          ><option value="">整张知识卡</option><option
            v-for="section in targetSections"
            :key="section.id"
            :value="section.id"
          >{{ section.title }}</option></select></label>
        </div><input
          :value="editorTitle"
          placeholder="笔记标题"
          @input="emit('update:editorTitle', $event.target.value)"
        ><textarea
          :value="editorContent"
          placeholder="写下你的理解…"
          @input="emit('update:editorContent', $event.target.value)"
        /><div class="note-editor-actions">
          <button
            class="secondary"
            @click="emit('close-editor')"
          >
            取消
          </button><button
            class="primary"
            :disabled="!editorContent.trim()"
            @click="emit(editorMode === 'create' ? 'create' : 'update')"
          >
            {{ editorMode === 'create' ? '保存笔记' : '保存修改' }}
          </button>
        </div>
      </div>
      <div
        v-else
        class="notes-list"
      >
        <div class="notes-list-toolbar">
          <button
            :disabled="!cardOptions.length"
            @click="emit('start')"
          >
            ＋ 新建笔记
          </button>
        </div><div
          v-if="!notesList.length"
          class="notes-empty"
        >
          还没有笔记。<br>在学习页面记录第一条笔记吧。
        </div><article
          v-for="item in notesList"
          :key="item.id"
          class="note-item"
        >
          <div class="note-item-head">
            <strong>{{ item.title }}</strong><div>
              <button @click="emit('edit', item)">
                编辑
              </button><button @click="emit('remove', item)">
                删除
              </button>
            </div>
          </div><p>{{ item.content }}</p><small>{{ noteSource(item) }} · {{ new Date(item.updatedAt).toLocaleString('zh-CN') }}</small>
        </article>
      </div>
    </aside>
  </div>
</template>
