<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Archive,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Pencil,
  RefreshCw,
  RotateCcw,
  Trash2,
  X
} from '@lucide/vue'
import {
  buildDeepSessionGroups,
  deepSessionStatus,
  deepSessionStatusLabel,
  formatDeepSessionTime,
  normalizeDeepSessions,
  splitDeepQueryDisplay
} from '@/utils/equipmentDeepSessions.js'

const props = defineProps({
  sessions: { type: [Array, Object], default: () => [] },
  runs: { type: Array, default: () => [] },
  currentRunId: { type: String, default: '' },
  selectedSessionId: { type: String, default: '' },
  pendingSessionId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  busySessionId: { type: String, default: '' }
})

const emit = defineEmits(['select', 'rename', 'archive', 'restore', 'delete'])

const showArchivedSessions = ref(false)
const collapsedGroups = ref({})
const renamingSessionId = ref('')
const renameDraft = ref('')
const deleteConfirmSessionId = ref('')
const localError = ref('')
const renameInput = ref(null)
const historyScroll = ref(null)
const sessionRowRefs = new Map()

const allSessions = computed(() => normalizeDeepSessions(props.sessions))
const currentSessions = computed(() =>
  allSessions.value.filter((item) => deepSessionStatus(item) !== 'archived')
)
const archivedSessions = computed(() =>
  allSessions.value.filter((item) => deepSessionStatus(item) === 'archived')
)
const visibleGroups = computed(() =>
  buildDeepSessionGroups({
    sessions: allSessions.value,
    runs: props.runs,
    currentRunId: props.currentRunId,
    archived: showArchivedSessions.value
  })
)
const visibleSessionCount = computed(() =>
  visibleGroups.value.reduce((total, group) => total + group.sessions.length, 0)
)

watch(
  visibleGroups,
  (groups) => {
    const next = { ...collapsedGroups.value }
    for (const group of groups) {
      if (!(group.group_key in next)) next[group.group_key] = !group.is_current
      if (group.is_current) next[group.group_key] = false
    }
    collapsedGroups.value = next
  },
  { immediate: true }
)

watch(
  [() => props.selectedSessionId, () => props.pendingSessionId, allSessions],
  ([selectedId, pendingId]) => {
    const id = pendingId || selectedId
    const selected = allSessions.value.find((item) => item.session_id === id)
    if (selected && deepSessionStatus(selected) === 'archived') showArchivedSessions.value = true
  },
  { immediate: true }
)

const setSessionRowRef = (element, id) => {
  if (element) sessionRowRefs.set(id, element)
  else sessionRowRefs.delete(id)
}

const revealSelectedSession = async (id) => {
  if (!id) return
  const group = visibleGroups.value.find((item) =>
    item.sessions.some((session) => session.session_id === id)
  )
  if (group && collapsedGroups.value[group.group_key]) {
    collapsedGroups.value = { ...collapsedGroups.value, [group.group_key]: false }
  }
  await nextTick()
  const row = sessionRowRefs.get(id)
  const scroller = historyScroll.value
  if (!row || !scroller) return
  const rowRect = row.getBoundingClientRect()
  const scrollRect = scroller.getBoundingClientRect()
  if (rowRect.top < scrollRect.top || rowRect.bottom > scrollRect.bottom) {
    row.scrollIntoView({ block: 'nearest' })
  }
}

watch(
  [() => props.selectedSessionId, () => props.pendingSessionId, visibleGroups],
  ([selectedId, pendingId]) => void revealSelectedSession(pendingId || selectedId),
  { immediate: true, flush: 'post' }
)

const switchFilter = (archived) => {
  showArchivedSessions.value = archived
  deleteConfirmSessionId.value = ''
  renamingSessionId.value = ''
  renameDraft.value = ''
  localError.value = ''
}

const toggleGroup = (groupKey) => {
  collapsedGroups.value = {
    ...collapsedGroups.value,
    [groupKey]: !collapsedGroups.value[groupKey]
  }
}

const sessionTitle = (item) =>
  String(item?.title || item?.capability_name || item?.topic || '未命名对话').trim() || '未命名对话'

const sessionKindLabel = (item) =>
  ({
    'deep-thinking': '深度思考',
    'reference-research': '参考武器深研',
    'capability-followup': '能力画像追问'
  })[String(item?.kind || item?.payload?.kind || '').toLowerCase()] || '专家会话'

const sessionMeta = (item) =>
  [
    sessionKindLabel(item),
    item?.capability_name && item.capability_name !== item.title ? item.capability_name : '',
    formatDeepSessionTime(item?.updated_at || item?.created_at)
  ]
    .filter(Boolean)
    .join(' · ')

const selectSession = (item) => {
  if (renamingSessionId.value === item.session_id) return
  deleteConfirmSessionId.value = ''
  emit('select', item)
}

const beginRename = async (item) => {
  deleteConfirmSessionId.value = ''
  localError.value = ''
  renamingSessionId.value = item.session_id
  renameDraft.value = sessionTitle(item)
  await nextTick()
  const input = Array.isArray(renameInput.value) ? renameInput.value.at(-1) : renameInput.value
  input?.focus()
  input?.select()
}

const cancelRename = () => {
  renamingSessionId.value = ''
  renameDraft.value = ''
  localError.value = ''
}

const saveRename = (item) => {
  const title = renameDraft.value.trim()
  if (!title) {
    localError.value = '对话名称不能为空。'
    return
  }
  if (title !== sessionTitle(item)) emit('rename', { item, title })
  cancelRename()
}

const beginDelete = (item) => {
  cancelRename()
  deleteConfirmSessionId.value = item.session_id
  localError.value = ''
}

const requestArchive = (item) => {
  deleteConfirmSessionId.value = ''
  emit('archive', item)
}

const requestRestore = (item) => {
  deleteConfirmSessionId.value = ''
  emit('restore', item)
}

const requestDelete = (item) => {
  emit('delete', item)
  deleteConfirmSessionId.value = ''
}

defineExpose({
  showCurrent: () => switchFilter(false),
  showArchived: () => switchFilter(true)
})
</script>

<template>
  <aside class="deep-session-list" aria-label="定向深研历史">
    <header>
      <div>
        <b>定向深研历史</b>
        <span>{{ visibleSessionCount }}</span>
      </div>
      <nav aria-label="对话历史筛选">
        <button
          type="button"
          :class="{ active: !showArchivedSessions }"
          @click="switchFilter(false)"
        >
          当前 {{ currentSessions.length }}
        </button>
        <button type="button" :class="{ active: showArchivedSessions }" @click="switchFilter(true)">
          归档 {{ archivedSessions.length }}
        </button>
      </nav>
    </header>

    <div ref="historyScroll" class="deep-session-history-scroll">
      <p v-if="error || localError" class="deep-panel-error" role="alert">
        <CircleAlert :size="13" />{{ localError || error }}
      </p>
      <p v-if="loading && !allSessions.length" class="deep-session-empty" role="status">
        <RefreshCw :size="14" class="spin" />读取中…
      </p>
      <template v-else-if="visibleGroups.length">
        <section
          v-for="group in visibleGroups"
          :key="group.group_key"
          class="deep-history-group"
          :class="{
            current: group.is_current,
            collapsed: collapsedGroups[group.group_key]
          }"
        >
          <button
            type="button"
            class="deep-history-group-toggle"
            :aria-expanded="!collapsedGroups[group.group_key]"
            :title="splitDeepQueryDisplay(group.query).full"
            @click="toggleGroup(group.group_key)"
          >
            <span class="deep-history-group-chevron" aria-hidden="true">
              <ChevronRight v-if="collapsedGroups[group.group_key]" :size="13" />
              <ChevronDown v-else :size="13" />
            </span>
            <span class="deep-history-group-main">
              <span class="deep-history-group-topic">
                {{ splitDeepQueryDisplay(group.query).topic }}
              </span>
              <span class="deep-history-group-meta">
                <em :class="{ current: group.is_current }">
                  {{ group.is_current ? '当前 Query' : '历史 Query' }}
                </em>
                <span>{{ group.session_count }} 段对话</span>
                <span
                  v-if="splitDeepQueryDisplay(group.query).hasBackground"
                  class="deep-history-group-hint"
                >
                  含背景
                </span>
              </span>
            </span>
          </button>

          <div v-if="!collapsedGroups[group.group_key]" class="deep-history-group-body">
            <details
              v-if="
                splitDeepQueryDisplay(group.query).hasBackground ||
                splitDeepQueryDisplay(group.query).topic.length > 28
              "
              class="deep-history-group-query"
            >
              <summary>
                <span class="deep-history-group-query-label">完整 Query</span>
                <span class="deep-history-group-query-preview">
                  {{
                    splitDeepQueryDisplay(group.query).hasBackground
                      ? splitDeepQueryDisplay(group.query).backgroundPreview
                      : splitDeepQueryDisplay(group.query).topic
                  }}
                </span>
              </summary>
              <div class="deep-history-group-query-body">
                <p><b>主题</b>{{ splitDeepQueryDisplay(group.query).topic }}</p>
                <p v-if="splitDeepQueryDisplay(group.query).hasBackground">
                  <b>背景</b>{{ splitDeepQueryDisplay(group.query).background }}
                </p>
              </div>
            </details>

            <div class="deep-history-group-sessions">
              <div
                v-for="item in group.sessions"
                :key="item.session_id"
                :ref="(element) => setSessionRowRef(element, item.session_id)"
                class="deep-session-row"
                :class="{
                  active: selectedSessionId === item.session_id,
                  opening: pendingSessionId === item.session_id
                }"
              >
                <form
                  v-if="renamingSessionId === item.session_id"
                  class="deep-session-rename"
                  @submit.prevent="saveRename(item)"
                >
                  <input
                    ref="renameInput"
                    v-model="renameDraft"
                    maxlength="240"
                    aria-label="对话名称"
                    @keydown.esc.prevent="cancelRename"
                  />
                  <button
                    type="submit"
                    aria-label="保存对话名称"
                    :disabled="busySessionId === item.session_id"
                  >
                    <Check :size="13" />
                  </button>
                  <button type="button" aria-label="取消重命名" @click="cancelRename">
                    <X :size="13" />
                  </button>
                </form>
                <button
                  v-else
                  type="button"
                  class="deep-session-select"
                  :aria-current="selectedSessionId === item.session_id ? 'page' : undefined"
                  :aria-busy="pendingSessionId === item.session_id"
                  @click="selectSession(item)"
                >
                  <span>
                    <b :title="sessionTitle(item)">{{ sessionTitle(item) }}</b>
                    <small :title="sessionMeta(item)">{{ sessionMeta(item) }}</small>
                  </span>
                  <span v-if="pendingSessionId === item.session_id" class="deep-session-opening">
                    <RefreshCw :size="11" class="spin" /> 正在打开
                  </span>
                  <em v-else :class="deepSessionStatus(item)">
                    {{ deepSessionStatusLabel(deepSessionStatus(item)) }}
                  </em>
                </button>

                <div
                  class="deep-session-actions"
                  :class="{ 'confirm-delete': deleteConfirmSessionId === item.session_id }"
                >
                  <template v-if="deleteConfirmSessionId === item.session_id">
                    <span>删除后无法恢复</span>
                    <button
                      type="button"
                      class="danger"
                      :disabled="busySessionId === item.session_id"
                      :aria-label="`确认删除对话：${sessionTitle(item)}`"
                      @click="requestDelete(item)"
                    >
                      <RefreshCw v-if="busySessionId === item.session_id" :size="11" class="spin" />
                      <Trash2 v-else :size="11" />
                      <span>确认删除</span>
                    </button>
                    <button
                      type="button"
                      :disabled="busySessionId === item.session_id"
                      @click="deleteConfirmSessionId = ''"
                    >
                      取消
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-if="!showArchivedSessions"
                      type="button"
                      title="改名"
                      :disabled="busySessionId === item.session_id"
                      @click="beginRename(item)"
                    >
                      <Pencil :size="12" /><span>改名</span>
                    </button>
                    <button
                      v-if="showArchivedSessions"
                      type="button"
                      title="恢复"
                      :disabled="busySessionId === item.session_id"
                      @click="requestRestore(item)"
                    >
                      <RefreshCw v-if="busySessionId === item.session_id" :size="12" class="spin" />
                      <RotateCcw v-else :size="12" /><span>恢复</span>
                    </button>
                    <button
                      v-else
                      type="button"
                      title="归档"
                      :disabled="busySessionId === item.session_id"
                      @click="requestArchive(item)"
                    >
                      <RefreshCw v-if="busySessionId === item.session_id" :size="12" class="spin" />
                      <Archive v-else :size="12" /><span>归档</span>
                    </button>
                    <button
                      type="button"
                      title="删除"
                      :disabled="busySessionId === item.session_id"
                      @click="beginDelete(item)"
                    >
                      <Trash2 :size="12" /><span>删除</span>
                    </button>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
      <p v-else class="deep-session-empty">
        {{ showArchivedSessions ? '没有已归档对话' : '还没有定向深研会话' }}<br />
        <small>
          {{
            showArchivedSessions ? '归档后可在这里恢复或删除' : '按 Query 任务分组后会出现在这里'
          }}
        </small>
      </p>
    </div>
  </aside>
</template>

<style scoped>
.deep-session-list {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  padding: 12px 10px;
  border-right: 0;
  background: #f4f6fb;
}
.deep-session-list > header {
  position: sticky;
  top: -14px;
  z-index: 2;
  display: grid;
  gap: 7px;
  margin: 0 -2px;
  padding: 0 2px 10px;
  color: #45526d;
  font-size: 12px;
  background: linear-gradient(180deg, #f4f6fb 70%, rgb(244 246 251 / 92%));
}
.deep-session-list > header > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.deep-session-list > header > div span {
  min-width: 20px;
  padding: 2px 6px;
  border-radius: 999px;
  background: #e9eaff;
  color: #5d5adf;
  font-size: 10px;
  text-align: center;
}
.deep-session-list > header nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}
.deep-session-list > header nav button {
  min-height: 25px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #8490a7;
  font-size: 9px;
  cursor: pointer;
}
.deep-session-list > header nav button.active {
  border-color: #d7daf7;
  background: #fff;
  color: #504dca;
  font-weight: 700;
}
.deep-session-history-scroll {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 0 2px 8px;
}
.deep-history-group {
  margin: 0 0 10px;
  overflow: hidden;
  border: 1px solid #e4e9f4;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 0 rgb(36 47 91 / 3%);
  isolation: isolate;
}
.deep-history-group.current {
  border-color: #c7ccff;
  box-shadow:
    0 0 0 1px rgb(98 95 240 / 8%),
    0 1px 0 rgb(36 47 91 / 3%);
}
.deep-history-group-toggle {
  display: grid;
  width: 100%;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  margin: 0;
  padding: 11px 12px;
  overflow: hidden;
  border: 0;
  background: linear-gradient(180deg, #f8f9fd, #f5f7fc);
  text-align: left;
  cursor: pointer;
}
.deep-history-group.current .deep-history-group-toggle {
  background: linear-gradient(180deg, #f4f5ff, #eef0ff);
}
.deep-history-group-chevron {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: none;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
  border-radius: 5px;
  color: #7b86a0;
}
.deep-history-group.current .deep-history-group-chevron {
  background: rgb(98 95 240 / 8%);
  color: #5c59d4;
}
.deep-history-group-main {
  display: grid;
  min-width: 0;
  gap: 6px;
  overflow: hidden;
}
.deep-history-group-topic {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: #2f3b55;
  font-size: 12.5px;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deep-history-group-meta {
  display: flex;
  min-width: 0;
  flex-wrap: nowrap;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  color: #8b95a9;
  font-size: 10px;
  line-height: 1.3;
}
.deep-history-group-meta em {
  display: inline-flex;
  min-height: 18px;
  flex: none;
  align-items: center;
  padding: 0 7px;
  border-radius: 999px;
  background: #eef0f6;
  color: #6f7a90;
  font-style: normal;
  font-weight: 650;
  white-space: nowrap;
}
.deep-history-group-meta em.current {
  background: #e9eaff;
  color: #5552d4;
}
.deep-history-group-meta > span {
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deep-history-group-hint {
  min-height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  background: #f0f2f8;
  color: #7b849c;
  font-weight: 650;
}
.deep-history-group-body {
  display: grid;
  gap: 0;
  overflow: hidden;
  border-top: 1px solid #edf0f6;
  background: #fbfcff;
}
.deep-history-group-query {
  margin: 0;
  padding: 0;
  overflow: hidden;
  border-bottom: 1px solid #eef1f7;
  background: #f7f8fd;
}
.deep-history-group-query summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  overflow: hidden;
  color: #6c6ac8;
  font-size: 10px;
  font-weight: 650;
  list-style: none;
  cursor: pointer;
  user-select: none;
}
.deep-history-group-query summary::-webkit-details-marker {
  display: none;
}
.deep-history-group-query summary::before {
  flex: none;
  color: #8c8bc8;
  content: '▸';
  transition: transform 0.15s ease;
}
.deep-history-group-query[open] summary::before {
  transform: rotate(90deg);
}
.deep-history-group-query-label {
  flex: none;
  white-space: nowrap;
}
.deep-history-group-query-preview {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: #8b95a9;
  font-weight: 450;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deep-history-group-query-body {
  max-height: 140px;
  margin: 0 10px 10px;
  padding: 8px 9px;
  overflow: auto;
  border: 1px solid #e4e8f5;
  border-radius: 8px;
  background: #fff;
}
.deep-history-group-query-body p {
  margin: 0;
  color: #4a5670;
  font-size: 11px;
  line-height: 1.55;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: pre-wrap;
}
.deep-history-group-query-body p + p {
  margin-top: 8px;
}
.deep-history-group-query-body b {
  display: block;
  margin-bottom: 2px;
  color: #7d879c;
  font-size: 10px;
  font-weight: 700;
}
.deep-history-group-sessions {
  display: grid;
  gap: 6px;
  padding: 8px;
  overflow: hidden;
}
.deep-session-row {
  position: relative;
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 10px;
  border: 1px solid #e7ebf4;
  border-radius: 11px;
  background: #fff;
  color: #56627b;
  text-align: left;
  box-shadow: 0 1px 0 rgb(36 47 91 / 2%);
  transition:
    border-color 0.14s ease,
    background-color 0.14s ease,
    box-shadow 0.14s ease;
}
.deep-session-row:hover,
.deep-session-row.active {
  border-color: #cfd3ff;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(98 95 240 / 8%);
}
.deep-session-row.active::before,
.deep-session-row.opening::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: -1px;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: #625ff0;
  content: '';
}
.deep-session-row.opening {
  border-color: #bfc4ff;
  background: #f8f8ff;
  box-shadow: 0 0 0 1px rgb(98 95 240 / 12%);
}
.deep-session-select {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.deep-session-select > span {
  display: grid;
  min-width: 0;
  gap: 4px;
}
.deep-session-row b,
.deep-session-row small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deep-session-row b {
  color: #2f3b55;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.4;
}
.deep-session-row small {
  color: #8b95a9;
  font-size: 10px;
  line-height: 1.4;
}
.deep-session-row:hover b,
.deep-session-row.active b {
  color: #403eae;
}
.deep-session-row em {
  display: inline-flex;
  min-height: 20px;
  align-self: flex-start;
  align-items: center;
  padding: 0 7px;
  border-radius: 999px;
  background: #eef0f7;
  color: #7b87a0;
  font-size: 10px;
  font-style: normal;
  white-space: nowrap;
}
.deep-session-row em.active,
.deep-session-row em.running {
  background: #edf7f1;
  color: #3f8462;
}
.deep-session-row em.failed,
.deep-session-row em.blocked,
.deep-session-row em.cancelled {
  background: #fff0f1;
  color: #aa5964;
}
.deep-session-row em.archived {
  background: #f0f1f4;
  color: #747d8f;
}
.deep-session-select > .deep-session-opening {
  display: inline-flex;
  min-height: 20px;
  align-self: flex-start;
  align-items: center;
  gap: 5px;
  padding: 0 7px;
  border-radius: 999px;
  background: #ececff;
  color: #514ed2;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}
.deep-session-actions {
  display: flex;
  min-height: 24px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  padding-top: 6px;
  border-top: 1px solid #eef0f7;
}
.deep-session-actions button {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  gap: 4px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #6f7698;
  font-size: 10px;
  cursor: pointer;
}
.deep-session-actions button:hover:not(:disabled) {
  border-color: #d7daf7;
  background: #f0f0ff;
  color: #4e4bc8;
}
.deep-session-actions button:disabled {
  cursor: wait;
  opacity: 0.58;
}
.deep-session-actions.confirm-delete {
  justify-content: flex-start;
  gap: 6px;
}
.deep-session-actions.confirm-delete > span {
  flex: 1 1 100%;
  margin: 0;
  color: #a14f5b;
  font-size: 10px;
}
.deep-session-actions button.danger {
  color: #b24e5d;
}
.deep-session-actions button.danger:hover:not(:disabled) {
  border-color: #efc6cc;
  background: #fff0f2;
  color: #9f3445;
}
.deep-session-rename {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px 28px;
  gap: 4px;
}
.deep-session-rename input {
  min-width: 0;
  height: 30px;
  padding: 0 8px;
  border: 1px solid #abaaf0;
  border-radius: 7px;
  outline: none;
  background: #fff;
  color: #394662;
  font-size: 11px;
}
.deep-session-rename button {
  display: inline-flex;
  width: 28px;
  height: 30px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid #d8dcf0;
  border-radius: 7px;
  background: #fff;
  color: #5c59d4;
  cursor: pointer;
}
.deep-session-empty,
.deep-panel-error {
  display: flex;
  min-height: 88px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 10px 5px;
  color: #8b95a9;
  font-size: 11px;
  line-height: 1.55;
  text-align: center;
}
.deep-session-empty {
  flex-direction: column;
}
.deep-session-empty small {
  color: #9ba4b6;
}
.deep-panel-error {
  min-height: 0;
  justify-content: flex-start;
  color: #b05c67;
  text-align: left;
}
.spin {
  animation: deep-session-spin 0.9s linear infinite;
}
@keyframes deep-session-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}

@media (max-width: 960px) {
  .deep-session-list {
    display: flex;
    min-height: 0;
    max-height: 88px;
    overflow: hidden;
    padding: 10px 12px;
    border-right: 0;
    border-bottom: 1px solid #e5e9f3;
  }
  .deep-session-list > header {
    position: sticky;
    top: -10px;
    z-index: 2;
    width: auto;
    padding: 8px 2px 10px;
    background: #f4f6fb;
  }
  .deep-session-row {
    width: 100%;
  }
  .deep-session-empty {
    display: none;
  }
}

@media (max-width: 720px) {
  .deep-session-list {
    max-height: 80px;
  }
  .deep-history-group-query {
    display: none;
  }
  .deep-history-group {
    margin-bottom: 6px;
  }
  .deep-history-group-toggle {
    padding-top: 8px;
    padding-bottom: 8px;
  }
}

@media (max-width: 520px) {
  .deep-session-actions button > span {
    display: none;
  }
  .deep-session-actions.confirm-delete button > span {
    display: inline;
  }
}

:global(html.dark) .deep-session-list {
  border-color: #343a47;
  background: #151a27;
}
:global(html.dark) .deep-session-list > header {
  color: #cbd3e2;
  background: linear-gradient(180deg, #151a27 70%, rgb(21 26 39 / 92%));
}
:global(html.dark) .deep-session-list > header > div span {
  background: rgb(113 110 224 / 20%);
  color: #aaa8ff;
}
:global(html.dark) .deep-session-list > header nav button {
  color: #929db1;
}
:global(html.dark) .deep-session-list > header nav button.active {
  border-color: #4a4d78;
  background: #20263a;
  color: #b9b7ff;
}
:global(html.dark) .deep-history-group {
  border-color: #343d51;
  background: #1c2333;
  box-shadow: 0 1px 0 rgb(0 0 0 / 18%);
}
:global(html.dark) .deep-history-group.current {
  border-color: #716ee0;
  box-shadow:
    0 0 0 1px rgb(113 110 224 / 15%),
    0 1px 0 rgb(0 0 0 / 18%);
}
:global(html.dark) .deep-history-group-toggle {
  background: linear-gradient(180deg, #20283a, #1b2232);
}
:global(html.dark) .deep-history-group.current .deep-history-group-toggle {
  background: linear-gradient(180deg, #292b49, #242642);
}
:global(html.dark) .deep-history-group-chevron {
  color: #929db1;
}
:global(html.dark) .deep-history-group.current .deep-history-group-chevron {
  background: rgb(151 149 246 / 13%);
  color: #aaa8ff;
}
:global(html.dark) .deep-history-group-topic,
:global(html.dark) .deep-session-row b {
  color: #dce2ed;
}
:global(html.dark) .deep-history-group-meta,
:global(html.dark) .deep-history-group-query-preview,
:global(html.dark) .deep-session-row small,
:global(html.dark) .deep-session-empty {
  color: #929db1;
}
:global(html.dark) .deep-history-group-meta em,
:global(html.dark) .deep-history-group-hint,
:global(html.dark) .deep-session-row em {
  background: #2a3142;
  color: #aab4c6;
}
:global(html.dark) .deep-history-group-meta em.current {
  background: rgb(113 110 224 / 22%);
  color: #b9b7ff;
}
:global(html.dark) .deep-history-group-body {
  border-color: #30384a;
  background: #171d2a;
}
:global(html.dark) .deep-history-group-query {
  border-color: #30384a;
  background: #1a2130;
}
:global(html.dark) .deep-history-group-query summary {
  color: #aaa8ff;
}
:global(html.dark) .deep-history-group-query summary::before {
  color: #8f8dd8;
}
:global(html.dark) .deep-history-group-query-body {
  border-color: #394257;
  background: #1e2637;
}
:global(html.dark) .deep-history-group-query-body p {
  color: #c5cddd;
}
:global(html.dark) .deep-history-group-query-body b {
  color: #929db1;
}
:global(html.dark) .deep-session-row {
  border-color: #364055;
  background: #1c2333;
  color: #b7c0d1;
  box-shadow: 0 1px 0 rgb(0 0 0 / 16%);
}
:global(html.dark) .deep-session-row:hover,
:global(html.dark) .deep-session-row.active {
  border-color: #716ee0;
  background: #222941;
  box-shadow: 0 0 0 1px rgb(113 110 224 / 15%);
}
:global(html.dark) .deep-session-row.opening {
  border-color: #716ee0;
  background: #242642;
}
:global(html.dark) .deep-session-select > .deep-session-opening {
  background: rgb(113 110 224 / 22%);
  color: #c1bfff;
}
:global(html.dark) .deep-session-row:hover b,
:global(html.dark) .deep-session-row.active b {
  color: #b9b7ff;
}
:global(html.dark) .deep-session-row em.active,
:global(html.dark) .deep-session-row em.running {
  background: #18372c;
  color: #77c79e;
}
:global(html.dark) .deep-session-row em.failed,
:global(html.dark) .deep-session-row em.blocked,
:global(html.dark) .deep-session-row em.cancelled {
  background: #41242b;
  color: #ee9da8;
}
:global(html.dark) .deep-session-row em.archived {
  background: #2b303a;
  color: #a5adba;
}
:global(html.dark) .deep-session-actions {
  border-color: #30384a;
}
:global(html.dark) .deep-session-actions button {
  color: #a9add5;
}
:global(html.dark) .deep-session-actions button:hover:not(:disabled) {
  border-color: #55559a;
  background: #292b49;
  color: #c3c1ff;
}
:global(html.dark) .deep-session-actions button.danger {
  color: #e98e9b;
}
:global(html.dark) .deep-session-actions button.danger:hover:not(:disabled) {
  border-color: #70414a;
  background: #41242b;
  color: #ffadb8;
}
:global(html.dark) .deep-session-rename input,
:global(html.dark) .deep-session-rename button {
  border-color: #4a5270;
  background: #171d2a;
  color: #c8c6ff;
}
:global(html.dark) .deep-panel-error,
:global(html.dark) .deep-session-actions.confirm-delete > span {
  color: #e98e9b;
}

@media (max-width: 960px) {
  :global(html.dark) .deep-session-list > header {
    background: #151a27;
  }
}
</style>

<!--
  Keep the dark overrides that target the document root outside scoped CSS.
  With the current Vue compiler, `:global(html.dark) .child` is reduced to
  `html.dark`, which silently drops `.child` and leaves these cards light.
-->
<style>
html.dark .deep-history-group-meta em,
html.dark .deep-history-group-hint {
  background: #2a3142;
  color: #aab4c6;
}

html.dark .deep-history-group-meta em.current {
  background: rgb(113 110 224 / 22%);
  color: #b9b7ff;
}

html.dark .deep-session-row {
  border-color: #364055;
  background: #1c2333;
  color: #b7c0d1;
  box-shadow: 0 1px 0 rgb(0 0 0 / 16%);
}

html.dark .deep-session-row:hover,
html.dark .deep-session-row.active {
  border-color: #716ee0;
  background: #222941;
  box-shadow: 0 0 0 1px rgb(113 110 224 / 15%);
}

html.dark .deep-session-row.opening {
  border-color: #716ee0;
  background: #242642;
}

html.dark .deep-session-row b {
  color: #dce2ed;
}

html.dark .deep-session-row small {
  color: #929db1;
}

html.dark .deep-session-row:hover b,
html.dark .deep-session-row.active b {
  color: #b9b7ff;
}

html.dark .deep-session-row em {
  background: #2a3142;
  color: #aab4c6;
}

html.dark .deep-session-row em.active,
html.dark .deep-session-row em.running {
  background: #18372c;
  color: #77c79e;
}

html.dark .deep-session-row em.failed,
html.dark .deep-session-row em.blocked,
html.dark .deep-session-row em.cancelled {
  background: #41242b;
  color: #ee9da8;
}

html.dark .deep-session-row em.archived {
  background: #2b303a;
  color: #a5adba;
}

html.dark .deep-session-select > .deep-session-opening {
  background: rgb(113 110 224 / 22%);
  color: #c1bfff;
}

html.dark .deep-session-actions {
  border-color: #30384a;
}

html.dark .deep-session-actions button {
  color: #a9add5;
}

html.dark .deep-session-actions button:hover:not(:disabled) {
  border-color: #55559a;
  background: #292b49;
  color: #c3c1ff;
}

html.dark .deep-session-actions button.danger {
  color: #e98e9b;
}

html.dark .deep-session-actions button.danger:hover:not(:disabled) {
  border-color: #70414a;
  background: #41242b;
  color: #ffadb8;
}

html.dark .deep-session-rename input,
html.dark .deep-session-rename button {
  border-color: #4a5270;
  background: #171d2a;
  color: #c8c6ff;
}

html.dark .deep-session-actions.confirm-delete > span {
  color: #e98e9b;
}
</style>
