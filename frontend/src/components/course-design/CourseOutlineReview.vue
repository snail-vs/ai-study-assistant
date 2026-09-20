<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CourseDesignMessage, CourseDesignSession } from '../../stores/course-design'
const props = defineProps<{ session: CourseDesignSession; busy?: boolean; activeCommand?: string | null; error?: string }>()
const emit = defineEmits<{ revise: [feedback: string]; confirm: []; back: []; generateCourse: [] }>()
const feedback = ref('')
const submittedMessageCount = ref(props.session.outlineRevisionMessages.length)
watch(() => props.session.outlineRevisionMessages.length, (count) => {
  if (count > submittedMessageCount.value) feedback.value = ''
  submittedMessageCount.value = count
})
const loadingLabel = computed(() => ({
  generate_outline: '正在生成课程大纲…',
  revise_outline: '正在根据你的建议修改大纲…',
  confirm_outline: '正在确认大纲…',
  generate_course: '正在提交课程生成…',
}[props.activeCommand || ''] || ''))
function revise() { if (feedback.value.trim()) emit('revise', feedback.value.trim()) }
</script>

<template>
  <section class="course-design-panel course-outline-review">
    <div class="course-design-head">
      <div><span class="eyebrow">课程大纲</span><h2>确认你的学习路径</h2></div><button
        class="secondary"
        type="button"
        :disabled="busy"
        @click="emit('back')"
      >
        返回调整需求
      </button>
    </div>
    <div
      v-if="busy && loadingLabel"
      class="course-outline-loading"
      aria-live="polite"
    >
      <i class="status-spinner" /><span>{{ loadingLabel }}</span>
    </div>
    <p
      v-if="error"
      class="course-design-error"
      role="alert"
    >
      {{ error }}
    </p>
    <ol
      v-if="session.outline.length"
      class="course-outline-list"
    >
      <li
        v-for="item in session.outline"
        :key="item.title"
      >
        <strong>{{ item.title }}</strong><span>{{ item.objective }}</span>
      </li>
    </ol>
    <div
      v-if="session.outline.length"
      class="course-outline-conversation"
    >
      <article
        v-for="(message, index) in (session.outlineRevisionMessages as CourseDesignMessage[])"
        :key="`${index}-${message.role}`"
        :class="message.role"
      >
        <span>{{ message.role === 'user' ? '你' : 'AI' }}</span><p>{{ message.content }}</p>
      </article><form @submit.prevent="revise">
        <input
          v-model="feedback"
          :disabled="busy"
          placeholder="想调整哪些章节？例如：增加一个实战项目…"
        ><button
          type="submit"
          :disabled="busy || !feedback.trim()"
        >
          修改大纲
        </button>
      </form>
    </div>
    <div class="course-design-actions">
      <button
        v-if="!session.outlineConfirmed"
        type="button"
        class="primary"
        :disabled="busy || !session.outline.length"
        @click="emit('confirm')"
      >
        确认这份大纲
      </button><template v-else>
        <span class="course-confirmed">大纲已确认</span><button
          type="button"
          class="primary"
          :disabled="busy"
          @click="emit('generateCourse')"
        >
          确认并生成课程
        </button>
      </template>
    </div>
  </section>
</template>
