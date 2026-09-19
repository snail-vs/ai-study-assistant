<script setup>
defineProps({ card: { type: Object, required: true }, activeSection: { type: Number, required: true }, learningView: { type: String, required: true }, relatedCards: { type: Array, default: () => [] }, recommendations: { type: Array, default: () => [] }, recommendationGroupLabel: { type: String, default: '' }, quizStatusLabel: { type: String, default: '理解检查' }, relationLabel: { type: Function, required: true } })
const emit = defineEmits(['toggle', 'select-section', 'open-quiz', 'open-related-card', 'select-recommendation'])
</script>
<template>
  <aside class="sidebar panel">
    <div class="sidebar-head">
      <div class="panel-title">
        学习导航
      </div><button
        class="sidebar-toggle"
        title="收起学习导航"
        @click="emit('toggle')"
      >
        ‹
      </button>
    </div><div class="tree-label">
      章节目录
    </div><button
      v-for="(item, index) in card.sections"
      :key="item.id"
      class="tree-item"
      :class="{ active: index === activeSection }"
      @click="emit('select-section', index)"
    >
      <span>{{ String(index + 1).padStart(2, '0') }}</span>{{ item.title }}
    </button><button
      class="activity-nav-item"
      :class="{ active: learningView === 'activity' }"
      @click="emit('open-quiz')"
    >
      <span>✓</span>理解检查 <small>{{ quizStatusLabel }}</small>
    </button><div class="tree-label related">
      本节学习分支
    </div><button
      v-for="related in relatedCards"
      :key="related.id"
      class="related-card"
      :class="{ active: card.id === related.id }"
      @click="emit('open-related-card', related)"
    >
      <span>↳ {{ relationLabel(related.relationType) }} · </span>{{ related.title }}
    </button><div
      v-if="!relatedCards.length"
      class="empty-related"
    >
      从问题讨论中生成<br>新的学习分支
    </div><div
      v-if="recommendations.length"
      class="tree-label related"
    >
      {{ recommendationGroupLabel }}
    </div><button
      v-for="item in recommendations"
      :key="item.id || item.proposalId"
      class="recommendation-link"
      @click="emit('select-recommendation', item)"
    >
      <span>＋ {{ relationLabel(item.relationType || 'prerequisite') }} · </span>{{ item.title }}
    </button>
  </aside>
</template>
