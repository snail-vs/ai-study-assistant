<script setup lang="ts">
import { onMounted, watch } from 'vue'
import MultiSelectQuestion from './MultiSelectQuestion.vue'
import CourseBriefReview from './CourseBriefReview.vue'
import CourseOutlineReview from './CourseOutlineReview.vue'
import { useCourseDesignStore, type CourseScale } from '../../stores/course-design'

const props = defineProps<{ editingLearningSpaceId?: string | null; initialTopic?: string }>()
const emit = defineEmits<{ courseQueued: [spaceId: string, title: string]; cancel: [] }>()
const store = useCourseDesignStore()
onMounted(() => { if (!store.session) void store.restore() })
watch(() => props.initialTopic, (value) => {
  if (value && !store.session && !store.topic) store.topic = value
}, { immediate: true })

async function start() {
  try { await store.begin(store.topic, props.editingLearningSpaceId) } catch { /* store exposes the error in the flow */ }
}
async function answer(selected: string[], custom: string) {
  store.setSelectedOptionIds(selected)
  store.setCustomAnswer(custom)
  try { await store.answerQuestion() } catch { /* store exposes the error in the flow */ }
}
async function backFromQuestion() {
  if (store.isGoalStage) { store.reset(); return }
  try { await store.goBack() } catch { /* store exposes the error in the flow */ }
}
async function completeWithAI() { try { await store.completeWithAI() } catch { /* store exposes the error in the flow */ } }
async function generate(outcome: string, prior: string) {
  store.setOutcomeDraft(outcome)
  store.setPriorKnowledgeDraft(prior)
  try { await store.updateBriefAndGenerateOutline() } catch { /* store exposes the error in the flow */ }
}
async function generateCourse() { const title = store.topic; try { const result = await store.generateCourse(); if (result.spaceId) emit('courseQueued', result.spaceId, title) } catch { /* store exposes the error in the flow */ } }
async function revise(feedback: string) { try { await store.reviseOutline(feedback) } catch { /* store exposes the error in the flow */ } }
async function confirm() { try { await store.confirmOutline() } catch { /* store exposes the error in the flow */ } }
async function selectScale(scale: CourseScale) { try { await store.selectScale(scale) } catch { /* store exposes the error in the flow */ } }
async function backFromBrief() { try { await store.goBack() } catch { /* store exposes the error in the flow */ } }
async function backFromOutline() { try { await store.goBack() } catch { /* store exposes the error in the flow */ } }
</script>

<template>
  <section class="course-design-flow">
    <form
      v-if="store.phase === 'topic'"
      class="course-design-panel course-topic-step"
      @submit.prevent="start"
    >
      <span class="eyebrow">创建你的课程</span><h2>你想学习什么？</h2><textarea
        v-model="store.topic"
        name="topic"
        class="course-design-textarea course-topic-input"
        placeholder="例如：我想系统理解 Kubernetes Operator，并能独立开发一个 Operator…"
        autofocus
      /><div class="course-design-actions">
        <button
          v-if="editingLearningSpaceId"
          type="button"
          class="secondary"
          @click="emit('cancel')"
        >
          取消
        </button><button
          type="submit"
          class="primary"
          :disabled="store.loading"
        >
          {{ store.loading ? '正在准备…' : '开始设计课程' }}
        </button>
      </div>
    </form>
    <MultiSelectQuestion
      v-else-if="store.phase === 'intake' && store.question"
      :key="store.question.id"
      :question="store.question"
      :selected="store.selectedOptionIds"
      :custom-text="store.customAnswer"
      :busy="store.loading"
      @submit="answer"
      @back="backFromQuestion"
      @complete="completeWithAI"
    />
    <CourseBriefReview
      v-else-if="store.phase === 'brief' && store.session"
      :session="store.session"
      :brief="store.brief"
      :scales="store.scaleOptions"
      :busy="store.loading"
      :active-command="store.activeCommand"
      @scale="selectScale"
      @generate="generate"
      @back="backFromBrief"
      @restart="store.reset"
    />
    <CourseOutlineReview
      v-else-if="store.phase === 'outline' && store.session"
      :session="store.session"
      :busy="store.loading"
      :active-command="store.activeCommand"
      :error="store.error"
      @revise="revise"
      @confirm="confirm"
      @back="backFromOutline"
      @generate-course="generateCourse"
    />
    <div
      v-if="store.error && store.phase !== 'outline'"
      class="course-design-error"
      role="alert"
    >
      {{ store.error }}
    </div>
  </section>
</template>
