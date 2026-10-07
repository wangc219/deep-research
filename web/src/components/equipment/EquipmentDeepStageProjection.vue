<script setup>
import { computed, ref, watch } from 'vue'
import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  GitBranch,
  ShieldCheck,
  Sparkles,
  Target
} from '@lucide/vue'
import { projectEquipmentDeepStage } from '@/utils/equipmentDeepStageProjection.js'

const props = defineProps({
  session: { type: Object, default: null },
  agentState: { type: Object, default: null },
  conversations: { type: Array, default: () => [] },
  todos: { type: Array, default: () => [] },
  subagentRuns: { type: Array, default: () => [] },
  versions: { type: Array, default: () => [] },
  activeSkillIds: { type: Array, default: null },
  processing: { type: Boolean, default: false },
  createArtifact: { type: Boolean, default: false },
  researchMode: { type: String, default: 'new_weapon_diverge' },
  researchSection: { type: String, default: '' }
})

const emit = defineEmits(['focus-direction', 'author-card'])
// 全景中的阶段条默认保持简洁；执行开始时仍会自动展开，保留过程即时反馈。
const collapsed = ref(true)
const projection = computed(() =>
  projectEquipmentDeepStage({
    session: props.session,
    agentState: props.agentState,
    conversations: props.conversations,
    todos: props.todos,
    subagentRuns: props.subagentRuns,
    versions: props.versions,
    activeSkillIds: props.activeSkillIds,
    processing: props.processing,
    createArtifact: props.createArtifact,
    researchMode: props.researchMode,
    researchSection: props.researchSection
  })
)
const progressedCount = computed(
  () =>
    projection.value.stages.filter((item) =>
      ['completed', 'observed', 'running'].includes(item.status)
    ).length
)
const currentStage = computed(
  () =>
    projection.value.stages.find((item) => item.status === 'running') ||
    [...projection.value.stages]
      .reverse()
      .find((item) => ['completed', 'observed'].includes(item.status)) ||
    projection.value.stages[0]
)

watch(
  () => props.processing,
  (processing) => {
    if (processing) collapsed.value = false
  }
)

const stageIcon = (status) => {
  if (status === 'completed') return Check
  if (status === 'observed') return BookOpen
  if (status === 'failed' || status === 'partial') return CircleAlert
  return status === 'running' ? Sparkles : Clock3
}
</script>

<template>
  <section class="deep-stage-projection" :aria-label="`深研阶段与${projection.title}`">
    <header class="deep-stage-heading">
      <div>
        <span class="deep-stage-heading-icon"><BrainCircuit :size="16" /></span>
        <span>
          <b>{{ projection.title }}</b>
          <small v-if="processing">阶段过程实时投影 · 最终回答仍以对话正文为准</small>
          <small v-else
            >{{ currentStage?.label }} · 5 个环节中 {{ progressedCount }} 个已有进展 ·
            可非线性推进</small
          >
        </span>
      </div>
      <button
        type="button"
        :aria-expanded="!collapsed"
        aria-controls="deep-stage-projection-body"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? `展开${projection.title}` : '收起' }}
        <ChevronDown :size="13" :class="{ rotated: !collapsed }" />
      </button>
    </header>

    <nav class="deep-stage-strip" :aria-label="`${projection.title}五环节`">
      <div
        v-for="(item, index) in projection.stages"
        :key="item.key"
        class="deep-stage-step"
        :class="`is-${item.status}`"
        :title="item.detail"
      >
        <span><component :is="stageIcon(item.status)" :size="12" /></span>
        <div>
          <b>{{ item.label }}</b
          ><small>{{ item.detail }}</small>
        </div>
        <ArrowRight v-if="index < projection.stages.length - 1" :size="12" />
      </div>
    </nav>

    <div v-if="!collapsed" id="deep-stage-projection-body" class="deep-stage-body">
      <section v-if="projection.candidates.length" class="deep-stage-block candidate-block">
        <header>
          <Sparkles :size="14" />
          <b>{{ projection.mode === 'section_deepen' ? '同装备深化方案' : '新质候选方向' }}</b>
          <em>{{ projection.candidates.length }}</em>
        </header>
        <div class="candidate-grid">
          <article v-for="item in projection.candidates.slice(0, 6)" :key="item.name">
            <button type="button" class="candidate-main" @click="emit('focus-direction', item)">
              <b>{{ item.name }}</b>
              <small v-if="item.angle || item.equipmentForm">
                {{ [item.angle, item.equipmentForm].filter(Boolean).join(' · ') }}
              </small>
              <p v-if="item.summary">{{ item.summary }}</p>
            </button>
            <button
              v-if="projection.mode !== 'section_deepen'"
              type="button"
              class="candidate-author"
              @click="emit('author-card', item)"
            >
              <Sparkles :size="11" /> 成卡
            </button>
          </article>
        </div>
      </section>

      <section
        v-if="projection.decisions.length || projection.rejected.length"
        class="deep-stage-block decision-block"
      >
        <header><ShieldCheck :size="14" /><b>议事裁决</b></header>
        <div class="decision-columns">
          <div v-if="projection.decisions.length">
            <strong>保留与深化</strong>
            <button
              v-for="item in projection.decisions"
              :key="`keep-${item.name}`"
              type="button"
              @click="emit('focus-direction', item)"
            >
              <Check :size="11" /><span
                ><b>{{ item.name }}</b
                ><small>{{ item.reason }}</small></span
              >
            </button>
          </div>
          <div v-if="projection.rejected.length" class="rejected-decisions">
            <strong>排除或待重构</strong>
            <article v-for="item in projection.rejected" :key="`reject-${item.name}`">
              <CircleAlert :size="11" /><span
                ><b>{{ item.name }}</b
                ><small>{{ item.reason }}</small></span
              >
            </article>
          </div>
        </div>
      </section>

      <section v-if="projection.handoffs.length" class="deep-stage-block handoff-block">
        <header>
          <GitBranch :size="14" /><b>Agent 交接</b><em>{{ projection.handoffs.length }}</em>
        </header>
        <div class="handoff-list">
          <article v-for="item in projection.handoffs" :key="item.id" :class="`is-${item.status}`">
            <span class="handoff-status-dot"></span>
            <div>
              <b>{{ item.name }}</b
              ><small>{{ item.task || item.summary || '协同研究任务' }}</small>
            </div>
            <em>{{ item.statusLabel }}</em>
          </article>
        </div>
      </section>

      <details
        v-if="
          projection.memory.objective ||
          projection.memory.assumptions.length ||
          projection.memory.openQuestions.length ||
          projection.memory.activeSkillIds.length
        "
        class="deep-memory-summary"
      >
        <summary><BookOpen :size="13" /><b>决策记忆</b><span>目标、假设与未决问题</span></summary>
        <div>
          <section v-if="projection.memory.objective">
            <strong><Target :size="12" /> 当前目标</strong>
            <p>{{ projection.memory.objective }}</p>
          </section>
          <section v-if="projection.memory.assumptions.length">
            <strong>关键假设</strong>
            <ul>
              <li v-for="item in projection.memory.assumptions" :key="item">{{ item }}</li>
            </ul>
          </section>
          <section v-if="projection.memory.openQuestions.length">
            <strong>未决问题</strong>
            <ul>
              <li v-for="item in projection.memory.openQuestions" :key="item">{{ item }}</li>
            </ul>
          </section>
          <section v-if="projection.memory.activeSkillIds.length">
            <strong>本轮 Skill</strong>
            <div class="deep-memory-skills">
              <code v-for="item in projection.memory.activeSkillIds" :key="item">{{ item }}</code>
            </div>
          </section>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.deep-stage-projection {
  position: relative;
  z-index: 2;
  flex: 0 0 auto;
  border-bottom: 1px solid var(--gray-150);
  background:
    radial-gradient(
      circle at 10% 0%,
      color-mix(in srgb, var(--main-100) 45%, transparent),
      transparent 34%
    ),
    var(--gray-0);
  color: var(--gray-900);
}

.deep-stage-heading,
.deep-stage-heading > div,
.deep-stage-block > header,
.deep-memory-summary summary {
  display: flex;
  align-items: center;
}

.deep-stage-heading {
  justify-content: space-between;
  gap: 14px;
  padding: 10px 18px 8px;
}

.deep-stage-heading > div {
  min-width: 0;
  gap: 9px;
}

.deep-stage-heading-icon {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--main-200);
  border-radius: 10px;
  background: var(--main-50);
  color: var(--main-700);
}

.deep-stage-heading > div > span:last-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.deep-stage-heading b {
  font-size: 13px;
  letter-spacing: 0.02em;
}

.deep-stage-heading small {
  overflow: hidden;
  color: var(--gray-600);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deep-stage-heading > button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: var(--gray-600);
  cursor: pointer;
  font-size: 11px;
}

.deep-stage-heading > button svg {
  transition: transform 0.18s ease;
}

.deep-stage-heading > button svg.rotated {
  transform: rotate(180deg);
}

.deep-stage-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
  padding: 0 18px 10px;
}

.deep-stage-step {
  position: relative;
  display: grid;
  min-width: 0;
  grid-template-columns: 22px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 6px;
}

.deep-stage-step:last-child {
  grid-template-columns: 22px minmax(0, 1fr);
}

.deep-stage-step > span {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 1px solid var(--gray-200);
  border-radius: 999px;
  background: var(--gray-25);
  color: var(--gray-500);
}

.deep-stage-step > div {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.deep-stage-step b {
  color: var(--gray-700);
  font-size: 11px;
  font-weight: 650;
}

.deep-stage-step small {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deep-stage-step > svg {
  color: var(--gray-300);
}

.deep-stage-step.is-completed > span {
  border-color: color-mix(in srgb, var(--color-success-500) 42%, var(--gray-200));
  background: var(--color-success-50);
  color: var(--color-success-700);
}

.deep-stage-step.is-observed > span {
  border-color: color-mix(in srgb, var(--main-300) 52%, var(--gray-200));
  background: color-mix(in srgb, var(--main-50) 74%, var(--gray-0));
  color: var(--main-700);
}

.deep-stage-step.is-observed b {
  color: var(--main-700);
}

.deep-stage-step.is-running > span {
  border-color: var(--main-300);
  background: var(--main-50);
  color: var(--main-700);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--main-100) 58%, transparent);
}

.deep-stage-step.is-running b {
  color: var(--main-700);
}

.deep-stage-step.is-failed > span,
.deep-stage-step.is-partial > span {
  border-color: var(--color-warning-100);
  background: var(--color-warning-50);
  color: var(--color-warning-700);
}

.deep-stage-body {
  display: grid;
  max-height: 310px;
  gap: 10px;
  overflow: auto;
  padding: 0 18px 12px;
}

.deep-stage-block,
.deep-memory-summary {
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: color-mix(in srgb, var(--gray-0) 92%, var(--main-50));
}

.deep-stage-block > header {
  gap: 6px;
  padding: 8px 10px 6px;
  color: var(--main-700);
  font-size: 11px;
}

.deep-stage-block > header em {
  margin-left: auto;
  color: var(--gray-500);
  font-style: normal;
}

.candidate-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
  padding: 0 9px 9px;
}

.candidate-grid article {
  position: relative;
  min-width: 0;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
}

.candidate-main {
  display: grid;
  width: 100%;
  gap: 3px;
  padding: 9px 58px 9px 9px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.candidate-main b {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-main small,
.candidate-main p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: var(--gray-600);
  font-size: 10px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.candidate-author {
  position: absolute;
  top: 7px;
  right: 7px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1px solid var(--main-200);
  border-radius: 6px;
  background: var(--main-50);
  color: var(--main-700);
  cursor: pointer;
  font-size: 9px;
}

.decision-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 0 9px 9px;
}

.decision-columns > div {
  display: grid;
  align-content: start;
  gap: 5px;
}

.decision-columns strong {
  color: var(--gray-600);
  font-size: 10px;
}

.decision-columns button,
.decision-columns article {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 8px;
  border: 1px solid var(--color-success-100);
  border-radius: 8px;
  background: var(--color-success-50);
  color: var(--color-success-900);
  text-align: left;
}

.decision-columns button {
  cursor: pointer;
}

.decision-columns .rejected-decisions article {
  border-color: var(--color-warning-100);
  background: var(--color-warning-50);
  color: var(--color-warning-900);
}

.decision-columns span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.decision-columns b,
.decision-columns small {
  font-size: 10px;
}

.decision-columns small {
  color: var(--gray-600);
}

.handoff-list {
  display: grid;
  gap: 5px;
  padding: 0 9px 9px;
}

.handoff-list article {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  padding: 6px 8px;
  border-radius: 8px;
  background: var(--gray-25);
}

.handoff-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--gray-400);
}

.handoff-list article.is-running .handoff-status-dot {
  background: var(--main-500);
  box-shadow: 0 0 0 3px var(--main-100);
}

.handoff-list article.is-completed .handoff-status-dot {
  background: var(--color-success-500);
}

.handoff-list article.is-failed .handoff-status-dot,
.handoff-list article.is-blocked .handoff-status-dot {
  background: var(--color-error-500);
}

.handoff-list article > div {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.handoff-list b,
.handoff-list small,
.handoff-list em {
  font-size: 10px;
}

.handoff-list small {
  overflow: hidden;
  color: var(--gray-600);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.handoff-list em {
  color: var(--gray-500);
  font-style: normal;
}

.deep-memory-summary summary {
  gap: 6px;
  padding: 8px 10px;
  color: var(--gray-700);
  cursor: pointer;
  font-size: 11px;
}

.deep-memory-summary summary span {
  margin-left: auto;
  color: var(--gray-500);
  font-size: 9px;
}

.deep-memory-summary > div {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 0 10px 10px;
}

.deep-memory-summary section {
  min-width: 0;
  padding: 7px 8px;
  border-radius: 8px;
  background: var(--gray-25);
}

.deep-memory-summary strong {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-700);
  font-size: 10px;
}

.deep-memory-summary p,
.deep-memory-summary ul {
  margin: 5px 0 0;
  padding-left: 15px;
  color: var(--gray-600);
  font-size: 10px;
  line-height: 1.5;
}

.deep-memory-summary p {
  padding-left: 0;
}

.deep-memory-skills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.deep-memory-skills code {
  padding: 2px 5px;
  border-radius: 5px;
  background: var(--main-50);
  color: var(--main-700);
  font-size: 9px;
}

@media (max-width: 900px) {
  .deep-stage-step small {
    display: none;
  }

  .candidate-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .deep-stage-heading,
  .deep-stage-strip,
  .deep-stage-body {
    padding-right: 10px;
    padding-left: 10px;
  }

  .deep-stage-strip {
    overflow-x: auto;
    grid-template-columns: repeat(5, minmax(108px, 1fr));
  }

  .candidate-grid,
  .decision-columns,
  .deep-memory-summary > div {
    grid-template-columns: 1fr;
  }

  .deep-stage-body {
    max-height: 270px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .deep-stage-heading > button svg {
    transition: none;
  }
}
</style>
