<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Bot, CheckCircle2, ChevronDown, CircleAlert, FileText, RefreshCw, Save, Wrench } from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'

const props = defineProps({
  modelValue: { type: Object, required: true },
  creating: Boolean
})
const emit = defineEmits(['update:modelValue', 'save-draft'])
const update = (key, value) => emit('update:modelValue', { ...props.modelValue, [key]: value })
const catalog = ref(null)
const loading = ref(false)
const error = ref('')
const advancedOpen = ref(true)
const preview = ref(null)
const previewLoading = ref(false)
const previewError = ref('')
let previewSequence = 0
const defaultAgentIds = computed(() => props.modelValue.execution_profile_id === 'legacy_v1' ? [] : preview.value?.selected_agent_ids || [])
const manualAgentIds = computed(() => props.modelValue.selected_agent_ids.filter((id) => !defaultAgentIds.value.includes(id)))
const planById = computed(() => new Map((preview.value?.plan || []).map((item) => [item.agent_id, item])))
const selectedBranch = computed(() => catalog.value?.discovery_branches.find((item) => item.id === props.modelValue.discovery_branch))
const roundOptions = computed(() => props.modelValue.execution_profile_id === 'legacy_v1' ? [1, 2, 3, 4, 5] : [1, 2, 3])
const summary = computed(() => [
  catalog.value?.interaction_modes.find((item) => item.id === props.modelValue.interaction_mode)?.name,
  selectedBranch.value ? `${selectedBranch.value.id} · ${selectedBranch.value.name}` : '自动分支',
  `${props.modelValue.max_rounds} 轮`,
  manualAgentIds.value.length ? `人工${props.modelValue.execution_profile_id === 'legacy_v1' ? '选择' : '追加'} ${manualAgentIds.value.length} 个 Agent` : '系统自动选择 Agent'
].filter(Boolean).join(' · '))
const toggleAgent = (id) => {
  if (defaultAgentIds.value.includes(id)) return
  const selected = props.modelValue.selected_agent_ids
  update('selected_agent_ids', selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id])
}
const loadCatalog = async () => {
  loading.value = true
  error.value = ''
  try { catalog.value = await equipmentApi.getResearchCatalog() }
  catch (err) { error.value = err.message || '运行配置加载失败' }
  finally { loading.value = false }
}
watch(() => [props.modelValue.topic, props.modelValue.supplemental_information, props.modelValue.research_route, props.modelValue.interaction_mode, props.modelValue.discovery_branch], (_, __, onCleanup) => {
  const sequence = ++previewSequence
  preview.value = null
  previewError.value = ''
  previewLoading.value = false
  if (!props.modelValue.topic.trim()) return
  previewLoading.value = true
  const timer = window.setTimeout(async () => {
    try {
      const result = await equipmentApi.previewResearchAgents({
        topic: props.modelValue.topic.trim(),
        supplemental_information: props.modelValue.supplemental_information.trim(),
        research_route: props.modelValue.research_route,
        interaction_mode: props.modelValue.interaction_mode,
        discovery_branch: props.modelValue.discovery_branch
      })
      if (sequence === previewSequence) preview.value = result
    } catch (err) {
      if (sequence === previewSequence) previewError.value = err.message || 'Agent 预览暂不可用'
    } finally {
      if (sequence === previewSequence) previewLoading.value = false
    }
  }, 280)
  onCleanup(() => window.clearTimeout(timer))
}, { immediate: true })
watch(() => props.modelValue.execution_profile_id, () => {
  if (props.modelValue.max_rounds > roundOptions.value.at(-1)) update('max_rounds', roundOptions.value.at(-1))
})
onMounted(loadCatalog)
onBeforeUnmount(() => { previewSequence += 1 })
</script>

<template>
  <section class="run-config-panel" aria-label="研究运行配置">
    <header class="run-config-heading"><Wrench :size="17" /><span><b>研究运行配置</b><small>配置随本次任务保存，收起面板后仍然生效</small></span></header>
    <p v-if="loading" role="status"><RefreshCw :size="14" class="spin" />正在读取运行配置…</p>
    <div v-else-if="error" class="run-config-error" role="alert"><CircleAlert :size="15" />{{ error }}<button type="button" @click="loadCatalog">重新加载</button></div>
    <template v-else-if="catalog">
      <section class="run-report-templates" aria-label="报告模板">
        <h3>报告模板 <small>任务启动后固定结构</small></h3>
        <div><button v-for="item in catalog.report_templates" :key="item.id" type="button" :aria-pressed="modelValue.report_template_mode === item.id" :class="{ selected: modelValue.report_template_mode === item.id }" @click="update('report_template_mode', item.id)"><span><FileText :size="15" /><b>{{ item.name }}</b><em v-if="item.default">推荐</em><CheckCircle2 v-if="modelValue.report_template_mode === item.id" :size="16" /></span><small>{{ item.description }}</small></button></div>
      </section>
      <button type="button" class="run-advanced-toggle" :aria-expanded="advancedOpen" aria-controls="run-advanced-options" @click="advancedOpen = !advancedOpen"><Wrench :size="15" /><span><b>{{ advancedOpen ? '收起高级编排选项' : '高级编排选项' }}</b><small>{{ summary }}</small></span><ChevronDown :size="16" :class="{ expanded: advancedOpen }" /></button>
      <div v-show="advancedOpen" id="run-advanced-options">
        <div class="run-config-fields">
          <label><span>交互模式</span><select :value="modelValue.interaction_mode" @change="update('interaction_mode', $event.target.value)"><option v-for="item in catalog.interaction_modes" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <label><span>A–H 发现分支</span><select :value="modelValue.discovery_branch" @change="update('discovery_branch', $event.target.value)"><option value="auto">Agent 自动选择</option><option v-for="item in catalog.discovery_branches" :key="item.id" :value="item.id">{{ item.id }} · {{ item.name }}</option></select></label>
          <label><span>研究路线</span><select :value="modelValue.research_route" @change="update('research_route', $event.target.value)"><option value="auto">按发现分支自动映射</option><option v-for="item in catalog.routes" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <label><span>最大研究轮次</span><select :value="modelValue.max_rounds" @change="update('max_rounds', Number($event.target.value))"><option v-for="round in roundOptions" :key="round" :value="round">{{ round }} 轮{{ round === 2 ? '（推荐）' : '' }}</option></select></label>
        </div>
        <p v-if="selectedBranch" class="run-config-note">{{ selectedBranch.id }} · {{ selectedBranch.name }}：{{ catalog.routes.find(item => item.id === selectedBranch.runtime_route)?.name }}<span class="run-step-modes"><span v-for="step in selectedBranch.step_modes" :key="step.step">S{{ step.step }} · {{ ({ deep: '深入', standard: '标准', light: '弱化', skip: '跳过', dynamic: '动态' })[step.execution_mode] || step.execution_mode }}</span></span></p>
        <p v-if="preview?.structured_query_brief?.supplement_present" class="run-config-note">主控 Agent 结构化简报：{{ preview.structured_query_brief.supplement_summary }}</p>
        <section class="run-agent-section" aria-label="业务 Agent">
          <h3>业务 Agent <small>{{ defaultAgentIds.length ? `默认 ${defaultAgentIds.length} + 追加 ${manualAgentIds.length}` : `人工选择 ${manualAgentIds.length}` }}</small></h3>
          <p>研究模式：{{ modelValue.execution_profile_id === 'legacy_v1' ? '传统固定编排，可人工选择角色；未选时由系统补足。' : '保留系统默认角色，可勾选其他角色作为人工追加。' }}</p>
          <p v-if="previewLoading" role="status"><RefreshCw :size="14" class="spin" />正在分析默认 Agent…</p>
          <p v-else-if="previewError" role="alert" class="run-config-error">{{ previewError }}；启动时仍由系统选择默认角色。</p>
          <p v-else-if="!modelValue.topic.trim()">输入研究问题后，将自动预览默认 Agent。</p>
          <p v-else-if="preview" class="run-agent-preview">{{ preview.primary_branch }} · {{ preview.branch_name }} · {{ preview.plan.map(item => item.display_name).join('、') }}</p>
          <div class="run-agent-grid"><label v-for="agent in catalog.agents" :key="agent.agent_id" :class="{ selected: defaultAgentIds.includes(agent.agent_id) || modelValue.selected_agent_ids.includes(agent.agent_id) }"><input type="checkbox" :checked="defaultAgentIds.includes(agent.agent_id) || modelValue.selected_agent_ids.includes(agent.agent_id)" :disabled="defaultAgentIds.includes(agent.agent_id)" @change="toggleAgent(agent.agent_id)"><Bot :size="17" /><span><b>{{ agent.display_name }}<em v-if="defaultAgentIds.includes(agent.agent_id)">系统默认</em><em v-else-if="modelValue.selected_agent_ids.includes(agent.agent_id)">{{ modelValue.execution_profile_id === 'legacy_v1' ? '人工选择' : '人工追加' }}</em></b><small>{{ agent.description }}</small><small v-if="planById.get(agent.agent_id)">{{ planById.get(agent.agent_id).reason }}</small></span></label></div>
        </section>
      </div>
    </template>
    <footer class="run-config-actions"><label><input type="checkbox" :checked="modelValue.start" @change="update('start', $event.target.checked)">创建后立即排队</label><button type="button" :disabled="creating || !modelValue.topic.trim()" @click="emit('save-draft')"><Save :size="14" />保存草稿</button></footer>
  </section>
</template>

<style scoped>
.run-config-panel{display:grid;gap:16px;margin-top:14px;color:var(--color-text,#33415c);text-align:left;font-size:12px;min-width:0}
.run-config-heading{display:flex;align-items:center;gap:9px}.run-config-heading span{display:grid;gap:4px}.run-config-heading small,.run-config-panel h3 small,.run-config-panel p,.run-report-templates small,.run-agent-grid small{color:var(--color-text-secondary,#778297)}
.run-config-panel h3{margin:0 0 10px;font-size:13px}.run-config-panel h3 small{margin-left:8px;font-weight:400;font-size:11px}.run-config-panel p{margin:0;line-height:1.7}.run-config-panel button{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border-color,#dfe4f2);border-radius:9px;background:var(--color-bg-container,#fff);color:inherit;cursor:pointer;font:inherit;padding:9px 12px}.run-config-panel button:disabled{cursor:default;opacity:.5}.run-report-templates>div,.run-config-fields,.run-agent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.run-report-templates button{display:grid;text-align:left;gap:7px}.run-report-templates button>span{display:flex;align-items:center;gap:6px}.run-report-templates button>span>svg:last-child{margin-left:auto}.run-config-panel em{font-style:normal;font-size:10px;color:#655de6;margin-left:5px}.run-report-templates small{line-height:1.6}.run-report-templates .selected,.run-agent-grid .selected{border-color:#a29bf0;background:var(--main-50,#f5f4ff)}.run-advanced-toggle{width:100%;text-align:left}.run-advanced-toggle>span{display:grid;gap:5px;flex:1}.run-advanced-toggle small{color:var(--color-text-secondary,#778297);line-height:1.6}.run-advanced-toggle .expanded{transform:rotate(180deg)}.run-config-fields{margin-bottom:14px}.run-config-fields label{display:grid;gap:6px;font-size:11px}.run-config-fields select{width:100%;min-width:0;height:36px;padding:0 9px;border:1px solid var(--border-color,#dfe4f2);border-radius:8px;background:var(--color-bg-container,#fff);color:inherit;font:inherit}.run-step-modes{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.run-step-modes span{padding:2px 6px;border-radius:5px;background:var(--color-bg-container,#f1f3fa)}.run-config-note{margin-bottom:14px!important}.run-agent-section>p{margin-bottom:10px}.run-agent-grid label{display:flex;align-items:flex-start;gap:7px;padding:11px;border:1px solid var(--border-color,#e1e5ee);border-radius:9px}.run-agent-grid input{margin-top:3px}.run-agent-grid svg{flex:none;margin-top:2px}.run-agent-grid label>span{display:grid;gap:5px;min-width:0}.run-agent-grid small{font-size:11px;line-height:1.6;overflow-wrap:anywhere}.run-config-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid var(--border-color,#e1e5ee);padding-top:12px}.run-config-actions>label{display:flex;gap:6px;align-items:center}.run-config-error{color:#b64d59!important;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
@media(max-width:600px){.run-report-templates>div,.run-agent-grid{grid-template-columns:1fr}.run-config-panel h3 small{display:block;margin:5px 0 0}}
:global(html.dark) .run-config-panel{color:#e4e8f2}:global(html.dark) .run-config-panel button,:global(html.dark) .run-config-fields select,:global(html.dark) .run-agent-grid label{background:#141925;border-color:#343b4d}:global(html.dark) .run-report-templates .selected,:global(html.dark) .run-agent-grid .selected{background:#292b55;border-color:#766cce}
</style>
