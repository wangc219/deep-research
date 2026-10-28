<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  ArrowRight,
  BrainCircuit,
  ClipboardList,
  FileCheck2,
  Play,
  Sparkles,
  Star
} from '@lucide/vue'
import {
  EQUIPMENT_WORKFLOW_STEPS,
  equipmentWorkflowLocation,
  nextEquipmentWorkflowStep,
  resolveEquipmentWorkflowRunId,
  resolveEquipmentWorkflowStep
} from '@/utils/equipmentWorkflow.js'

const route = useRoute()
const router = useRouter()

const icons = {
  queries: Sparkles,
  runs: Play,
  capabilities: ClipboardList,
  'deep-thinking': BrainCircuit,
  reports: FileCheck2,
  favorites: Star
}
const current = computed(() => resolveEquipmentWorkflowStep(route.path))
const currentIndex = computed(() =>
  EQUIPMENT_WORKFLOW_STEPS.findIndex((step) => step.id === current.value.id)
)
const runId = computed(() => resolveEquipmentWorkflowRunId(route))
const nextStep = computed(() => nextEquipmentWorkflowStep(current.value.id))
const locationFor = (step) => equipmentWorkflowLocation(step, runId.value)
const goNext = () => router.push(locationFor(nextStep.value))
</script>

<template>
  <section class="equipment-workflow-nav" aria-label="装备研究全流程导航">
    <div class="workflow-heading">
      <span>装备研究流程</span>
      <small v-if="runId" title="后续页面将继续使用当前研究任务">已关联当前任务</small>
      <small v-else>随时进入任一步骤</small>
    </div>

    <nav aria-label="研究流程步骤">
      <RouterLink
        v-for="(step, index) in EQUIPMENT_WORKFLOW_STEPS"
        :key="step.id"
        :to="locationFor(step)"
        class="workflow-step"
        :class="{ current: step.id === current.id, completed: index < currentIndex }"
        :aria-current="step.id === current.id ? 'step' : undefined"
        :title="`${step.label}：${step.description}`"
      >
        <span class="workflow-step-index">
          <component :is="icons[step.id]" :size="13" />
        </span>
        <span>
          <b>{{ step.shortLabel }}</b>
          <small>{{ step.description }}</small>
        </span>
      </RouterLink>
    </nav>

    <button type="button" class="workflow-next" @click="goNext">
      <span><small>下一步</small><b>{{ nextStep.action }}</b></span>
      <ArrowRight :size="15" />
    </button>
  </section>
</template>

<style scoped>
.equipment-workflow-nav {
  display: grid;
  z-index: 30;
  flex: 0 0 auto;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  min-height: 62px;
  padding: 8px clamp(12px, 2vw, 26px);
  border-bottom: 1px solid color-mix(in srgb, var(--main-color) 12%, var(--gray-100));
  background: color-mix(in srgb, var(--gray-0) 94%, var(--main-25));
  box-shadow: 0 6px 18px rgb(66 98 132 / 6%);
}
.workflow-heading {
  display: grid;
  min-width: 108px;
  gap: 1px;
}
.workflow-heading > span {
  color: var(--gray-850, var(--gray-900));
  font-size: 12px;
  font-weight: 700;
}
.workflow-heading > small { color: var(--gray-450); font-size: 9px; }
.workflow-heading > small:first-of-type { color: var(--main-color); }
.equipment-workflow-nav nav {
  display: grid;
  grid-template-columns: repeat(6, minmax(88px, 1fr));
  min-width: 0;
  gap: 4px;
}
.workflow-step {
  display: flex;
  min-width: 0;
  min-height: 42px;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  border: 1px solid transparent;
  border-radius: 9px;
  color: var(--gray-550, var(--gray-600));
  text-decoration: none;
  transition: background .16s ease, border-color .16s ease, color .16s ease;
}
.workflow-step:hover {
  background: color-mix(in srgb, var(--main-color) 6%, transparent);
  color: var(--main-color);
}
.workflow-step.current {
  border-color: color-mix(in srgb, var(--main-color) 24%, var(--gray-100));
  background: color-mix(in srgb, var(--main-color) 9%, var(--gray-0));
  color: var(--main-color);
}
.workflow-step.completed .workflow-step-index {
  background: color-mix(in srgb, var(--main-color) 12%, var(--gray-0));
  color: var(--main-color);
}
.workflow-step-index {
  display: grid;
  flex: 0 0 25px;
  width: 25px;
  height: 25px;
  place-items: center;
  border-radius: 8px;
  background: var(--gray-50);
  color: var(--gray-500);
}
.workflow-step > span:last-child {
  display: grid;
  min-width: 0;
  gap: 1px;
}
.workflow-step b {
  overflow: hidden;
  font-size: 10px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workflow-step small {
  overflow: hidden;
  color: var(--gray-400);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workflow-next {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 8px;
  padding: 5px 10px 5px 12px;
  border: 1px solid color-mix(in srgb, var(--main-color) 22%, var(--gray-100));
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--main-color);
}
.workflow-next > span { display: grid; text-align: left; }
.workflow-next small { color: var(--gray-400); font-size: 8px; }
.workflow-next b { font-size: 10px; font-weight: 650; white-space: nowrap; }
.workflow-next:hover { background: color-mix(in srgb, var(--main-color) 7%, var(--gray-0)); }

:global(html.dark) .equipment-workflow-nav {
  border-bottom-color: #2b3445;
  background: rgb(17 22 34 / 96%);
  box-shadow: 0 6px 18px rgb(0 0 0 / 18%);
}
:global(html.dark) .workflow-step.current,
:global(html.dark) .workflow-next { background: #20283a; }
:global(html.dark) .workflow-step-index { background: #252d3d; }

@media (max-width: 1180px) {
  .workflow-heading { display: none; }
  .equipment-workflow-nav { grid-template-columns: minmax(0, 1fr) auto; }
}
@media (max-width: 820px) {
  .equipment-workflow-nav {
    grid-template-columns: minmax(0, 1fr);
    min-height: 53px;
    padding: 6px 10px;
  }
  .equipment-workflow-nav nav {
    display: flex;
    overflow-x: auto;
    gap: 4px;
    scrollbar-width: none;
  }
  .equipment-workflow-nav nav::-webkit-scrollbar { display: none; }
  .workflow-step {
    flex: 0 0 auto;
    min-height: 38px;
    padding: 4px 8px;
  }
  .workflow-step small { display: none; }
  .workflow-next { display: none; }
}
@media print {
  .equipment-workflow-nav { display: none; }
}
</style>
