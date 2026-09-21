<script setup lang="ts">
import { computed, ref } from 'vue'

type LearningSpace = Record<string, any>
type LearningCard = Record<string, any>
type HomeCard = { card: LearningCard; space: LearningSpace }
type ViewMode = 'cards' | 'spaces'

const props = defineProps<{
  history: LearningSpace[]
  historyCards: Record<string, LearningCard[]>
}>()

const emit = defineEmits([
  'open-card', 'open-space', 'retry-failed', 'delete-failed', 'delete-card',
])

const homeViewMode = ref<ViewMode>(localStorage.getItem('studycenter.homeViewMode') === 'spaces' ? 'spaces' : 'cards')

const homeCards = computed<HomeCard[]>(() => props.history.flatMap((spaceItem) => (
  (props.historyCards[spaceItem.id] || []).map((cardItem) => ({ card: cardItem, space: spaceItem }))
)))
const spaceSummaries = computed(() => props.history.map((spaceItem) => ({
  space: spaceItem,
  cardCount: (props.historyCards[spaceItem.id] || []).length,
})))
const creatingSpaces = computed(() => props.history.filter((item) => (
  item.generationStatus === 'queued' || item.generationStatus === 'running' || item.generationStatus === 'failed'
)))

function setHomeViewMode(mode: ViewMode) {
  homeViewMode.value = mode
  localStorage.setItem('studycenter.homeViewMode', mode)
}

function generationStatusLabel(item: LearningSpace) {
  if (item.generationStatus === 'queued') return '排队中'
  if (item.generationStatus === 'running') return '正在生成'
  if (item.generationStatus === 'failed') return `生成失败：${item.generationError || '请重试'}`
  return '已完成'
}

function openSpace(item: LearningSpace) {
  if (!item.rootCardId || item.generationStatus !== 'completed') return
  emit('open-space', item)
}
</script>

<template>
  <div v-if="history.length" class="history">
    <div class="history-heading">
      <div class="history-title">{{ homeViewMode === 'cards' ? '我的知识卡' : '我的学习空间' }}</div>
      <div class="history-view-switch" role="tablist" aria-label="首页列表视图">
        <button :class="{ active: homeViewMode === 'cards' }" role="tab" :aria-selected="homeViewMode === 'cards'" @click="setHomeViewMode('cards')">知识卡</button>
        <button :class="{ active: homeViewMode === 'spaces' }" role="tab" :aria-selected="homeViewMode === 'spaces'" @click="setHomeViewMode('spaces')">学习空间</button>
      </div>
    </div>
    <template v-if="homeViewMode === 'spaces'">
      <div v-for="item in spaceSummaries" :key="item.space.id" class="history-item space-history-item">
        <button class="history-open" :disabled="item.space.generationStatus !== 'completed' || !item.space.rootCardId" @click="openSpace(item.space)">
          <span>{{ item.space.title }}</span>
          <small>{{ generationStatusLabel(item.space) }} · {{ item.cardCount }} 张知识卡 · {{ new Date(item.space.createdAt).toLocaleDateString('zh-CN') }}</small>
        </button>
        <div class="history-actions">
          <button v-if="item.space.generationStatus === 'failed'" class="history-delete retry-generation" @click.stop="emit('retry-failed', item.space)">继续生成</button>
          <button v-if="item.space.generationStatus === 'failed'" class="history-delete" @click.stop="emit('delete-failed', item.space)">删除</button>
        </div>
      </div>
    </template>
    <template v-else>
      <div v-for="item in creatingSpaces" :key="item.id" class="history-item generation-item">
        <div class="history-open">
          <span>{{ item.title }}</span>
          <small>{{ generationStatusLabel(item) }}</small>
        </div>
        <button v-if="item.generationStatus === 'failed'" class="history-delete retry-generation" @click="emit('retry-failed', item)">继续生成</button>
        <button v-if="item.generationStatus === 'failed'" class="history-delete" @click="emit('delete-failed', item)">删除</button>
      </div>
      <div v-for="item in homeCards" :key="item.card.id" class="history-item">
        <button class="history-open" @click="emit('open-card', item)">
          <span>{{ item.card.title }}</span>
          <small>{{ new Date(item.space.createdAt).toLocaleDateString('zh-CN') }} · 开始学习 →</small>
        </button>
        <button class="history-delete" title="删除知识卡" @click.stop="emit('delete-card', item)">删除</button>
      </div>
    </template>
  </div>
</template>
