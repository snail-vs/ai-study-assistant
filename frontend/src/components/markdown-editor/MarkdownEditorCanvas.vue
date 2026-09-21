<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { Crepe } from '@milkdown/crepe'
import type { Editor } from '@milkdown/kit/core'
import { Milkdown, useEditor } from '@milkdown/vue'
import { replaceAll } from '@milkdown/kit/utils'

const props = defineProps<{
  modelValue: string
  readonly?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const builder = shallowRef<Crepe | null>(null)
let editorInstance: Editor | null = null
let syncingExternalValue = false
let lastMarkdown = props.modelValue

const { loading } = useEditor((root) => {
  const crepe = new Crepe({
    root,
    defaultValue: props.modelValue,
    features: {
      [Crepe.Feature.ImageBlock]: false,
      [Crepe.Feature.Latex]: false,
      [Crepe.Feature.TopBar]: false,
      [Crepe.Feature.AI]: false,
    },
    featureConfigs: {
      [Crepe.Feature.Cursor]: {
        virtual: false,
      },
      [Crepe.Feature.Placeholder]: {
        text: props.placeholder || '写下你的理解、疑问或灵感…',
        mode: 'block',
      },
    },
  })
  crepe.setReadonly(Boolean(props.readonly))
  crepe.on((listener) => {
    listener.markdownUpdated((_ctx, markdown) => {
      if (syncingExternalValue || markdown === lastMarkdown) return
      lastMarkdown = markdown
      emit('update:modelValue', markdown)
    })
    listener.destroy(() => { editorInstance = null })
  })
  builder.value = crepe
  editorInstance = crepe.editor
  return crepe
})

watch(() => props.modelValue, (value) => {
  if (value === lastMarkdown) return
  const editor = editorInstance
  if (!editor) return
  lastMarkdown = value
  syncingExternalValue = true
  try {
    editor.action(replaceAll(value))
  } finally {
    syncingExternalValue = false
  }
})

watch(() => props.readonly, (value) => {
  builder.value?.setReadonly(Boolean(value))
})
</script>

<template>
  <div class="markdown-editor-canvas" :aria-busy="loading">
    <Milkdown />
    <span v-if="loading" class="markdown-editor-loading">正在准备编辑器…</span>
  </div>
</template>
