<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import { Check } from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import ActionDropdown from '@/components/common/ActionDropdown.vue'
import ActionTrigger from '@/components/common/ActionTrigger.vue'

import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import ProjectSelectionSection from '@/components/ProjectSelectionSection.vue'
import ToolApprovalModeSelector from '@/components/ToolApprovalModeSelector.vue'
import { AUTO_PROJECT_ID } from '@/utils/projectSelection'
import { useUserStore } from '@/stores/user'
import {
  applyFrequencyChange,
  buildCronExpression,
  dayOptions,
  monthOptions,
  parseCronExpression,
  scheduleFrequencies,
  weekdayOptions
} from '@/utils/scheduleFrequency'

const props = defineProps({
  job: { type: Object, default: null },
  seed: { type: Object, default: () => ({}) },
  agents: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  saveState: { type: String, default: 'idle' },
  error: { type: String, default: '' }
})
const emit = defineEmits(['change'])
const userStore = useUserStore()
const projectOwnerUid = computed(() => props.job?.uid || userStore.uid)

const defaultSchedule = {
  frequency: 'daily',
  time: '09:00',
  weekdays: [1],
  dayOfMonth: 1,
  month: 1,
  cronExpression: '0 9 * * *'
}

const agentValues = computed(() =>
  props.agents.map((agent) => agent.slug || agent.id).filter(Boolean)
)

function initialForm(job) {
  const seed = job ? {} : props.seed
  const targetConfig = job?.target_config || seed.target_config || {}
  const schedule = job ? parseCronExpression(job.cron_expression) : defaultSchedule
  return {
    name: job?.name ?? seed.name ?? '新建定时任务',
    target_type: job?.target_type || seed.target_type || 'agent_conversation',
    prompt: job?.prompt || '',
    topic: targetConfig.topic || '',
    source_query_id: targetConfig.source_query_id || '',
    source_query_version: targetConfig.source_query_version || null,
    query_version_policy: targetConfig.query_version_policy || 'latest',
    supplemental_information: targetConfig.supplemental_information || '',
    research_route: targetConfig.research_route || 'auto',
    execution_profile_id: targetConfig.execution_profile_id || 'winning_swarm_dynamic_v2',
    interaction_mode: targetConfig.interaction_mode || 'expert',
    max_rounds: Number(targetConfig.max_rounds) || 2,
    knowledge_enabled: targetConfig.knowledge_enabled !== false,
    knowledge_ids: targetConfig.knowledge_ids ?? null,
    project_id: job?.project_id || seed.project_id || '',
    agent_slug: job?.agent_slug || agentValues.value[0] || '',
    ...schedule,
    cronExpression:
      schedule?.cronExpression || buildCronExpression(schedule) || defaultSchedule.cronExpression,
    model_spec: job?.model_spec || '',
    timezone: job?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
    tool_approval_mode: job?.tool_approval_mode || 'default'
  }
}

const form = reactive(initialForm(props.job))
let hydrating = false
const nameInput = ref(null)
const agentDropdownOpen = ref(false)
const agentSearch = ref('')
const selectedAgentLabel = computed(() => {
  const agent = props.agents.find((item) => (item.slug || item.id) === form.agent_slug)
  return agent?.name || form.agent_slug || '选择智能体'
})
const filteredAgents = computed(() => {
  const query = agentSearch.value.trim().toLocaleLowerCase()
  return props.agents.filter((agent) =>
    [agent.name, agent.slug, agent.id].some((value) =>
      String(value || '')
        .toLocaleLowerCase()
        .includes(query)
    )
  )
})
const queryOptions = ref([])
const queryLoading = ref(false)

async function loadQueries() {
  if (!form.project_id || form.project_id === AUTO_PROJECT_ID || form.target_type !== 'equipment_research') {
    queryOptions.value = []
    return
  }
  queryLoading.value = true
  try {
    const response = await equipmentApi.listQueries({
      project_id: form.project_id,
      status: 'published',
      limit: 100,
      offset: 0
    })
    const rows = response?.items || response?.queries || response?.data || []
    queryOptions.value = rows.filter((item) => !item.project_id || item.project_id === form.project_id)
  } catch {
    queryOptions.value = []
  } finally {
    queryLoading.value = false
  }
}

function selectQuery() {
  const query = queryOptions.value.find((item) => item.query_id === form.source_query_id)
  if (!query) {
    form.source_query_version = null
    return
  }
  form.topic = query.query || form.topic
  form.supplemental_information = query.supplemental_information || ''
  form.source_query_version = Number(query.version) || 1
  form.knowledge_enabled = query.knowledge_enabled !== false
  form.knowledge_ids = query.knowledge_ids ?? null
  if (!props.job && form.name === '新建定时任务') form.name = `定时研究：${form.topic.slice(0, 28)}`
}

/** 选择任务智能体，不改变全局对话的智能体。 */
function selectAgent(agent) {
  form.agent_slug = agent.slug || agent.id
  agentDropdownOpen.value = false
}

/** 打开配置时选中名称，方便直接改名。 */
function focusName() {
  nameInput.value?.focus({ preventScroll: true })
  nameInput.value?.select()
}

onMounted(() => {
  focusName()
  void loadQueries()
})

const daysInSelectedMonth = computed(() => {
  if (form.frequency !== 'yearly') return 31
  if (Number(form.month) === 2) return 28
  return [4, 6, 9, 11].includes(Number(form.month)) ? 30 : 31
})
const availableDayOptions = computed(() => dayOptions.slice(0, daysInSelectedMonth.value))

const saveLabel = computed(() => {
  if (!props.job && props.saveState === 'invalid') return '填写完整后自动创建'
  if (props.saveState === 'dirty') return '等待自动保存'
  if (props.saveState === 'saving' || props.saving) return '正在保存'
  if (props.saveState === 'saved') return '已自动保存'
  if (props.saveState === 'error') return '保存失败'
  if (props.saveState === 'invalid') return '补全必填项后自动保存'
  return props.job ? '修改会自动保存' : '填写完整后自动创建'
})

function validationMessage() {
  if (!form.name.trim()) return '请输入任务名称'
  if (!form.project_id || form.project_id === AUTO_PROJECT_ID) return '请选择一个 Project'
  if (form.target_type === 'agent_conversation') {
    if (!form.prompt.trim()) return '请输入任务指令'
    if (!form.agent_slug) return '请选择执行智能体'
  } else if (!form.topic.trim()) return '请输入研究主题或选择已发布 Query'
  if (form.frequency === 'weekly' && !form.weekdays.length) return '请至少选择一个执行日'
  if (form.frequency !== 'custom' && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(form.time)) {
    return '请选择执行时间'
  }
  if (form.frequency === 'custom' && (form.cronExpression || '').trim().split(/\s+/).length !== 5) {
    return '请输入有效的五段 Cron 表达式'
  }
  return ''
}

function changePayload() {
  const validationError = validationMessage()
  if (validationError) return { error: validationError, payload: null }
  return {
    error: '',
    payload: {
      name: form.name.trim(),
      target_type: form.target_type,
      target_config: form.target_type === 'equipment_research'
        ? {
            topic: form.topic.trim(),
            source_query_id: form.source_query_id || null,
            source_query_version: form.source_query_id && form.query_version_policy === 'pinned'
              ? Number(form.source_query_version) || 1
              : null,
            query_version_policy: form.query_version_policy,
            supplemental_information: form.supplemental_information.trim(),
            research_route: form.research_route,
            execution_profile_id: form.execution_profile_id,
            interaction_mode: form.interaction_mode,
            max_rounds: Number(form.max_rounds) || 2,
            knowledge_enabled: form.knowledge_enabled,
            knowledge_ids: form.knowledge_enabled ? form.knowledge_ids : []
          }
        : {},
      prompt: form.target_type === 'agent_conversation' ? form.prompt.trim() : form.topic.trim(),
      project_id: form.project_id,
      agent_slug: form.target_type === 'agent_conversation' ? form.agent_slug : '',
      cron_expression: buildCronExpression(form),
      model_spec: form.model_spec,
      timezone: form.timezone,
      tool_approval_mode: form.tool_approval_mode
    }
  }
}

function toggleWeekday(day) {
  const selected = new Set(form.weekdays)
  if (selected.has(day)) selected.delete(day)
  else selected.add(day)
  form.weekdays = [...selected].sort((left, right) => left - right)
}

watch(agentValues, (values) => {
  if (form.target_type === 'agent_conversation' && !form.agent_slug && values.length) {
    form.agent_slug = values[0]
  }
})

watch(() => [form.project_id, form.target_type], () => void loadQueries())

watch(daysInSelectedMonth, (days) => {
  if (form.dayOfMonth > days) form.dayOfMonth = days
})

watch(
  () => props.job?.id,
  async (jobId, previousJobId) => {
    if (jobId === previousJobId) return
    hydrating = true
    Object.assign(form, initialForm(props.job))
    await nextTick()
    hydrating = false
    if (previousJobId || !jobId) focusName()
  }
)

watch(
  form,
  () => {
    if (!hydrating) emit('change', changePayload())
  },
  { deep: true }
)

/** 切换频率并保留切换前的结构化 Cron。 */
function changeFrequency(frequency) {
  Object.assign(form, applyFrequencyChange(form, frequency))
}
</script>

<template>
  <section class="inline-editor" aria-label="任务配置">
    <div class="title-line">
      <input
        ref="nameInput"
        v-model="form.name"
        class="name-input"
        maxlength="255"
        aria-label="任务名称"
        placeholder="未命名任务"
      />
      <span class="save-state" :class="saveState">{{ saveLabel }}</span>
    </div>

    <div class="task-type-selector" aria-label="任务类型">
      <button type="button" :class="{ active: form.target_type === 'agent_conversation' }" @click="form.target_type = 'agent_conversation'">
        <b>智能体对话</b><span>周期执行指令并生成独立对话</span>
      </button>
      <button type="button" :class="{ active: form.target_type === 'equipment_research' }" @click="form.target_type = 'equipment_research'">
        <b>装备研究任务</b><span>周期创建并启动独立 Query 研究</span>
      </button>
    </div>

    <label v-if="form.target_type === 'agent_conversation'" class="prompt-field">
      <span class="sr-only">任务指令</span>
      <textarea
        v-model="form.prompt"
        maxlength="32000"
        rows="4"
        placeholder="描述每次触发时智能体需要完成的工作"
      />
    </label>

    <div v-else class="research-fields">
      <label>
        <span>已发布 Query（可选）</span>
        <select v-model="form.source_query_id" :disabled="queryLoading" @change="selectQuery">
          <option value="">直接输入研究主题</option>
          <option v-for="query in queryOptions" :key="query.query_id" :value="query.query_id">
            {{ query.query }}
          </option>
        </select>
      </label>
      <label>
        <span>研究主题</span>
        <textarea v-model="form.topic" maxlength="32000" rows="3" placeholder="明确每次触发需要重新研判的研究问题" />
      </label>
      <label>
        <span>研究补充约束</span>
        <textarea v-model="form.supplemental_information" maxlength="8000" rows="3" placeholder="补充任务边界、重点技术、作战场景和期望输出" />
      </label>
      <p>每次触发都会创建新的研究任务与能力画像，不覆盖历史成果。</p>
    </div>

    <p v-if="error" class="save-error" role="alert">{{ error }}</p>

    <section class="settings-section" aria-labelledby="context-settings-heading">
      <h3 id="context-settings-heading">详情</h3>
      <div class="settings-card">
        <div v-if="form.target_type === 'agent_conversation'" class="setting-row">
          <span>运行于</span>
          <div class="setting-control">
            <ActionDropdown
              v-model:open="agentDropdownOpen"
              v-model:search="agentSearch"
              search-placeholder="搜索智能体"
              :disabled="saving"
            >
              <template #trigger>
                <ActionTrigger
                  :label="selectedAgentLabel"
                  :open="agentDropdownOpen"
                  :disabled="saving"
                  aria-label="执行智能体"
                />
              </template>
              <div role="menu" aria-label="执行智能体">
                <button
                  v-for="agent in filteredAgents"
                  :key="agent.slug || agent.id"
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.agent_slug === (agent.slug || agent.id)"
                  :disabled="saving"
                  class="config-dropdown-item"
                  :class="{ selected: form.agent_slug === (agent.slug || agent.id) }"
                  @click="selectAgent(agent)"
                >
                  <span class="config-dropdown-item-label">{{
                    agent.name || agent.slug || agent.id
                  }}</span>
                  <Check
                    v-if="form.agent_slug === (agent.slug || agent.id)"
                    :size="14"
                    class="config-dropdown-item-check"
                  />
                </button>
                <p v-if="!filteredAgents.length" class="agent-empty" role="status">
                  {{ agentSearch.trim() ? '没有匹配的智能体' : '暂无可用智能体' }}
                </p>
              </div>
            </ActionDropdown>
          </div>
        </div>
        <div class="setting-row">
          <span>Project</span>
          <div class="setting-control">
            <ProjectSelectionSection
              v-model="form.project_id"
              :disabled="saving"
              :allow-auto="false"
              :owner-uid="projectOwnerUid"
              eager-load
              aria-label="任务 Project"
            />
          </div>
        </div>
        <div class="setting-row">
          <span>模型</span>
          <div class="setting-control">
            <ModelSelectorComponent
              :model_spec="form.model_spec"
              clearable
              size="nano"
              display-name="mini"
              placeholder="跟随智能体模型"
              @select-model="(spec) => (form.model_spec = spec)"
            />
          </div>
        </div>
        <div v-if="form.target_type === 'agent_conversation'" class="setting-row">
          <span>工具审批</span>
          <div class="setting-control">
            <ToolApprovalModeSelector v-model="form.tool_approval_mode" />
          </div>
        </div>
        <template v-else>
          <label v-if="form.source_query_id" class="setting-row">
            <span>Query 版本</span>
            <select v-model="form.query_version_policy">
              <option value="latest">每次使用最新已发布版本</option>
              <option value="pinned">固定当前版本 v{{ form.source_query_version || 1 }}</option>
            </select>
          </label>
          <label class="setting-row">
            <span>研究编排</span>
            <select v-model="form.execution_profile_id">
              <option value="winning_swarm_dynamic_v2">动态蜂群 · 多维优选 6 项</option>
              <option value="winning_swarm_v1">标准蜂群研究</option>
            </select>
          </label>
          <label class="setting-row">
            <span>研究轮次</span>
            <select v-model.number="form.max_rounds">
              <option :value="1">1 轮快速复核</option>
              <option :value="2">2 轮平衡研究</option>
              <option :value="3">3 轮深度研究</option>
            </select>
          </label>
        </template>
      </div>
      <p v-if="form.target_type === 'agent_conversation' && form.tool_approval_mode === 'always_trust'" class="trust-warning">
        允许敏感工具无人值守执行，仅用于可信的智能体和 Project。
      </p>
    </section>

    <section class="settings-section" aria-labelledby="schedule-settings-heading">
      <h3 id="schedule-settings-heading">频率</h3>
      <div class="settings-card">
        <fieldset class="setting-row frequency-row">
          <legend class="sr-only">重复频率</legend>
          <div class="frequency-content">
            <span aria-hidden="true">重复</span>
            <div class="frequency-options">
              <label v-for="frequency in scheduleFrequencies" :key="frequency.value">
                <input
                  type="radio"
                  name="schedule-frequency"
                  :value="frequency.value"
                  :checked="form.frequency === frequency.value"
                  @change="changeFrequency(frequency.value)"
                />
                <span>{{ frequency.label }}</span>
              </label>
            </div>
          </div>
        </fieldset>
        <div v-if="form.frequency === 'weekly'" class="setting-row weekday-row">
          <span>执行日</span>
          <div class="weekday-options" aria-label="每周执行日">
            <button
              v-for="weekday in weekdayOptions"
              :key="weekday.value"
              type="button"
              :class="{ selected: form.weekdays.includes(weekday.value) }"
              :aria-pressed="form.weekdays.includes(weekday.value)"
              @click="toggleWeekday(weekday.value)"
            >
              {{ weekday.label }}
            </button>
          </div>
        </div>
        <div v-if="form.frequency === 'yearly'" class="setting-row">
          <span>月份</span>
          <div class="setting-control">
            <select v-model.number="form.month" aria-label="执行月份">
              <option v-for="month in monthOptions" :key="month.value" :value="month.value">
                {{ month.label }}
              </option>
            </select>
          </div>
        </div>
        <div v-if="['monthly', 'yearly'].includes(form.frequency)" class="setting-row">
          <span>日期</span>
          <div class="setting-control">
            <select v-model.number="form.dayOfMonth" aria-label="执行日期">
              <option v-for="day in availableDayOptions" :key="day.value" :value="day.value">
                {{ day.label }}
              </option>
            </select>
          </div>
        </div>
        <label class="setting-row">
          <span>{{ form.frequency === 'custom' ? 'Cron' : '时间' }}</span>
          <input
            v-if="form.frequency === 'custom'"
            v-model="form.cronExpression"
            aria-label="Cron 表达式"
            placeholder="0 9 * * *"
          />
          <input v-else v-model="form.time" type="time" aria-label="执行时间" />
        </label>
      </div>
    </section>
  </section>
</template>

<style lang="less" scoped>
.inline-editor {
  min-width: 0;
  color: var(--gray-1000);
}

.title-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 22px 6px;
}

.name-input {
  min-width: 0;
  padding: 0;
  border: 0;
  outline: 0;
  flex: 1;
  background: transparent;
  color: var(--gray-1000);
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 24px;

  &:focus {
    box-shadow: 0 1px 0 var(--main-color);
  }
}

.save-state {
  color: var(--gray-400);
  font-size: 12px;
  white-space: nowrap;

  &.saving,
  &.dirty {
    color: var(--gray-600);
  }

  &.saved {
    color: var(--color-success-700);
  }

  &.error,
  &.invalid {
    color: var(--color-error-700);
  }
}

.task-type-selector {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 8px 22px 12px;

  button {
    display: grid;
    gap: 3px;
    padding: 10px 12px;
    border: 1px solid var(--gray-150);
    border-radius: 9px;
    background: var(--gray-0);
    color: var(--gray-700);
    text-align: left;
    cursor: pointer;

    &.active {
      border-color: var(--main-color);
      background: color-mix(in srgb, var(--main-color) 7%, var(--gray-0));
      color: var(--gray-1000);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--main-color) 12%, transparent);
    }
  }

  b { font-size: 13px; }
  span { color: var(--gray-500); font-size: 11px; line-height: 16px; }
}

.research-fields {
  display: grid;
  gap: 9px;
  margin: 8px 22px 18px;
  padding: 13px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);

  label { display: grid; gap: 5px; }
  label > span { color: var(--gray-600); font-size: 12px; font-weight: 600; }
  select,
  textarea {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--gray-150);
    border-radius: 7px;
    outline: 0;
    background: var(--gray-0);
    color: var(--gray-900);
    font: inherit;
    font-size: 12px;
  }
  textarea { resize: vertical; line-height: 1.55; }
  :is(select, textarea):focus { border-color: var(--main-color); }
  p { margin: 0; color: var(--gray-500); font-size: 11px; line-height: 17px; }
}

.prompt-field {
  display: block;
  padding: 10px 14px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  margin: 8px 22px 18px;
  background: var(--gray-25);

  textarea {
    width: 100%;
    min-height: 72px;
    padding: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--gray-800);
    font: inherit;
    font-size: 13px;
    line-height: 1.6;
    resize: vertical;

    &:focus {
      box-shadow: none;
    }
  }

  &:focus-within {
    border-color: var(--gray-300);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-color) 8%, transparent);
  }
}

.save-error {
  margin: 0 22px 8px;
  font-size: 12px;
  line-height: 18px;
  color: var(--color-error-700);
}

.trust-warning {
  padding: 0 2px;
  margin: 6px 0 0;
  color: var(--color-warning-800);
  font-size: 12px;
  line-height: 18px;
  text-align: right;
}

.settings-section {
  padding: 0 22px 18px;

  h3 {
    margin: 0 0 6px;
    color: var(--gray-500);
    font-size: 11px;
    font-weight: 500;
  }
}

.settings-card {
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);

  > .setting-row:last-child {
    border-bottom: 0;
  }
}

.setting-row {
  display: grid;
  min-height: 40px;
  margin: 0;
  padding: 5px 14px;
  border-bottom: 1px solid var(--gray-100);
  grid-template-columns: 110px minmax(0, 1fr);
  align-items: center;

  > span {
    color: var(--gray-600);
    font-size: 13px;
  }

  input,
  select {
    width: min(240px, 100%);
    height: 30px;
    padding: 0 8px;
    border: 1px solid transparent;
    border-radius: 5px;
    outline: none;
    background: transparent;
    color: var(--gray-900);
    font: inherit;
    font-size: 13px;
    justify-self: end;
    text-align: right;

    &:hover {
      background: var(--gray-50);
    }

    &:focus {
      border-color: var(--gray-200);
      background: var(--gray-0);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-color) 10%, transparent);
    }
  }

  select {
    cursor: pointer;
    text-align-last: right;
  }

  input[type='time'] {
    width: min(130px, 100%);
  }
}

.frequency-row {
  display: block;

  .frequency-content {
    display: grid;
    min-height: 30px;
    grid-template-columns: 110px minmax(0, 1fr);
    align-items: center;

    > span {
      color: var(--gray-600);
      font-size: 13px;
    }
  }

  min-inline-size: 0;
  border-top: 0;
  border-inline: 0;
}

.frequency-options {
  display: flex;
  justify-content: flex-end;
  gap: 10px;

  label {
    display: inline-flex;
    color: var(--gray-700);
    cursor: pointer;
    font-size: 12px;
    align-items: center;
    gap: 3px;
  }

  input {
    width: auto;
    height: auto;
    padding: 0;
    accent-color: var(--main-color);
  }
}

.setting-control {
  display: flex;
  width: min(240px, 100%);
  min-width: 0;
  justify-self: end;
  justify-content: flex-end;
}

.weekday-options {
  display: flex;
  justify-content: flex-end;
  gap: 4px;

  button {
    width: 28px;
    height: 28px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--gray-500);
    font: inherit;
    font-size: 12px;
    cursor: pointer;

    &:hover {
      background: var(--gray-50);
      color: var(--gray-800);
    }

    &.selected {
      border-color: var(--gray-200);
      background: var(--gray-100);
      color: var(--gray-900);
    }
  }
}

.setting-control :deep(.config-dropdown-trigger) {
  height: 30px;
  max-width: 100%;
  padding: 0 8px;
  border-radius: 5px;
  color: var(--gray-900);
}

.setting-control :deep(.config-dropdown-text),
.setting-control :deep(.config-dropdown-chevron) {
  display: block;
}

.setting-control :deep(.collapse-label) {
  width: auto;
}

.setting-control :deep(.collapse-label .config-dropdown-compact-icon) {
  display: none;
}

.agent-empty {
  margin: 0;
  padding: 16px 12px;
  color: var(--gray-500);
  font-size: 12px;
  text-align: center;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 720px) {
  .title-line,
  .settings-section {
    padding-inline: 14px;
  }

  .prompt-field {
    margin-inline: 14px;
  }

  .save-error {
    margin-inline: 14px;
  }

  .title-line {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .name-input {
    width: 100%;
  }

  .setting-row,
  .frequency-row .frequency-content {
    grid-template-columns: 80px minmax(0, 1fr);
  }

  .weekday-options {
    flex-wrap: wrap;
  }

  .frequency-options {
    flex-wrap: wrap;
  }
}
</style>
