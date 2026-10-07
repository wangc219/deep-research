<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown, CircleAlert, Puzzle, RefreshCw, Search, X } from '@lucide/vue'
import { skillApi } from '@/apis'
import {
  equipmentDeepSkillLimit,
  equipmentDeepSkillSourceLabel,
  filterAccessibleDeepSkills,
  normalizeAccessibleDeepSkills,
  normalizeEquipmentDeepSkillIds,
  reconcileEquipmentDeepSkillIds,
  sameEquipmentDeepSkillIds,
  toggleEquipmentDeepSkillId
} from '@/utils/equipmentDeepSkills.js'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  sessionId: { type: String, default: '' },
  skills: { type: [Array, Object], default: null },
  maxSelected: { type: Number, default: 12 },
  disabled: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  loadOnMount: { type: Boolean, default: true },
  placement: {
    type: String,
    default: 'top',
    validator: (value) => ['top', 'bottom'].includes(value)
  }
})

const emit = defineEmits(['update:modelValue', 'change', 'loaded', 'load-error'])

const root = ref(null)
const searchInput = ref(null)
const open = ref(false)
const query = ref('')
const loading = ref(false)
const loadError = ref('')
const selectionNotice = ref('')
const fetchedSkills = ref([])
const fetchedCatalogReady = ref(false)
const selectedIds = ref([])
let requestSequence = 0

const limit = computed(() => equipmentDeepSkillLimit(props.maxSelected))
const usesProvidedSkills = computed(() => props.skills !== null)
const catalogReady = computed(() => usesProvidedSkills.value || fetchedCatalogReady.value)
const skills = computed(() =>
  normalizeAccessibleDeepSkills(usesProvidedSkills.value ? props.skills : fetchedSkills.value)
)
const filteredSkills = computed(() => filterAccessibleDeepSkills(skills.value, query.value))
const selectedSet = computed(() => new Set(selectedIds.value))
const selectedSkills = computed(() => {
  const byId = new Map(skills.value.map((skill) => [skill.skill_id, skill]))
  return selectedIds.value.map((skillId) =>
    byId.get(skillId) || {
      skill_id: skillId,
      slug: skillId,
      name: skillId,
      description: '',
      source_scope: ''
    }
  )
})
const canEdit = computed(() => !props.disabled && !props.readonly)

const errorMessage = (error) =>
  String(
    error?.response?.data?.detail ||
      error?.data?.detail ||
      error?.message ||
      '读取可访问 Skill 失败，请稍后重试。'
  ).trim()

const emitSelection = (nextSelection, reason) => {
  const next = catalogReady.value
    ? reconcileEquipmentDeepSkillIds(nextSelection, skills.value, limit.value)
    : normalizeEquipmentDeepSkillIds(nextSelection, limit.value)
  selectedIds.value = next
  emit('update:modelValue', [...next])
  emit('change', {
    sessionId: props.sessionId,
    skillIds: [...next],
    reason
  })
}

const syncSelectionFromProps = ({ notifyReconciled = false } = {}) => {
  const incoming = normalizeEquipmentDeepSkillIds(props.modelValue, limit.value)
  const next = catalogReady.value
    ? reconcileEquipmentDeepSkillIds(incoming, skills.value, limit.value)
    : incoming
  selectedIds.value = next

  if (notifyReconciled && !sameEquipmentDeepSkillIds(incoming, next)) {
    emitSelection(next, 'catalog-reconcile')
  }
}

watch(
  [() => props.modelValue, limit],
  () => syncSelectionFromProps(),
  { immediate: true, deep: true, flush: 'sync' }
)

watch(
  [skills, catalogReady],
  ([, ready]) => {
    if (ready) syncSelectionFromProps({ notifyReconciled: true })
  },
  { deep: true, flush: 'sync' }
)

watch(
  () => props.sessionId,
  () => {
    open.value = false
    query.value = ''
    selectionNotice.value = ''
    syncSelectionFromProps()
  },
  { flush: 'sync' }
)

watch(
  () => props.skills,
  (value) => {
    if (value !== null) {
      loadError.value = ''
      loading.value = false
    }
  },
  { deep: true }
)

const loadAccessibleSkills = async () => {
  if (usesProvidedSkills.value) {
    syncSelectionFromProps({ notifyReconciled: true })
    return skills.value
  }

  const sequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  try {
    const response = await skillApi.listAccessibleSkills()
    if (sequence !== requestSequence) return []
    fetchedSkills.value = normalizeAccessibleDeepSkills(response)
    fetchedCatalogReady.value = true
    emit('loaded', {
      sessionId: props.sessionId,
      skills: [...fetchedSkills.value]
    })
    return fetchedSkills.value
  } catch (error) {
    if (sequence !== requestSequence) return []
    loadError.value = errorMessage(error)
    emit('load-error', {
      sessionId: props.sessionId,
      message: loadError.value,
      error
    })
    return []
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

const showPicker = async () => {
  if (props.disabled) return
  open.value = true
  selectionNotice.value = ''
  await nextTick()
  searchInput.value?.focus()
}

const togglePicker = () => {
  if (open.value) {
    open.value = false
    return
  }
  void showPicker()
}

const toggleSkill = (skillId, enabled) => {
  if (!canEdit.value) return
  const result = toggleEquipmentDeepSkillId({
    selected: selectedIds.value,
    skillId,
    enabled,
    skills: skills.value,
    maxSelected: limit.value
  })

  if (result.limited) {
    selectionNotice.value = `每轮最多选择 ${limit.value} 个 Skill。`
    return
  }
  if (result.unavailable) {
    selectionNotice.value = '该 Skill 已不可访问，请刷新目录。'
    return
  }

  selectionNotice.value = ''
  emitSelection(result.selected, enabled ? 'select' : 'remove')
}

const removeSkill = (skillId) => toggleSkill(skillId, false)

const clearSelection = () => {
  if (!canEdit.value || !selectedIds.value.length) return
  selectionNotice.value = ''
  emitSelection([], 'clear')
}

const skillDetails = (skill) =>
  [...skill.triggers, ...skill.tool_dependencies, ...skill.mcp_dependencies].slice(0, 3)

const handleDocumentPointerDown = (event) => {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}

const handleDocumentKeyDown = (event) => {
  if (open.value && event.key === 'Escape') {
    event.preventDefault()
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeyDown)
  if (!usesProvidedSkills.value && props.loadOnMount) void loadAccessibleSkills()
})

onBeforeUnmount(() => {
  requestSequence += 1
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeyDown)
})

defineExpose({
  open: showPicker,
  close: () => {
    open.value = false
  },
  refresh: loadAccessibleSkills
})
</script>

<template>
  <div
    ref="root"
    class="equipment-deep-skill-picker"
    :class="{ open, disabled, readonly }"
    :data-session-id="sessionId || undefined"
  >
    <div class="deep-skill-composer-row">
      <button
        type="button"
        class="deep-skill-trigger"
        :aria-expanded="open"
        aria-haspopup="dialog"
        aria-controls="equipment-deep-skill-popover"
        :disabled="disabled"
        @click="togglePicker"
      >
        <Puzzle :size="13" />
        <span>本轮 Skill</span>
        <em>{{ selectedIds.length }}/{{ limit }}</em>
        <ChevronDown :size="12" aria-hidden="true" />
      </button>

      <div v-if="selectedSkills.length" class="deep-skill-chips" aria-label="本轮启用的 Skill">
        <button
          v-for="skill in selectedSkills"
          :key="skill.skill_id"
          type="button"
          :title="canEdit ? `移除 ${skill.name}` : skill.name"
          :aria-label="canEdit ? `移除 Skill：${skill.name}` : `已启用 Skill：${skill.name}`"
          :disabled="!canEdit"
          @click="removeSkill(skill.skill_id)"
        >
          <b>{{ skill.skill_id }}</b>
          <X v-if="canEdit" :size="10" aria-hidden="true" />
        </button>
      </div>
    </div>

    <Transition name="deep-skill-popover">
      <section
        v-if="open"
        id="equipment-deep-skill-popover"
        class="deep-skill-popover"
        :class="`placement-${placement}`"
        role="dialog"
        aria-label="本轮 Skill 选择"
      >
        <header>
          <div>
            <Puzzle :size="15" />
            <span>
              <b>程序化 Skill</b>
              <small>仅显示当前账号可访问的能力</small>
            </span>
          </div>
          <div class="deep-skill-popover-actions">
            <button
              v-if="!usesProvidedSkills"
              type="button"
              aria-label="刷新 Skill 目录"
              title="刷新目录"
              :disabled="loading"
              @click="loadAccessibleSkills"
            >
              <RefreshCw :size="13" :class="{ spin: loading }" />
            </button>
            <button type="button" aria-label="关闭 Skill 选择" @click="open = false">
              <X :size="14" />
            </button>
          </div>
        </header>

        <label class="deep-skill-search">
          <Search :size="14" />
          <input
            ref="searchInput"
            v-model="query"
            type="search"
            autocomplete="off"
            aria-label="搜索 Skill"
            placeholder="搜索名称、ID、描述或依赖"
          />
          <button v-if="query" type="button" aria-label="清空搜索" @click="query = ''">
            <X :size="12" />
          </button>
        </label>

        <p v-if="loadError" class="deep-skill-error" role="alert">
          <CircleAlert :size="13" />
          <span>{{ loadError }}</span>
          <button v-if="!usesProvidedSkills" type="button" @click="loadAccessibleSkills">重试</button>
        </p>
        <p v-else-if="selectionNotice" class="deep-skill-notice" role="status">
          <CircleAlert :size="13" />{{ selectionNotice }}
        </p>

        <div class="deep-skill-list" aria-live="polite">
          <p v-if="loading && !skills.length" class="deep-skill-empty" role="status">
            <RefreshCw :size="14" class="spin" />读取可访问 Skill…
          </p>
          <article
            v-for="skill in filteredSkills"
            v-else
            :key="skill.skill_id"
            :class="{ selected: selectedSet.has(skill.skill_id) }"
          >
            <label>
              <input
                type="checkbox"
                :checked="selectedSet.has(skill.skill_id)"
                :disabled="!canEdit"
                @change="toggleSkill(skill.skill_id, $event.target.checked)"
              />
              <span class="deep-skill-check" aria-hidden="true">
                <Check :size="11" />
              </span>
              <span class="deep-skill-main">
                <b>{{ skill.name }}</b>
                <small>
                  <code>{{ skill.skill_id }}</code>
                  · {{ equipmentDeepSkillSourceLabel(skill.source_scope) }}
                </small>
              </span>
            </label>
            <p v-if="skill.description">{{ skill.description }}</p>
            <div v-if="skillDetails(skill).length" class="deep-skill-details">
              <span v-for="item in skillDetails(skill)" :key="item">{{ item }}</span>
            </div>
          </article>

          <p v-if="!loading && !filteredSkills.length" class="deep-skill-empty">
            {{ query ? '没有匹配的 Skill。' : '当前账号没有可访问的 Skill。' }}
          </p>
        </div>

        <footer>
          <span>已选择 <b>{{ selectedIds.length }}</b> / {{ limit }}</span>
          <div>
            <button
              v-if="selectedIds.length && canEdit"
              type="button"
              class="deep-skill-clear"
              @click="clearSelection"
            >
              清空
            </button>
            <button type="button" class="deep-skill-done" @click="open = false">完成</button>
          </div>
        </footer>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.equipment-deep-skill-picker {
  position: relative;
  min-width: 0;
  color: var(--color-text);
}

.deep-skill-composer-row {
  display: flex;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

button {
  font: inherit;
}

.deep-skill-trigger {
  display: inline-flex;
  min-height: 28px;
  flex: none;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--color-bg-container);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 10px;
  font-weight: 700;
}

.deep-skill-trigger > svg:first-child,
.equipment-deep-skill-picker.open .deep-skill-trigger {
  color: var(--main-color);
}

.deep-skill-trigger em {
  min-width: 26px;
  padding: 2px 5px;
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-700);
  font-size: 9px;
  font-style: normal;
  text-align: center;
}

.deep-skill-trigger > svg:last-child {
  transition: transform 0.16s ease;
}

.equipment-deep-skill-picker.open .deep-skill-trigger > svg:last-child {
  transform: rotate(180deg);
}

.deep-skill-trigger:hover:not(:disabled),
.deep-skill-trigger:focus-visible {
  border-color: var(--main-300);
  background: var(--main-20);
  outline: none;
}

.deep-skill-trigger:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.deep-skill-chips {
  display: flex;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.deep-skill-chips button {
  display: inline-flex;
  min-width: 0;
  min-height: 23px;
  align-items: center;
  gap: 4px;
  padding: 0 6px 0 8px;
  border: 1px solid var(--main-200);
  border-radius: 999px;
  background: var(--main-30);
  color: var(--main-700);
  cursor: pointer;
}

.deep-skill-chips button:hover:not(:disabled),
.deep-skill-chips button:focus-visible {
  border-color: var(--main-300);
  background: var(--main-50);
  outline: none;
}

.deep-skill-chips button:disabled {
  cursor: default;
}

.deep-skill-chips b {
  min-width: 0;
  font: 9px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-wrap: anywhere;
}

.deep-skill-chips svg {
  flex: none;
  color: var(--color-text-tertiary);
}

.deep-skill-popover {
  position: absolute;
  left: 0;
  z-index: 24;
  display: grid;
  width: min(440px, calc(100vw - 32px));
  max-height: min(520px, 70vh);
  grid-template-rows: auto auto auto minmax(80px, 1fr) auto;
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--color-bg-container);
  box-shadow: 0 16px 42px var(--shadow-3);
}

.deep-skill-popover.placement-top {
  bottom: calc(100% + 8px);
}

.deep-skill-popover.placement-bottom {
  top: calc(100% + 8px);
}

.deep-skill-popover > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 14px 11px;
  border-bottom: 1px solid var(--gray-150);
  background: var(--color-bg-elevated);
}

.deep-skill-popover > header > div:first-child {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 7px;
  color: var(--main-color);
}

.deep-skill-popover > header span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.deep-skill-popover > header b {
  color: var(--color-text);
  font-size: 12px;
}

.deep-skill-popover > header small {
  color: var(--color-text-tertiary);
  font-size: 9px;
}

.deep-skill-popover-actions {
  display: inline-flex;
  gap: 4px;
}

.deep-skill-popover-actions button,
.deep-skill-search button {
  display: inline-flex;
  width: 25px;
  height: 25px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
}

.deep-skill-popover-actions button:hover:not(:disabled),
.deep-skill-search button:hover {
  background: var(--gray-100);
  color: var(--main-color);
}

.deep-skill-search {
  display: flex;
  height: 34px;
  align-items: center;
  gap: 7px;
  margin: 11px 13px 8px;
  padding: 0 8px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--color-bg-elevated);
  color: var(--color-text-tertiary);
}

.deep-skill-search:focus-within {
  border-color: var(--main-300);
  background: var(--color-bg-container);
  box-shadow: 0 0 0 2px var(--main-50);
}

.deep-skill-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: 11px;
}

.deep-skill-search input::placeholder {
  color: var(--color-text-tertiary);
}

.deep-skill-error,
.deep-skill-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 13px 8px;
  padding: 7px 8px;
  border: 1px solid var(--color-error-100);
  border-radius: 7px;
  background: var(--color-error-50);
  color: var(--color-error-700);
  font-size: 9px;
}

.deep-skill-error span {
  min-width: 0;
  flex: 1;
}

.deep-skill-error button {
  flex: none;
  min-height: 24px;
  padding: 0 7px;
  border: 1px solid var(--color-error-100);
  border-radius: 6px;
  background: var(--color-bg-container);
  color: inherit;
  cursor: pointer;
}

.deep-skill-notice {
  border-color: var(--color-warning-100);
  background: var(--color-warning-50);
  color: var(--color-warning-900);
}

.deep-skill-list {
  display: grid;
  min-height: 0;
  align-content: start;
  gap: 7px;
  padding: 2px 13px 11px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.deep-skill-list article {
  padding: 9px 10px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--color-bg-container);
}

.deep-skill-list article.selected {
  border-color: var(--main-300);
  background: var(--main-20);
  box-shadow: inset 3px 0 var(--main-color);
}

.deep-skill-list label {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  align-items: start;
  gap: 6px;
  cursor: pointer;
}

.deep-skill-list input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.deep-skill-check {
  display: inline-flex;
  width: 15px;
  height: 15px;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
  border: 1px solid var(--gray-300);
  border-radius: 4px;
  background: var(--color-bg-container);
  color: transparent;
}

.deep-skill-list input:checked + .deep-skill-check {
  border-color: var(--main-color);
  background: var(--main-color);
  color: var(--main-0);
}

.deep-skill-list input:focus-visible + .deep-skill-check {
  outline: 2px solid var(--main-200);
  outline-offset: 2px;
}

.deep-skill-list input:disabled + .deep-skill-check {
  cursor: not-allowed;
  opacity: 0.5;
}

.deep-skill-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.deep-skill-main b {
  color: var(--color-text);
  font-size: 10.5px;
  overflow-wrap: anywhere;
}

.deep-skill-main small {
  color: var(--color-text-tertiary);
  font-size: 8.5px;
}

.deep-skill-main code {
  color: var(--main-700);
  font: inherit;
}

.deep-skill-list article > p {
  margin: 6px 0 0 38px;
  color: var(--color-text-secondary);
  font-size: 10px;
  line-height: 1.5;
}

.deep-skill-details {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 6px 0 0 38px;
}

.deep-skill-details span {
  padding: 2px 5px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--color-text-tertiary);
  font-size: 8px;
}

.deep-skill-empty {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 10px;
}

.deep-skill-popover > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 13px;
  border-top: 1px solid var(--gray-150);
  background: var(--color-bg-elevated);
  color: var(--color-text-secondary);
  font-size: 10px;
}

.deep-skill-popover > footer > div {
  display: inline-flex;
  gap: 6px;
}

.deep-skill-popover > footer button {
  min-height: 28px;
  padding: 0 11px;
  border: 1px solid var(--gray-200);
  border-radius: 7px;
  cursor: pointer;
  font-size: 10px;
}

.deep-skill-clear {
  background: var(--color-bg-container);
  color: var(--color-text-secondary);
}

.deep-skill-done {
  border-color: var(--main-color) !important;
  background: var(--main-color);
  color: var(--main-0);
}

.spin {
  animation: deep-skill-spin 0.9s linear infinite;
}

.deep-skill-popover-enter-active,
.deep-skill-popover-leave-active {
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
}

.deep-skill-popover-enter-from,
.deep-skill-popover-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@keyframes deep-skill-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 720px) {
  .deep-skill-popover {
    right: 0;
    left: auto;
    width: min(420px, calc(100vw - 24px));
    max-height: min(470px, 66vh);
  }

  .deep-skill-chips {
    max-height: 52px;
    overflow-y: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .deep-skill-trigger > svg:last-child,
  .deep-skill-popover-enter-active,
  .deep-skill-popover-leave-active {
    transition: none;
  }

  .spin {
    animation: none;
  }
}
</style>
