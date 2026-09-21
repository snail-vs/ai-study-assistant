<script setup lang="ts">
import { MilkdownProvider } from '@milkdown/vue'
import MarkdownEditorCanvas from './MarkdownEditorCanvas.vue'
import '@milkdown/crepe/theme/frame.css'
import '@milkdown/crepe/theme/common/style.css'

const props = withDefaults(defineProps<{
  modelValue: string
  readonly?: boolean
  placeholder?: string
}>(), {
  readonly: false,
  placeholder: '写下你的理解、疑问或灵感…',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

</script>

<template>
  <div class="markdown-editor" :class="{ 'is-readonly': readonly }">
    <MilkdownProvider>
      <MarkdownEditorCanvas
        :model-value="modelValue"
        :readonly="readonly"
        :placeholder="placeholder"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </MilkdownProvider>
  </div>
</template>
