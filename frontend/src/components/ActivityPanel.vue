<script setup>
defineProps({ activeActivity: { type: Object, default: null }, activityAnswers: { type: Object, default: () => ({}) }, activityResult: { type: Object, default: null }, activityLoading: Boolean, activitySubmitting: Boolean, followUpAnswer: { type: String, default: '' }, followUpSubmitting: Boolean, masteryLabel: { type: Function, required: true } })
const emit = defineEmits(['submit', 'submit-follow-up', 'retry', 'close', 'update:followUpAnswer', 'update:answer'])
</script>
<template>
  <section class="quiz-screen">
    <div
      v-if="activityLoading"
      class="activity-loading"
    >
      <i class="status-spinner" />正在根据本节内容准备理解检查…
    </div><template v-else-if="activeActivity">
      <div class="quiz-intro">
        <div><span class="quiz-kicker">学习活动</span><h2>{{ activeActivity.title }}</h2><p>{{ activeActivity.objective }}</p></div><button
          class="quiz-close"
          @click="emit('close')"
        >
          返回课程内容
        </button>
      </div><div
        v-if="!activityResult"
        class="quiz-questions"
      >
        <article
          v-for="(question, index) in activeActivity.questions"
          :key="question.id"
          class="quiz-question"
        >
          <h3>{{ index + 1 }}. {{ question.prompt }}</h3><div
            v-if="question.type === 'short_answer'"
            class="quiz-options"
          >
            <textarea
              :value="activityAnswers[question.id]"
              placeholder="用一两句话写下你的理解…"
              @input="emit('update:answer', { id: question.id, value: $event.target.value })"
            />
          </div><div
            v-else
            class="quiz-options"
          >
            <label
              v-for="option in (question.options?.length ? question.options : [{ id: true, text: '正确' }, { id: false, text: '错误' }])"
              :key="String(option.id)"
            ><input
              :checked="activityAnswers[question.id] === option.id"
              :name="question.id"
              type="radio"
              :value="option.id"
              @change="emit('update:answer', { id: question.id, value: option.id })"
            ><span>{{ option.text }}</span></label>
          </div>
        </article><button
          class="primary quiz-submit"
          :disabled="activitySubmitting"
          @click="emit('submit')"
        >
          {{ activitySubmitting ? '正在分析你的回答…' : '提交答案' }}
        </button>
      </div><section
        v-else
        class="quiz-result"
      >
        <div class="quiz-score">
          <strong>{{ activityResult.score }}</strong><span>分</span><em>{{ masteryLabel(activityResult.masteryLevel) }}</em>
        </div><p class="quiz-diagnostic">
          {{ activityResult.diagnosticSummary }}
        </p><article
          v-for="(result, index) in activityResult.results"
          :key="result.questionId"
          class="quiz-result-item"
          :class="{ correct: result.correct }"
        >
          <div><b>{{ result.correct ? '✓' : '!' }}</b><strong>第 {{ index + 1 }} 题</strong></div><p>{{ result.feedback }}</p><small v-if="result.referenceAnswer">参考答案：{{ result.referenceAnswer }}</small>
        </article><section
          v-if="activityResult.followUp"
          class="quiz-follow-up"
        >
          <div class="quiz-follow-up-head">
            <span class="quiz-kicker">针对性追问</span><span
              v-if="activityResult.followUp.status === 'completed'"
              class="quiz-follow-up-status"
            >已完成</span>
          </div><p class="quiz-follow-up-prompt">
            {{ activityResult.followUp.prompt }}
          </p><template v-if="activityResult.followUp.status === 'pending'">
            <textarea
              :value="followUpAnswer"
              class="quiz-follow-up-input"
              maxlength="4000"
              placeholder="补充说明你的理解…"
              @input="emit('update:followUpAnswer', $event.target.value)"
            /><div class="quiz-follow-up-meta">
              <span>{{ followUpAnswer.length }} / 4000</span><button
                class="primary"
                :disabled="followUpSubmitting"
                @click="emit('submit-follow-up')"
              >
                {{ followUpSubmitting ? '正在分析…' : '提交追问回答' }}
              </button>
            </div>
          </template><div
            v-else-if="activityResult.followUp.result"
            class="quiz-follow-up-feedback"
            :class="{ correct: activityResult.followUp.result.correct }"
          >
            <strong>{{ activityResult.followUp.result.correct ? '回答通过' : '还需要补充' }}</strong><p>{{ activityResult.followUp.result.feedback }}</p><small v-if="activityResult.postFollowUpMastery">当前掌握状态：{{ masteryLabel(activityResult.postFollowUpMastery) }}</small>
          </div>
        </section><div class="quiz-result-actions">
          <button
            class="secondary"
            @click="emit('retry')"
          >
            重新尝试
          </button><button
            class="primary"
            @click="emit('close')"
          >
            返回课程内容
          </button>
        </div>
      </section>
    </template>
  </section>
</template>
