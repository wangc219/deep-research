<template>
  <a-modal
    :open="open"
    title="知识图谱双标与专家仲裁"
    width="1280px"
    :footer="null"
    class="graph-annotation-modal"
    @cancel="close"
  >
    <div class="annotation-toolbar">
      <a-select
        v-model:value="campaignFilter"
        class="campaign-filter"
        allow-clear
        placeholder="全部活动"
        @change="loadAssignments"
      >
        <a-select-option v-for="campaign in campaigns" :key="campaign.campaign_id">
          {{ campaign.name }} · {{ campaign.progress?.completed || 0 }}/{{
            campaign.progress?.total || 0
          }}
        </a-select-option>
      </a-select>
      <span class="toolbar-summary">
        {{ assignments.length }} 个本人任务 · 持久草稿 {{ persistedDraftCount }} · 待提交
        {{ bulkEligibleCount }}
      </span>
      <input
        ref="aiDraftInput"
        type="file"
        accept=".jsonl,application/x-ndjson,application/jsonl"
        multiple
        hidden
        @change="importAiDraftFiles"
      />
      <a-button size="small" :loading="importingAiDrafts" @click="openAiDraftPicker">
        <Upload :size="14" />
        导入本人 AI 候选
      </a-button>
      <a-button
        v-if="selectedCampaign && bulkEligibleCount"
        type="primary"
        size="small"
        :loading="bulkSubmitting"
        @click="confirmBulkSubmit"
      >
        统一提交 {{ bulkEligibleCount }} 篇 revision
      </a-button>
      <a-button
        v-if="selectedCampaign?.status === 'completed' || selectedCampaign?.status === 'sealed'"
        size="small"
        :loading="exporting"
        @click="exportCampaign"
      >
        <Download :size="14" />
        导出 Gold JSON
      </a-button>
      <a-button size="small" :loading="loading" @click="loadWorkspace">
        <RefreshCw :size="14" />
        刷新
      </a-button>
    </div>

    <div v-if="selectedCampaign" class="campaign-progress">
      <div v-for="split in ['train', 'dev', 'test']" :key="split">
        <strong>{{ selectedCampaign.progress?.by_split?.[split] || 0 }}</strong>
        <span>{{ split }}</span>
      </div>
      <a-progress
        :percent="Math.round((selectedCampaign.progress?.completion_rate || 0) * 100)"
        size="small"
      />
    </div>

    <div v-if="errorMessage" class="annotation-error" role="alert">
      <CircleAlert :size="18" />
      <span>{{ errorMessage }}</span>
    </div>

    <a-spin :spinning="loading || assignmentLoading">
      <div v-if="!assignments.length && !errorMessage" class="annotation-empty">
        <BookOpenCheck :size="30" />
        <strong>管理员尚未创建正式活动，或当前账号尚未被分配任务</strong>
        <span>AI 候选可以先导入浏览器内存，但只有正式任务创建后才能逐篇核对和提交。</span>
      </div>

      <div v-else class="annotation-layout">
        <aside class="assignment-list" aria-label="本人标注任务">
          <button
            v-for="item in assignments"
            :key="item.assignment_id"
            type="button"
            class="assignment-item"
            :class="{ active: item.assignment_id === selectedAssignmentId }"
            @click="selectAssignment(item.assignment_id)"
          >
            <span class="assignment-role">{{ roleLabel(item.role) }}</span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.split }} · v{{ item.document_version }} · {{ item.domain }}</small>
            <a-tag :color="statusColor(item.status)">{{ statusLabel(item.status) }}</a-tag>
            <a-tag v-if="item.draft_available" :color="item.draft_submitted ? 'green' : 'gold'">
              {{ item.draft_submitted ? '草稿已提交' : '草稿待提交' }}
            </a-tag>
          </button>
        </aside>

        <main v-if="assignment" class="annotation-main">
          <header class="assignment-header">
            <div>
              <span class="eyebrow">{{ assignment.campaign_name }}</span>
              <h3>{{ assignment.title }}</h3>
              <p>
                {{ assignment.source_type }} · {{ assignment.language }} · {{ assignment.domain }} ·
                文档版本 {{ assignment.document_version }}
              </p>
            </div>
            <div class="header-tags">
              <a-tag color="blue">{{ roleLabel(assignment.role) }}</a-tag>
              <a-tag :color="assignment.both_submitted ? 'green' : 'orange'">
                {{ assignment.both_submitted ? '双份初稿已齐' : '等待独立初稿' }}
              </a-tag>
            </div>
          </header>

          <section class="source-blocks">
            <div class="section-heading">
              <strong>PostgreSQL 权威 Block</strong>
              <span>Span 使用 [start, end)，提交时逐字回切原文</span>
            </div>
            <details v-for="block in assignment.blocks" :key="block.block_id">
              <summary>
                {{ block.block_id }} · 第 {{ block.page || '?' }} 页 ·
                {{ block.heading_path?.join(' / ') || '无标题路径' }}
              </summary>
              <p>{{ block.text }}</p>
            </details>
          </section>

          <section v-if="assignment.difference" class="difference-panel">
            <div class="section-heading">
              <strong>独立标注差异</strong>
              <a-tag :color="assignment.difference.agreement ? 'green' : 'orange'">
                {{
                  assignment.difference.agreement
                    ? '完全一致'
                    : `${assignment.difference.disagreement_count} 项差异`
                }}
              </a-tag>
            </div>
            <div class="difference-grid">
              <span>共同实体 {{ assignment.difference.entities.common_count }}</span>
              <span>左侧独有 {{ assignment.difference.entities.only_left.length }}</span>
              <span>右侧独有 {{ assignment.difference.entities.only_right.length }}</span>
              <span>共同关系 {{ assignment.difference.relations.common_count }}</span>
            </div>
          </section>

          <div v-if="loadedDraftSourceKind === 'ai_prelabel'" class="ai-draft-notice">
            <CircleAlert :size="18" />
            <div>
              <strong>AI 候选草稿已加载</strong>
              <span>
                可直接修改并保存；不要求逐篇点击“已核对”。只有你在最终确认框中点击统一提交，才会生成正式
                revision。
              </span>
            </div>
          </div>

          <a-tabs v-model:active-key="activeEditorTab" class="annotation-editors">
            <a-tab-pane key="entities" :tab="`实体 ${draft.entities.length}`">
              <div class="editor-actions">
                <span>严格 Span、类型与标准实体 ID</span>
                <a-button size="small" @click="addEntity"><Plus :size="14" />新增实体</a-button>
              </div>
              <div v-if="!draft.entities.length" class="editor-empty">尚未添加实体</div>
              <div v-for="(entity, index) in draft.entities" :key="entity.entity_id" class="entity-row">
                <a-select v-model:value="entity.block_id" @change="syncEntityText(entity)">
                  <a-select-option v-for="block in assignment.blocks" :key="block.block_id">
                    {{ block.block_id }}
                  </a-select-option>
                </a-select>
                <a-select v-model:value="entity.type">
                  <a-select-option v-for="type in entityTypes" :key="type.code">
                    {{ type.name_zh }}
                  </a-select-option>
                </a-select>
                <a-input-number v-model:value="entity.start" :min="0" @change="syncEntityText(entity)" />
                <a-input-number v-model:value="entity.end" :min="1" @change="syncEntityText(entity)" />
                <a-input :value="entity.text" readonly placeholder="Span 原文" />
                <a-input v-model:value="entity.canonical_entity_id" placeholder="标准实体 UUID" />
                <a-button type="text" danger @click="draft.entities.splice(index, 1)">
                  <Trash2 :size="15" />
                </a-button>
              </div>
            </a-tab-pane>

            <a-tab-pane key="relations" :tab="`关系 ${draft.relations.length}`">
              <div class="editor-actions">
                <span>端点、方向、证据 Span、级别和适用条件</span>
                <a-button size="small" :disabled="draft.entities.length < 2" @click="addRelation">
                  <Plus :size="14" />新增关系
                </a-button>
              </div>
              <div v-if="!draft.relations.length" class="editor-empty">尚未添加关系</div>
              <article
                v-for="(relation, index) in draft.relations"
                :key="relation.relation_id"
                class="relation-row"
              >
                <div class="relation-grid">
                  <a-select v-model:value="relation.type" placeholder="关系类型">
                    <a-select-option v-for="type in relationTypes" :key="type.code">
                      {{ type.name_zh }}
                    </a-select-option>
                  </a-select>
                  <a-select v-model:value="relation.source_entity_id" placeholder="起点实体">
                    <a-select-option v-for="entity in draft.entities" :key="entity.entity_id">
                      {{ entity.text || entity.entity_id }}
                    </a-select-option>
                  </a-select>
                  <a-select v-model:value="relation.target_entity_id" placeholder="终点实体">
                    <a-select-option v-for="entity in draft.entities" :key="entity.entity_id">
                      {{ entity.text || entity.entity_id }}
                    </a-select-option>
                  </a-select>
                  <a-select v-model:value="relation.claim_level">
                    <a-select-option value="Fact">Fact</a-select-option>
                    <a-select-option value="Inference">Inference</a-select-option>
                    <a-select-option value="Hypothesis">Hypothesis</a-select-option>
                  </a-select>
                  <a-select v-model:value="relation.evidence_block_id" placeholder="证据 Block">
                    <a-select-option v-for="block in assignment.blocks" :key="block.block_id">
                      {{ block.block_id }}
                    </a-select-option>
                  </a-select>
                  <a-input-number v-model:value="relation.evidence_start" :min="0" placeholder="start" />
                  <a-input-number v-model:value="relation.evidence_end" :min="1" placeholder="end" />
                  <a-input
                    v-model:value="relation.applicable_conditions_text"
                    placeholder="适用条件，以逗号分隔"
                  />
                </div>
                <div class="relation-evidence-preview">
                  证据：{{ relationEvidenceText(relation) || '请设置有效证据 Span' }}
                  <a-button type="text" danger @click="draft.relations.splice(index, 1)">
                    <Trash2 :size="15" />
                  </a-button>
                </div>
              </article>
            </a-tab-pane>
          </a-tabs>

          <footer class="submission-footer">
            <span v-if="assignment.role === 'annotator'">
              保存草稿不会生成 revision；另一名标注员提交前看不到你的初稿；单篇或统一提交才会追加不可变
              revision。
            </span>
            <span v-else>仲裁终稿要求所有实体具有 canonical_entity_id，提交后不可覆盖。</span>
            <div class="submission-actions">
              <a-button
                v-if="assignment.role === 'annotator'"
                :loading="savingDraft"
                :disabled="!isDraftDirty && assignment.draft"
                @click="persistCurrentDraft()"
              >
                {{ isDraftDirty ? '保存当前草稿' : '草稿已保存' }}
              </a-button>
              <a-button
                type="primary"
                :loading="submitting"
                :disabled="assignment.role === 'arbitrator' && !assignment.both_submitted"
                @click="submitDraft"
              >
                {{ assignment.role === 'arbitrator' ? '提交专家仲裁终稿' : '提交独立标注 revision' }}
              </a-button>
            </div>
          </footer>
        </main>
      </div>
    </a-spin>
  </a-modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import {
  BookOpenCheck,
  CircleAlert,
  Download,
  Plus,
  RefreshCw,
  Trash2,
  Upload
} from '@lucide/vue'
import { message, Modal } from 'ant-design-vue'
import { graphApi } from '@/apis/graph_api'
import { useUserStore } from '@/stores/user'
import {
  mergeAiDraftMaps,
  parseAiDraftJsonl,
  prepareAiDraftForAssignment
} from '@/utils/annotationDraftImport'

const props = defineProps({
  open: { type: Boolean, default: false },
  kbId: { type: String, required: true }
})
const emit = defineEmits(['update:open', 'submitted'])
const userStore = useUserStore()

const loading = ref(false)
const assignmentLoading = ref(false)
const submitting = ref(false)
const savingDraft = ref(false)
const bulkSubmitting = ref(false)
const exporting = ref(false)
const errorMessage = ref('')
const campaigns = ref([])
const assignments = ref([])
const assignment = ref(null)
const campaignFilter = ref(undefined)
const selectedAssignmentId = ref('')
const activeEditorTab = ref('entities')
const entityTypes = ref([])
const relationTypes = ref([])
const aiDraftInput = ref(null)
const aiDraftsByDocument = ref(new Map())
const aiDraftLoadedDocumentId = ref('')
const importingAiDrafts = ref(false)
const loadedDraftSourceKind = ref('manual')
const loadedDraftProvenance = ref({})
const draftBaseline = ref('')
const draft = reactive({ entities: [], relations: [] })

const selectedCampaign = computed(() =>
  campaigns.value.find((item) => item.campaign_id === campaignFilter.value)
)
const persistedDraftCount = computed(
  () => assignments.value.filter((item) => item.role === 'annotator' && item.draft_available).length
)
const bulkEligibleCount = computed(
  () =>
    assignments.value.filter(
      (item) => item.role === 'annotator' && item.draft_available && !item.draft_submitted
    ).length
)
const isDraftDirty = computed(() => {
  if (!assignment.value || assignment.value.role !== 'annotator') return false
  return JSON.stringify(buildPayload()) !== draftBaseline.value
})

const loadWorkspace = async () => {
  if (!props.open || !props.kbId) return
  loading.value = true
  errorMessage.value = ''
  try {
    const [campaignResponse, ontologyResponse] = await Promise.all([
      graphApi.getAnnotationCampaigns(props.kbId).catch(() => ({ data: { items: [] } })),
      graphApi.getOntology()
    ])
    campaigns.value = campaignResponse?.data?.items || []
    const activeCampaigns = campaigns.value.filter((item) => item.status === 'active')
    if (!campaignFilter.value && activeCampaigns.length === 1) {
      campaignFilter.value = activeCampaigns[0].campaign_id
    }
    entityTypes.value = ontologyResponse?.data?.entity_types || []
    relationTypes.value = ontologyResponse?.data?.relation_types || []
    await loadAssignments()
  } catch (error) {
    console.error('Failed to load annotation workspace:', error)
    errorMessage.value = error?.message || '双标工作台加载失败'
  } finally {
    loading.value = false
  }
}

const loadAssignments = async () => {
  if (!props.open || !props.kbId) return
  try {
    const response = await graphApi.getMyAnnotationAssignments(
      props.kbId,
      campaignFilter.value || ''
    )
    assignments.value = response?.data?.items || []
    const stillSelected = assignments.value.some(
      (item) => item.assignment_id === selectedAssignmentId.value
    )
    if (!stillSelected) selectedAssignmentId.value = assignments.value[0]?.assignment_id || ''
    if (selectedAssignmentId.value) await loadAssignment()
    else assignment.value = null
  } catch (error) {
    console.error('Failed to load annotation assignments:', error)
    assignments.value = []
    assignment.value = null
    errorMessage.value = error?.message || '本人标注任务加载失败'
  }
}

const selectAssignment = async (assignmentId) => {
  if (assignment.value?.role === 'annotator' && isDraftDirty.value) {
    const saved = await persistCurrentDraft({ showMessage: false })
    if (!saved) return
  }
  selectedAssignmentId.value = assignmentId
  await loadAssignment()
}

const loadAssignment = async () => {
  if (!selectedAssignmentId.value) return
  assignmentLoading.value = true
  errorMessage.value = ''
  try {
    const response = await graphApi.getAnnotationAssignment(
      props.kbId,
      selectedAssignmentId.value
    )
    assignment.value = response?.data || null
    hydrateAssignmentDraft(assignment.value)
  } catch (error) {
    console.error('Failed to load annotation assignment:', error)
    assignment.value = null
    errorMessage.value = error?.message || '标注任务加载失败'
  } finally {
    assignmentLoading.value = false
  }
}

const preferredPayload = (item) => {
  if (!item?.submissions?.length) return null
  if (item.role === 'arbitrator') return item.submissions[0]?.annotation_payload || null
  return item.submissions[item.submissions.length - 1]?.annotation_payload || null
}

const hydrateAssignmentDraft = (item) => {
  aiDraftLoadedDocumentId.value = ''
  if (item?.draft?.annotation_payload) {
    loadedDraftSourceKind.value = item.draft.source_kind || 'manual'
    loadedDraftProvenance.value = item.draft.provenance || {}
    hydrateDraft(item.draft.annotation_payload)
    return
  }
  const submittedPayload = preferredPayload(item)
  if (submittedPayload) {
    loadedDraftSourceKind.value = 'manual'
    loadedDraftProvenance.value = {}
    hydrateDraft(submittedPayload)
    return
  }
  const importedDraft = aiDraftsByDocument.value.get(item?.document_id)
  if (!importedDraft) {
    loadedDraftSourceKind.value = 'manual'
    loadedDraftProvenance.value = {}
    hydrateDraft(null)
    return
  }
  try {
    const candidate = prepareAiDraftForAssignment(importedDraft, item, userStore.uid)
    hydrateDraft(candidate)
    aiDraftLoadedDocumentId.value = item.document_id
    loadedDraftSourceKind.value = 'ai_prelabel'
    loadedDraftProvenance.value = importedDraft.draft_provenance || {}
  } catch (error) {
    hydrateDraft(null)
    errorMessage.value = error?.message || 'AI 候选与当前任务不匹配'
  }
}

const openAiDraftPicker = () => {
  if (!aiDraftInput.value || importingAiDrafts.value) return
  aiDraftInput.value.value = ''
  aiDraftInput.value.click()
}

const importAiDraftFiles = async (event) => {
  const files = [...(event.target?.files || [])]
  if (!files.length || importingAiDrafts.value) return
  importingAiDrafts.value = true
  errorMessage.value = ''
  try {
    let imported = new Map()
    for (const file of files) {
      imported = mergeAiDraftMaps(imported, parseAiDraftJsonl(await file.text()))
    }
    aiDraftsByDocument.value = imported
    aiDraftLoadedDocumentId.value = ''
    if (assignment.value) hydrateAssignmentDraft(assignment.value)
    message.success(`已在浏览器内存中导入 ${imported.size} 篇本人 AI 候选，未提交任何 revision`)
  } catch (error) {
    console.error('Failed to import AI annotation drafts:', error)
    aiDraftsByDocument.value = new Map()
    aiDraftLoadedDocumentId.value = ''
    if (assignment.value) hydrateAssignmentDraft(assignment.value)
    errorMessage.value = error?.message || 'AI 候选导入失败'
  } finally {
    importingAiDrafts.value = false
  }
}

const hydrateDraft = (payload) => {
  draft.entities.splice(0)
  draft.relations.splice(0)
  for (const entity of payload?.entities || []) draft.entities.push({ ...entity })
  for (const relation of payload?.relations || []) {
    const span = relation.evidence_spans?.[0]
    draft.relations.push({
      ...relation,
      evidence_block_id: span?.block_id || relation.evidence_block_ids?.[0] || '',
      evidence_start: span?.start ?? 0,
      evidence_end: span?.end ?? 1,
      applicable_conditions_text: (relation.applicable_conditions || []).join(', ')
    })
  }
  draftBaseline.value = assignment.value ? JSON.stringify(buildPayload()) : ''
}

const addEntity = () => {
  const block = assignment.value?.blocks?.[0]
  draft.entities.push({
    entity_id: `e-${crypto.randomUUID()}`,
    block_id: block?.block_id || '',
    type: entityTypes.value[0]?.code || 'KeyTechnology',
    text: '',
    start: 0,
    end: 1,
    canonical_entity_id: ''
  })
  syncEntityText(draft.entities[draft.entities.length - 1])
}

const addRelation = () => {
  const block = assignment.value?.blocks?.[0]
  draft.relations.push({
    relation_id: `r-${crypto.randomUUID()}`,
    type: relationTypes.value[0]?.code || 'BASED_ON',
    source_entity_id: draft.entities[0]?.entity_id || '',
    target_entity_id: draft.entities[1]?.entity_id || '',
    claim_level: 'Fact',
    evidence_block_id: block?.block_id || '',
    evidence_start: 0,
    evidence_end: 1,
    applicable_conditions_text: ''
  })
}

const blockById = (blockId) => assignment.value?.blocks?.find((block) => block.block_id === blockId)

const syncEntityText = (entity) => {
  const text = blockById(entity.block_id)?.text || ''
  entity.text = text.slice(Number(entity.start || 0), Number(entity.end || 0))
}

const relationEvidenceText = (relation) => {
  const text = blockById(relation.evidence_block_id)?.text || ''
  return text.slice(Number(relation.evidence_start || 0), Number(relation.evidence_end || 0))
}

const buildPayload = () => ({
  document_id: assignment.value.document_id,
  title: assignment.value.title,
  split: assignment.value.split,
  language: assignment.value.language,
  source_type: assignment.value.source_type,
  domain: assignment.value.domain,
  source_version: String(assignment.value.document_version),
  blocks: assignment.value.blocks.map(({ block_id, text, page }) => ({ block_id, text, page })),
  entities: draft.entities.map((entity) => ({
    entity_id: entity.entity_id,
    block_id: entity.block_id,
    type: entity.type,
    text: entity.text,
    start: Number(entity.start),
    end: Number(entity.end),
    canonical_entity_id: entity.canonical_entity_id || null
  })),
  relations: draft.relations.map((relation) => {
    const evidenceText = relationEvidenceText(relation)
    return {
      relation_id: relation.relation_id,
      type: relation.type,
      source_entity_id: relation.source_entity_id,
      target_entity_id: relation.target_entity_id,
      evidence_block_ids: relation.evidence_block_id ? [relation.evidence_block_id] : [],
      evidence_spans: evidenceText
        ? [
            {
              block_id: relation.evidence_block_id,
              start: Number(relation.evidence_start),
              end: Number(relation.evidence_end),
              text: evidenceText
            }
          ]
        : [],
      applicable_conditions: String(relation.applicable_conditions_text || '')
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
      claim_level: relation.claim_level
    }
  })
})

const persistCurrentDraft = async ({ showMessage = true } = {}) => {
  if (!assignment.value || assignment.value.role !== 'annotator' || savingDraft.value) return false
  savingDraft.value = true
  try {
    const response = await graphApi.saveAnnotationDraft(
      props.kbId,
      assignment.value.assignment_id,
      buildPayload(),
      {
        source_kind: loadedDraftSourceKind.value,
        provenance: loadedDraftProvenance.value
      }
    )
    const saved = response?.data
    assignment.value.draft = saved
    const summary = assignments.value.find(
      (item) => item.assignment_id === assignment.value.assignment_id
    )
    if (summary) {
      summary.draft_available = true
      summary.draft_submitted = Boolean(saved?.submitted)
      summary.draft_updated_at = saved?.updated_at || null
    }
    draftBaseline.value = JSON.stringify(buildPayload())
    if (showMessage) message.success('当前草稿已保存，尚未生成 revision')
    return true
  } catch (error) {
    console.error('Failed to save annotation draft:', error)
    message.error(error?.message || '草稿保存失败')
    return false
  } finally {
    savingDraft.value = false
  }
}

const confirmBulkSubmit = async () => {
  if (!selectedCampaign.value || bulkSubmitting.value) return
  if (assignment.value?.role === 'annotator' && isDraftDirty.value) {
    const saved = await persistCurrentDraft({ showMessage: false })
    if (!saved) return
  }
  const expectedCount = bulkEligibleCount.value
  if (!expectedCount) {
    message.info('当前活动没有待提交草稿')
    return
  }
  Modal.confirm({
    title: `统一提交 ${expectedCount} 篇独立标注 revision？`,
    content:
      '这次确认将覆盖所列全部持久草稿，不设置逐篇“已核对”门槛。每篇都会写入不可变正式 revision；重复点击时内容未变化的草稿不会再次提交。',
    okText: '确认统一提交',
    cancelText: '继续审核',
    okType: 'primary',
    async onOk() {
      bulkSubmitting.value = true
      try {
        const response = await graphApi.bulkSubmitAnnotations(
          props.kbId,
          selectedCampaign.value.campaign_id,
          expectedCount
        )
        const result = response?.data || {}
        message.success(`已统一提交 ${result.submitted_count || 0} 篇独立标注 revision`)
        emit('submitted')
        await loadWorkspace()
      } catch (error) {
        console.error('Failed to bulk submit annotations:', error)
        message.error(error?.message || '统一提交失败')
        throw error
      } finally {
        bulkSubmitting.value = false
      }
    }
  })
}

const submitDraft = async () => {
  if (!assignment.value || submitting.value) return
  submitting.value = true
  try {
    const payload = buildPayload()
    if (assignment.value.role === 'arbitrator') {
      await graphApi.adjudicateAnnotation(props.kbId, assignment.value.assignment_id, payload)
      message.success('专家仲裁终稿已保存')
    } else {
      await graphApi.submitAnnotation(props.kbId, assignment.value.assignment_id, payload)
      message.success('独立标注 revision 已追加')
    }
    aiDraftLoadedDocumentId.value = ''
    emit('submitted')
    await loadWorkspace()
  } catch (error) {
    console.error('Failed to submit annotation:', error)
    message.error(error?.message || '标注提交失败')
  } finally {
    submitting.value = false
  }
}

const exportCampaign = async () => {
  if (!selectedCampaign.value || exporting.value) return
  exporting.value = true
  try {
    const response = await graphApi.exportAnnotationCampaign(
      props.kbId,
      selectedCampaign.value.campaign_id
    )
    const payload = response?.data
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selectedCampaign.value.campaign_id}-gold.json`
    link.click()
    URL.revokeObjectURL(url)
    message.success(`已导出 ${payload?.document_count || 0} 篇金标`)
  } catch (error) {
    console.error('Failed to export annotation campaign:', error)
    message.error(error?.message || '金标导出失败')
  } finally {
    exporting.value = false
  }
}

const roleLabel = (role) => (role === 'arbitrator' ? '仲裁专家' : '独立标注员')
const statusLabel = (status) =>
  ({
    assigned: '待标注',
    annotating: '标注中',
    awaiting_adjudication: '待仲裁',
    adjudicating: '仲裁中',
    completed: '已完成'
  })[status] || status
const statusColor = (status) =>
  ({
    assigned: 'default',
    annotating: 'blue',
    awaiting_adjudication: 'orange',
    adjudicating: 'purple',
    completed: 'green'
  })[status] || 'default'

const close = () => emit('update:open', false)

watch(
  () => [props.open, props.kbId],
  ([isOpen]) => {
    if (isOpen) loadWorkspace()
  }
)

watch(
  () => userStore.uid,
  () => {
    aiDraftsByDocument.value = new Map()
    aiDraftLoadedDocumentId.value = ''
  }
)
</script>

<style scoped>
.annotation-toolbar,
.assignment-header,
.section-heading,
.editor-actions,
.submission-footer,
.relation-evidence-preview {
  display: flex;
  align-items: center;
  gap: 10px;
}

.annotation-toolbar {
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.campaign-filter {
  width: 300px;
}

.toolbar-summary {
  flex: 1;
  color: var(--gray-500);
  font-size: 13px;
}

.campaign-progress {
  display: grid;
  grid-template-columns: repeat(3, 70px) minmax(180px, 1fr);
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-50);
}

.campaign-progress > div {
  display: flex;
  gap: 5px;
  align-items: baseline;
}

.campaign-progress span {
  color: var(--gray-500);
  font-size: 11px;
}

.annotation-error,
.annotation-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 180px;
  color: var(--gray-600);
}

.annotation-error {
  min-height: auto;
  margin-bottom: 12px;
  padding: 10px;
  border-radius: 8px;
  background: var(--color-error-50);
  color: var(--color-error-700);
}

.annotation-empty {
  flex-direction: column;
}

.annotation-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  height: min(72vh, 760px);
  min-height: 0;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  overflow: hidden;
}

.assignment-list {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border-right: 1px solid var(--gray-200);
  background: var(--gray-50);
}

.assignment-item {
  display: grid;
  width: 100%;
  gap: 6px;
  padding: 14px;
  border: 0;
  border-bottom: 1px solid var(--gray-200);
  background: transparent;
  color: var(--gray-800);
  text-align: left;
  cursor: pointer;
}

.assignment-item.active {
  background: var(--main-10);
  box-shadow: inset 3px 0 var(--main-color);
}

.assignment-role,
.eyebrow {
  color: var(--main-color);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.assignment-item small,
.assignment-header p,
.section-heading span,
.submission-footer span {
  color: var(--gray-500);
  font-size: 12px;
}

.annotation-main {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 18px;
}

.assignment-header {
  justify-content: space-between;
}

.assignment-header h3,
.assignment-header p {
  margin: 4px 0 0;
}

.header-tags {
  display: flex;
  gap: 6px;
}

.source-blocks,
.difference-panel {
  margin-top: 16px;
  padding: 12px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
}

.section-heading,
.editor-actions,
.submission-footer {
  justify-content: space-between;
}

.source-blocks details {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--gray-150);
}

.source-blocks summary {
  color: var(--gray-600);
  font-size: 12px;
  cursor: pointer;
}

.source-blocks p {
  white-space: pre-wrap;
  line-height: 1.7;
}

.difference-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-top: 10px;
}

.difference-grid span {
  padding: 8px;
  border-radius: 6px;
  background: var(--gray-50);
  font-size: 12px;
}

.ai-draft-notice {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--color-warning-100);
  border-radius: 8px;
  background: var(--color-warning-50);
  color: var(--color-warning-900);
}

.ai-draft-notice > div {
  display: grid;
  gap: 3px;
}

.ai-draft-notice span {
  font-size: 12px;
}

.annotation-editors {
  margin-top: 10px;
}

.editor-empty {
  padding: 24px;
  color: var(--gray-500);
  text-align: center;
}

.entity-row {
  display: grid;
  grid-template-columns: 120px 140px 76px 76px minmax(130px, 1fr) minmax(150px, 1fr) 34px;
  gap: 8px;
  margin-top: 10px;
}

.relation-row {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}

.relation-grid {
  display: grid;
  grid-template-columns: 180px 1fr 1fr 130px;
  gap: 8px;
}

.relation-evidence-preview {
  justify-content: space-between;
  margin-top: 8px;
  color: var(--gray-500);
  font-size: 12px;
}

.submission-footer {
  position: sticky;
  bottom: -18px;
  margin: 18px -18px -18px;
  padding: 14px 18px;
  border-top: 1px solid var(--gray-200);
  background: var(--gray-0);
}

.submission-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 900px) {
  .annotation-layout {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(120px, 180px) minmax(0, 1fr);
    height: min(78vh, 720px);
  }

  .assignment-list {
    display: flex;
    max-height: none;
    border-right: 0;
    border-bottom: 1px solid var(--gray-200);
    overflow-x: auto;
  }

  .assignment-item {
    min-width: 230px;
  }

  .entity-row,
  .relation-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
