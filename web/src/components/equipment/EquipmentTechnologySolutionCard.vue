<script setup>
import { computed } from 'vue'
import { ArrowRight, CheckCircle2, CircleDashed, Wrench } from '@lucide/vue'
import { technologySolutionFromSession } from '@/utils/equipmentTechnologySolutions.js'

const props = defineProps({
  equipmentName: { type: String, default: '当前装备' },
  session: { type: Object, default: null },
  loading: { type: Boolean, default: false }
})

defineEmits(['open'])

const solution = computed(() => technologySolutionFromSession(props.session || {}))
const activeJob = computed(() =>
  (Array.isArray(props.session?.jobs) ? props.session.jobs : []).some(
    (item) => !['completed', 'failed', 'cancelled', 'canceled', 'rejected'].includes(String(item?.status || '').toLowerCase())
  )
)
const statusLabel = computed(() => {
  if (props.loading) return '读取中'
  if (activeJob.value) return '方案生成中'
  if (solution.value) return '已有技术方案'
  if (props.session) return '攻关进行中'
  return '尚未启动'
})
const preview = computed(() => {
  const content = solution.value?.content || ''
  return content.length > 2400 ? `${content.slice(0, 2400)}…` : content
})
const updatedLabel = computed(() => {
  const value = solution.value?.createdAt || solution.value?.updatedAt
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { hour12: false })
})
</script>

<template>
  <section class="technology-solution" :class="{ ready: solution, running: activeJob }" aria-label="技术实现方案">
    <header>
      <span class="technology-solution-icon"><Wrench :size="17" /></span>
      <div>
        <small>原能力画像配套研发成果</small>
        <strong>技术实现方案 · {{ equipmentName }}</strong>
      </div>
      <em>
        <CheckCircle2 v-if="solution" :size="13" />
        <CircleDashed v-else :size="13" />
        {{ statusLabel }}
      </em>
    </header>

    <div v-if="solution" class="technology-solution-body">
      <div class="technology-solution-labels" aria-label="方案结构">
        <span>核心技术</span><span>卡点根因</span><span>攻关路线</span><span>工程实现</span><span>试验验证</span><span>TRL / 风险</span>
      </div>
      <pre>{{ preview }}</pre>
      <footer>
        <small>{{ updatedLabel ? `最近形成：${updatedLabel}` : '已形成可继续迭代的方案' }}</small>
        <button type="button" @click="$emit('open')">继续完善方案<ArrowRight :size="13" /></button>
      </footer>
    </div>

    <div v-else class="technology-solution-empty">
      <div>
        <b>{{ activeJob ? '正在形成技术实现方案' : '原卡技术描述仅作为攻关线索' }}</b>
        <p>围绕研发所需核心技术、真实卡点、工程实现与验证路线继续深挖，形成可供一线研发人员执行的具体方案。</p>
      </div>
      <button type="button" :disabled="loading || activeJob" @click="$emit('open')">
        {{ props.session ? '继续技术攻关' : '进入技术攻关舱' }}<ArrowRight :size="13" />
      </button>
    </div>
  </section>
</template>

<style scoped>
.technology-solution {
  overflow: hidden;
  margin: 0 0 12px;
  border: 1px solid color-mix(in srgb, var(--main-300) 58%, var(--gray-150));
  border-radius: 12px;
  background:
    linear-gradient(110deg, color-mix(in srgb, var(--main-50) 86%, transparent), transparent 62%),
    var(--gray-0);
  box-shadow: 0 8px 22px rgb(39 53 82 / 7%);
}
.technology-solution > header,
.technology-solution > header > div,
.technology-solution > header > em,
.technology-solution-empty,
.technology-solution-body footer,
.technology-solution-labels {
  display: flex;
  align-items: center;
}
.technology-solution > header {
  gap: 10px;
  min-height: 58px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--main-100);
}
.technology-solution-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 9px;
  background: var(--main-color);
  color: #fff;
}
.technology-solution > header > div {
  min-width: 0;
  flex: 1;
  align-items: flex-start;
  flex-direction: column;
  gap: 2px;
}
.technology-solution > header small {
  color: var(--gray-500);
  font-size: 10px;
}
.technology-solution > header strong {
  overflow: hidden;
  max-width: 100%;
  color: var(--gray-900);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.technology-solution > header > em {
  gap: 5px;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--gray-75);
  color: var(--gray-600);
  font-size: 10px;
  font-style: normal;
  font-weight: 650;
  white-space: nowrap;
}
.technology-solution.ready > header > em {
  background: #edf8f1;
  color: #2e7c52;
}
.technology-solution.running > header > em {
  background: #fff7e7;
  color: #94641f;
}
.technology-solution-empty {
  justify-content: space-between;
  gap: 18px;
  padding: 14px;
}
.technology-solution-empty > div {
  min-width: 0;
}
.technology-solution-empty b {
  color: var(--gray-800);
  font-size: 12px;
}
.technology-solution-empty p {
  max-width: 760px;
  margin: 4px 0 0;
  color: var(--gray-550);
  font-size: 11px;
  line-height: 1.55;
}
.technology-solution button {
  flex: 0 0 auto;
  border-color: var(--main-300);
  background: var(--main-color);
  color: #fff;
}
.technology-solution-body {
  padding: 12px 14px 14px;
}
.technology-solution-labels {
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 9px;
}
.technology-solution-labels span {
  padding: 3px 7px;
  border: 1px solid var(--main-100);
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-700);
  font-size: 9px;
}
.technology-solution-body pre {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: 11px 12px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  background: var(--gray-25);
  color: var(--gray-750);
  font-family: inherit;
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.technology-solution-body footer {
  justify-content: space-between;
  gap: 12px;
  margin-top: 9px;
}
.technology-solution-body footer small {
  color: var(--gray-500);
  font-size: 9px;
}
:global(html.dark) .technology-solution {
  border-color: #43496a;
  background: linear-gradient(110deg, rgb(59 54 105 / 42%), transparent 62%), #1c2333;
}
:global(html.dark) .technology-solution > header,
:global(html.dark) .technology-solution-body pre {
  border-color: #343a47;
}
:global(html.dark) .technology-solution-body pre {
  background: #171d2a;
}
@media (max-width: 640px) {
  .technology-solution-empty,
  .technology-solution-body footer {
    align-items: stretch;
    flex-direction: column;
  }
  .technology-solution-empty button,
  .technology-solution-body footer button {
    width: 100%;
  }
  .technology-solution > header strong {
    white-space: normal;
  }
}
</style>
