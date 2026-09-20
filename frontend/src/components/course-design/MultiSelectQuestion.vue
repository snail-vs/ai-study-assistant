<script setup lang="ts">
import { ref, watch } from 'vue'
import type { CourseDesignQuestion } from '../../stores/course-design'

const props = defineProps<{ question: CourseDesignQuestion; selected?: string[]; customText?: string; busy?: boolean }>()
const emit = defineEmits<{ submit: [selected: string[], customText: string]; back: [] ; complete: [] }>()
const selected = ref<string[]>([...(props.selected || [])])
const customText = ref(props.customText || '')
watch(() => props.question.id, () => {
  selected.value = [...(props.selected || [])]
  customText.value = props.customText || ''
})
watch(() => props.selected, (value) => { selected.value = [...(value || [])] }, { deep: true })
watch(() => props.customText, (value) => { customText.value = value || '' })

function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}
function submit() { emit('submit', selected.value, customText.value) }
</script>

<template>
  <section
    class="course-design-panel course-question"
    aria-live="polite"
  >
    <div class="course-design-stepper">
      <span>课程需求澄清</span><strong>{{ question.stage === 'collecting_goals' ? '1 / 3' : '2 / 3' }}</strong>
    </div>
    <div class="course-question-copy">
      <span class="course-speaker">AI</span>
      <div>
        <h2>{{ question.title }}</h2><p v-if="question.description">
          {{ question.description }}
        </p>
      </div>
    </div>
    <div
      class="course-option-grid"
      role="group"
      :aria-label="question.title"
    >
      <button
        v-for="option in question.options"
        :key="option.id"
        type="button"
        class="course-option-chip"
        :class="{ selected: selected.includes(option.id) }"
        :aria-pressed="selected.includes(option.id)"
        :disabled="busy"
        @click="toggle(option.id)"
      >
        {{ option.label }}
      </button>
    </div>
    <textarea
      v-if="question.allowCustom"
      v-model="customText"
      class="course-design-textarea"
      :disabled="busy"
      placeholder="也可以补充你的具体目标或经验…"
    />
    <div class="course-design-actions">
      <button
        type="button"
        class="secondary"
        :disabled="busy"
        @click="emit('back')"
      >
        返回
      </button>
      <button
        type="button"
        class="secondary"
        :disabled="busy"
        @click="emit('complete')"
      >
        AI 帮我补全
      </button>
      <button
        type="button"
        class="primary"
        :disabled="busy || (!selected.length && !customText.trim())"
        @click="submit"
      >
        下一步
      </button>
    </div>
  </section>
</template>
