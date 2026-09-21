<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CourseBrief, CourseDesignSession, CourseScale, ScaleOption } from '../../stores/course-design'

const props = defineProps<{ session: CourseDesignSession; brief: CourseBrief; scales: ScaleOption[]; busy?: boolean; activeCommand?: string | null }>()
const emit = defineEmits<{ scale: [value: CourseScale]; generate: [learningOutcome: string, priorKnowledge: string]; back: []; restart: [] }>()
const outcome = ref(props.brief.learningOutcome || '')
const prior = ref(props.brief.priorKnowledge || '')
watch(() => props.brief.learningOutcome, (value) => { outcome.value = value || '' })
watch(() => props.brief.priorKnowledge, (value) => { prior.value = value || '' })
const loadingLabel = computed(() => ({
  update_brief: '正在保存/整理课程需求…',
  select_scale: '正在保存课程规模…',
  generate_outline: '正在生成课程大纲…',
}[props.activeCommand || ''] || ''))
const generatingOutline = computed(() => props.busy && ['update_brief', 'generate_outline'].includes(props.activeCommand || ''))
</script>

<template>
  <section class="course-design-panel course-brief-review">
    <div class="course-design-head">
      <div><span class="eyebrow">课程设计建议 · 3 / 3</span><h2>确认你的学习路径</h2></div><button
        class="secondary"
        type="button"
        :disabled="busy"
        @click="emit('restart')"
      >
        重新开始
      </button>
    </div>
    <div class="course-topic-summary">
      <h3>学习主题</h3><p>{{ brief.topic || '未填写主题' }}</p>
    </div>
    <div class="course-brief-block">
      <h3>学习目标</h3><div class="course-readonly-tags">
        <span
          v-for="item in (brief.learningGoals || [])"
          :key="item"
        >{{ item }}</span><span
          v-if="!brief.learningGoals?.length"
          class="muted"
        >暂无结构化目标</span>
      </div><textarea
        v-model="outcome"
        class="course-design-textarea"
        :disabled="busy"
        aria-label="学习目标总结"
        placeholder="AI 整理的学习目标，可在这里调整…"
      />
    </div>
    <div class="course-brief-block">
      <h3>个人基础</h3><div class="course-readonly-tags">
        <span
          v-for="item in (brief.priorKnowledgeLevels || [])"
          :key="item"
        >{{ item }}</span><span
          v-if="!brief.priorKnowledgeLevels?.length"
          class="muted"
        >暂无结构化基础信息</span>
      </div><textarea
        v-model="prior"
        class="course-design-textarea"
        :disabled="busy"
        aria-label="个人基础总结"
        placeholder="AI 整理的个人基础，可在这里调整…"
      />
    </div>
    <div class="course-scale-section">
      <div class="course-section-title">
        <h3>课程规模</h3><span
          v-if="session.recommendedScale"
          class="course-recommendation"
        >AI 推荐：{{ scales.find((item) => item.id === session.recommendedScale)?.label }}</span>
      </div><div class="course-scale-grid">
        <button
          v-for="option in scales"
          :key="option.id"
          type="button"
          class="course-scale-card"
          :class="{ selected: session.selectedScale === option.id }"
          :disabled="busy"
          @click="emit('scale', option.id)"
        >
          <strong>{{ option.label }}</strong><small>{{ option.hint }}</small><span>{{ option.detail }}</span><em v-if="session.recommendedScale === option.id">AI 推荐</em>
        </button>
      </div>
    </div>
    <div
      v-if="busy && loadingLabel"
      class="course-outline-loading"
      aria-live="polite"
    >
      <i class="status-spinner" /><span>{{ loadingLabel }}</span>
    </div>
    <div class="course-design-actions">
      <button
        type="button"
        class="secondary"
        :disabled="busy"
        @click="emit('back')"
      >
        返回修改基础
      </button><button
        type="button"
        class="primary"
        :disabled="busy || !session.selectedScale || !outcome.trim() || !prior.trim()"
        :aria-busy="generatingOutline"
        @click="emit('generate', outcome, prior)"
      >
        <template v-if="generatingOutline"><i class="status-spinner" />正在生成课程大纲…</template>
        <template v-else>生成课程大纲</template>
      </button>
    </div>
  </section>
</template>
