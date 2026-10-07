<script setup>
import { computed, ref, watch } from 'vue'
import {
  Archive,
  ArrowUp,
  Bot,
  Boxes,
  BrainCircuit,
  CircleAlert,
  Clock3,
  GitBranch,
  RefreshCw,
  UserRound,
  Workflow
} from '@lucide/vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { formatFullDateTime } from '@/utils/time'
import {
  formatLegacyDeepJson,
  formatLegacyDeepReference,
  hasLegacyDeepValue,
  projectLegacyDeepSession
} from '@/utils/equipmentLegacyDeepSession.js'

const props = defineProps({
  session: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  sending: { type: Boolean, default: false }
})

const emit = defineEmits(['submit'])

const draft = ref('')
const projection = computed(() => projectLegacyDeepSession(props.session))
const hasSession = computed(() => Boolean(projection.value.id || props.session))
const canSubmit = computed(
  () => !projection.value.archived && !props.sending && Boolean(draft.value.trim())
)

watch(
  () => projection.value.id,
  () => {
    draft.value = ''
  }
)

const submitDraft = () => {
  const content = draft.value.trim()
  if (!content || props.sending || projection.value.archived) return
  emit('submit', content)
  draft.value = ''
}

const handleComposerKeydown = (event) => {
  if (event.isComposing) return
  if (
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey
  ) {
    event.preventDefault()
    submitDraft()
  }
}

const isUserRole = (role) => ['user', 'human'].includes(String(role || '').toLowerCase())
const displayTime = (value) => (value ? formatFullDateTime(value) : '')
</script>

<template>
  <section class="legacy-deep-session" :aria-busy="loading || sending">
    <div v-if="loading && !hasSession" class="legacy-session-state" role="status">
      <span class="legacy-state-icon"><RefreshCw :size="21" class="spin" /></span>
      <b>正在读取历史深研会话</b>
      <p>消息、任务、分支与旧版检查点会一并恢复。</p>
    </div>

    <div v-else-if="error && !hasSession" class="legacy-session-state error" role="alert">
      <span class="legacy-state-icon"><CircleAlert :size="21" /></span>
      <b>历史深研会话加载失败</b>
      <p>{{ error }}</p>
    </div>

    <div v-else-if="!hasSession" class="legacy-session-state empty">
      <span class="legacy-state-icon"><BrainCircuit :size="22" /></span>
      <b>暂无可显示的历史会话</b>
      <p>选择一条旧版深研记录后，可在这里读取完整对话与运行轨迹。</p>
    </div>

    <template v-else>
      <header class="legacy-session-header">
        <div class="legacy-session-heading">
          <span class="legacy-session-kicker"><BrainCircuit :size="14" /> 历史兼容会话</span>
          <h2>{{ projection.title }}</h2>
          <p v-if="projection.topic">{{ projection.topic }}</p>
          <small>
            <code>{{ projection.id }}</code>
            <span v-if="displayTime(projection.updatedAt || projection.createdAt)">
              更新于 {{ displayTime(projection.updatedAt || projection.createdAt) }}
            </span>
          </small>
        </div>
        <span class="legacy-status" :class="projection.statusTone">
          {{ projection.statusLabel }}
        </span>
      </header>

      <div v-if="loading" class="legacy-inline-state" role="status">
        <RefreshCw :size="14" class="spin" />正在同步历史记录…
      </div>
      <div v-if="error" class="legacy-inline-state error" role="alert">
        <CircleAlert :size="14" />{{ error }}
      </div>
      <div v-if="projection.archived" class="legacy-archive-banner" role="status">
        <Archive :size="15" />
        <span><b>该会话已归档</b>历史消息和运行记录保持可读，恢复后才能继续追问。</span>
      </div>

      <div class="legacy-session-scroll">
        <section class="legacy-messages" aria-label="历史深研消息">
          <header class="legacy-section-heading">
            <span><Bot :size="15" /><b>对话记录</b></span>
            <em>{{ projection.messages.length }} 条</em>
          </header>

          <div v-if="!projection.messages.length" class="legacy-section-empty">
            <Bot :size="19" />
            <span
              ><b>尚无历史消息</b><small>发送首条追问后，旧版运行结果会显示在这里。</small></span
            >
          </div>

          <article
            v-for="item in projection.messages"
            v-else
            :key="item.id"
            class="legacy-message"
            :class="{ user: isUserRole(item.role) }"
          >
            <span class="legacy-message-avatar">
              <UserRound v-if="isUserRole(item.role)" :size="15" />
              <Bot v-else :size="15" />
            </span>
            <div class="legacy-message-content">
              <div class="legacy-message-meta">
                <b>{{ item.roleLabel }}</b>
                <span v-if="displayTime(item.createdAt)">{{ displayTime(item.createdAt) }}</span>
                <span class="legacy-status compact" :class="item.statusTone">
                  {{ item.statusLabel }}
                </span>
                <code v-if="item.branchId">分支 {{ item.branchId }}</code>
                <code v-if="item.sequence !== null">#{{ item.sequence }}</code>
              </div>

              <div v-if="isUserRole(item.role)" class="legacy-user-body">
                {{ item.content || '（空消息）' }}
              </div>
              <div v-else class="legacy-assistant-body">
                <MarkdownPreview :content="item.content || '（空消息）'" code-copy />
              </div>

              <p v-if="item.error" class="legacy-record-error" role="alert">
                <CircleAlert :size="13" />{{ item.error }}
              </p>

              <div
                v-if="item.artifactRefs.length || item.versionRefs.length"
                class="legacy-reference-groups"
              >
                <div v-if="item.artifactRefs.length">
                  <span><Boxes :size="12" />产物引用</span>
                  <code
                    v-for="(reference, index) in item.artifactRefs"
                    :key="`artifact-${item.id}-${index}`"
                  >
                    {{ formatLegacyDeepReference(reference) }}
                  </code>
                </div>
                <div v-if="item.versionRefs.length">
                  <span><Workflow :size="12" />版本引用</span>
                  <code
                    v-for="(reference, index) in item.versionRefs"
                    :key="`version-${item.id}-${index}`"
                  >
                    {{ formatLegacyDeepReference(reference) }}
                  </code>
                </div>
              </div>

              <div class="legacy-record-details">
                <details>
                  <summary>消息链路</summary>
                  <dl>
                    <dt>消息 ID</dt>
                    <dd>
                      <code>{{ item.id }}</code>
                    </dd>
                    <template v-if="item.parentMessageId">
                      <dt>父消息</dt>
                      <dd>
                        <code>{{ item.parentMessageId }}</code>
                      </dd>
                    </template>
                    <template v-if="item.turnId">
                      <dt>轮次</dt>
                      <dd>
                        <code>{{ item.turnId }}</code>
                      </dd>
                    </template>
                    <dt>消息类型</dt>
                    <dd>{{ item.messageKind }}</dd>
                    <dt>原始角色</dt>
                    <dd>{{ item.role }}</dd>
                  </dl>
                </details>
                <details v-if="hasLegacyDeepValue(item.metadata)">
                  <summary>消息 metadata</summary>
                  <pre>{{ formatLegacyDeepJson(item.metadata) }}</pre>
                </details>
              </div>
            </div>
          </article>

          <div v-if="sending" class="legacy-sending-row" role="status" aria-live="polite">
            <span class="legacy-message-avatar"><Bot :size="15" /></span>
            <div>
              <b>研究助手正在处理追问</b>
              <span class="legacy-thinking-dots" aria-hidden="true"><i /><i /><i /></span>
            </div>
          </div>
        </section>

        <section class="legacy-ledger" aria-label="历史深研运行记录">
          <header class="legacy-section-heading">
            <span><Workflow :size="15" /><b>运行记录</b></span>
            <em>{{ projection.jobs.length }} 项</em>
          </header>

          <div v-if="!projection.jobs.length" class="legacy-section-empty compact">
            <Workflow :size="18" />
            <span><b>没有旧版任务记录</b><small>当前会话只保留了消息正文。</small></span>
          </div>
          <div v-else class="legacy-job-list">
            <article v-for="job in projection.jobs" :key="job.id" class="legacy-job-card">
              <header>
                <span class="legacy-job-icon"><Workflow :size="14" /></span>
                <span>
                  <b>{{ job.stage || job.kind || '深研任务' }}</b>
                  <small
                    ><code>{{ job.id }}</code></small
                  >
                </span>
                <em class="legacy-status compact" :class="job.statusTone">
                  {{ job.statusLabel }}
                </em>
              </header>
              <div class="legacy-job-facts">
                <span v-if="job.kind">类型 {{ job.kind }}</span>
                <span v-if="job.branchId">分支 {{ job.branchId }}</span>
                <span v-if="job.stateVersion !== null">状态版本 {{ job.stateVersion }}</span>
                <span v-if="job.modelSpec">模型 {{ job.modelSpec }}</span>
                <span v-if="displayTime(job.updatedAt)"
                  ><Clock3 :size="11" />{{ displayTime(job.updatedAt) }}</span
                >
              </div>
              <p v-if="job.error" class="legacy-record-error" role="alert">
                <CircleAlert :size="13" />{{ job.error }}
              </p>
              <dl
                v-if="job.parentJobId || job.childRunId || job.rootMessageId"
                class="legacy-job-links"
              >
                <template v-if="job.parentJobId">
                  <dt>父任务</dt>
                  <dd>
                    <code>{{ job.parentJobId }}</code>
                  </dd>
                </template>
                <template v-if="job.childRunId">
                  <dt>子运行</dt>
                  <dd>
                    <code>{{ job.childRunId }}</code>
                  </dd>
                </template>
                <template v-if="job.rootMessageId">
                  <dt>起点消息</dt>
                  <dd>
                    <code>{{ job.rootMessageId }}</code>
                  </dd>
                </template>
              </dl>
              <div class="legacy-record-details">
                <details v-if="hasLegacyDeepValue(job.checkpoint)">
                  <summary>Checkpoint</summary>
                  <pre>{{ formatLegacyDeepJson(job.checkpoint) }}</pre>
                </details>
                <details v-if="hasLegacyDeepValue(job.payload)">
                  <summary>任务 payload</summary>
                  <pre>{{ formatLegacyDeepJson(job.payload) }}</pre>
                </details>
              </div>
            </article>
          </div>
        </section>

        <section class="legacy-ledger" aria-label="历史深研分支">
          <header class="legacy-section-heading">
            <span><GitBranch :size="15" /><b>研究分支</b></span>
            <em>{{ projection.branches.length }} 条</em>
          </header>

          <div v-if="!projection.branches.length" class="legacy-section-empty compact">
            <GitBranch :size="18" />
            <span><b>没有独立分支记录</b><small>现有消息按旧版主线顺序展示。</small></span>
          </div>
          <div v-else class="legacy-branch-list">
            <article v-for="branch in projection.branches" :key="branch.id">
              <header>
                <span><GitBranch :size="14" /></span>
                <div>
                  <b>{{ branch.title }}</b
                  ><code>{{ branch.id }}</code>
                </div>
                <em class="legacy-status compact" :class="branch.statusTone">
                  {{ branch.statusLabel }}
                </em>
              </header>
              <dl>
                <template v-if="branch.parentBranchId">
                  <dt>父分支</dt>
                  <dd>
                    <code>{{ branch.parentBranchId }}</code>
                  </dd>
                </template>
                <template v-if="branch.forkedFromMessageId">
                  <dt>分叉消息</dt>
                  <dd>
                    <code>{{ branch.forkedFromMessageId }}</code>
                  </dd>
                </template>
                <template v-if="branch.childSessionId">
                  <dt>子会话</dt>
                  <dd>
                    <code>{{ branch.childSessionId }}</code>
                  </dd>
                </template>
                <template v-if="displayTime(branch.createdAt)">
                  <dt>创建时间</dt>
                  <dd>{{ displayTime(branch.createdAt) }}</dd>
                </template>
              </dl>
              <details v-if="hasLegacyDeepValue(branch.payload)">
                <summary>分支 payload</summary>
                <pre>{{ formatLegacyDeepJson(branch.payload) }}</pre>
              </details>
            </article>
          </div>
        </section>
      </div>

      <div v-if="projection.archived" class="legacy-readonly-footer">
        <Archive :size="14" />归档会话为只读状态，请先从历史列表恢复后继续追问。
      </div>
      <form v-else class="legacy-composer-wrap" @submit.prevent="submitDraft">
        <div class="legacy-composer" :class="{ sending }">
          <textarea
            v-model="draft"
            rows="1"
            maxlength="8000"
            :disabled="sending"
            :placeholder="
              sending ? '正在提交追问…' : '继续追问旧版深研会话，Enter 发送，Shift+Enter 换行…'
            "
            aria-label="继续追问历史深研会话"
            @keydown="handleComposerKeydown"
          />
          <button
            type="submit"
            :disabled="!canSubmit"
            :aria-label="sending ? '正在发送' : '发送追问'"
          >
            <RefreshCw v-if="sending" :size="16" class="spin" />
            <ArrowUp v-else :size="17" />
          </button>
        </div>
        <small>旧数据保持原样只读；新追问由父页面提交，服务端终态刷新后再显示。</small>
      </form>
    </template>
  </section>
</template>

<style scoped>
.legacy-deep-session {
  display: flex;
  min-width: 0;
  min-height: 0;
  height: 100%;
  flex: 1;
  flex-direction: column;
  background: var(--gray-25);
  color: var(--gray-900);
}

.legacy-session-state {
  display: grid;
  min-height: 360px;
  place-content: center;
  justify-items: center;
  gap: 8px;
  padding: 32px;
  text-align: center;
}

.legacy-session-state .legacy-state-icon {
  display: grid;
  width: 50px;
  height: 50px;
  place-items: center;
  margin-bottom: 4px;
  border: 1px solid var(--main-100);
  border-radius: 16px;
  background: linear-gradient(145deg, var(--main-50), var(--gray-0));
  color: var(--main-color);
  box-shadow: 0 12px 30px color-mix(in srgb, var(--main-color) 10%, transparent);
}

.legacy-session-state b {
  font-size: 16px;
}

.legacy-session-state p {
  max-width: 520px;
  margin: 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.7;
}

.legacy-session-state.error .legacy-state-icon {
  border-color: color-mix(in srgb, #c4525d 28%, var(--gray-100));
  background: color-mix(in srgb, #c4525d 8%, var(--gray-0));
  color: #b84a55;
}

.legacy-session-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 17px max(24px, calc((100% - 900px) / 2));
  border-bottom: 1px solid var(--gray-100);
  background: color-mix(in srgb, var(--gray-0) 94%, transparent);
}

.legacy-session-heading {
  min-width: 0;
}

.legacy-session-kicker,
.legacy-section-heading > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legacy-session-kicker {
  color: var(--main-color);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.legacy-session-heading h2 {
  margin: 4px 0 0;
  overflow: hidden;
  font-size: 18px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.legacy-session-heading p {
  margin: 3px 0 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.55;
}

.legacy-session-heading small {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 7px;
  color: var(--gray-400);
  font-size: 10px;
}

code {
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.legacy-status {
  display: inline-flex;
  min-height: 25px;
  align-items: center;
  padding: 3px 9px;
  border: 1px solid var(--gray-150);
  border-radius: 999px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 10px;
  font-style: normal;
  font-weight: 650;
  white-space: nowrap;
}

.legacy-status.compact {
  min-height: 20px;
  padding: 2px 7px;
  font-size: 9px;
}

.legacy-status.active {
  border-color: var(--main-150);
  background: var(--main-50);
  color: var(--main-color);
}

.legacy-status.success {
  border-color: color-mix(in srgb, #2d8a67 24%, var(--gray-100));
  background: color-mix(in srgb, #2d8a67 8%, var(--gray-0));
  color: #267858;
}

.legacy-status.pending {
  border-color: color-mix(in srgb, #b47a21 24%, var(--gray-100));
  background: color-mix(in srgb, #b47a21 8%, var(--gray-0));
  color: #976318;
}

.legacy-status.danger {
  border-color: color-mix(in srgb, #c4525d 26%, var(--gray-100));
  background: color-mix(in srgb, #c4525d 8%, var(--gray-0));
  color: #b34853;
}

.legacy-status.muted {
  background: var(--gray-50);
  color: var(--gray-500);
}

.legacy-inline-state,
.legacy-archive-banner {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px max(24px, calc((100% - 900px) / 2));
  border-bottom: 1px solid var(--gray-100);
  color: var(--gray-500);
  font-size: 11px;
}

.legacy-inline-state.error {
  background: color-mix(in srgb, #c4525d 7%, var(--gray-0));
  color: #b34853;
}

.legacy-archive-banner {
  background: color-mix(in srgb, var(--gray-100) 70%, var(--gray-0));
}

.legacy-archive-banner span {
  display: flex;
  gap: 5px;
}

.legacy-session-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 24px max(24px, calc((100% - 900px) / 2)) 30px;
}

.legacy-messages,
.legacy-ledger {
  display: grid;
  gap: 14px;
}

.legacy-ledger {
  margin-top: 26px;
  padding-top: 22px;
  border-top: 1px solid var(--gray-100);
}

.legacy-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--gray-700);
  font-size: 12px;
}

.legacy-section-heading svg {
  color: var(--main-color);
}

.legacy-section-heading em {
  color: var(--gray-400);
  font-size: 10px;
  font-style: normal;
  font-weight: 500;
}

.legacy-section-empty {
  display: flex;
  min-height: 150px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--gray-150);
  border-radius: 14px;
  background: color-mix(in srgb, var(--gray-0) 72%, transparent);
  color: var(--gray-400);
}

.legacy-section-empty.compact {
  min-height: 82px;
}

.legacy-section-empty span {
  display: grid;
  gap: 2px;
}

.legacy-section-empty b {
  color: var(--gray-600);
  font-size: 12px;
}

.legacy-section-empty small {
  font-size: 10px;
}

.legacy-message {
  display: flex;
  align-items: flex-start;
  gap: 11px;
}

.legacy-message.user {
  flex-direction: row-reverse;
}

.legacy-message-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--main-color);
}

.legacy-message.user .legacy-message-avatar {
  border-color: var(--main-color);
  background: var(--main-color);
  color: #fff;
}

.legacy-message-content {
  min-width: 0;
  max-width: calc(100% - 42px);
  flex: 1;
}

.legacy-message.user .legacy-message-content {
  max-width: min(76%, 720px);
  flex: 0 1 auto;
}

.legacy-message-meta {
  display: flex;
  min-height: 22px;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 5px;
  color: var(--gray-400);
  font-size: 9px;
}

.legacy-message.user .legacy-message-meta {
  justify-content: flex-end;
}

.legacy-message-meta b {
  color: var(--gray-600);
  font-size: 10px;
}

.legacy-message-meta code {
  padding: 2px 5px;
  border-radius: 5px;
  background: var(--gray-50);
}

.legacy-user-body {
  padding: 10px 13px;
  border-radius: 12px 3px 12px 12px;
  background: var(--main-color);
  color: #fff;
  font-size: 13px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.legacy-assistant-body {
  padding: 13px 15px;
  border: 1px solid var(--gray-100);
  border-radius: 3px 13px 13px;
  background: var(--gray-0);
  box-shadow: 0 7px 24px color-mix(in srgb, var(--gray-900) 4%, transparent);
}

.legacy-assistant-body :deep(.yk-markdown-preview) {
  color: var(--gray-800);
  font-size: 13px;
  line-height: 1.75;
}

.legacy-assistant-body :deep(.yk-markdown-preview > :first-child) {
  margin-top: 0;
}

.legacy-assistant-body :deep(.yk-markdown-preview > :last-child) {
  margin-bottom: 0;
}

.legacy-record-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 7px 0 0;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, #c4525d 22%, var(--gray-100));
  border-radius: 8px;
  background: color-mix(in srgb, #c4525d 7%, var(--gray-0));
  color: #b34853;
  font-size: 10px;
  line-height: 1.55;
}

.legacy-record-error svg {
  flex: 0 0 auto;
  margin-top: 1px;
}

.legacy-reference-groups {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.legacy-reference-groups > div {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 5px;
}

.legacy-reference-groups span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 22px;
  color: var(--gray-500);
  font-size: 9px;
  font-weight: 650;
}

.legacy-reference-groups code {
  max-width: 100%;
  padding: 3px 6px;
  border: 1px solid var(--gray-100);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 9px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.legacy-record-details {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 8px;
}

details {
  min-width: min(100%, 260px);
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  background: var(--gray-0);
}

summary {
  padding: 6px 9px;
  color: var(--gray-500);
  font-size: 9px;
  font-weight: 650;
  cursor: pointer;
  user-select: none;
}

details dl,
.legacy-job-links,
.legacy-branch-list dl {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 5px 9px;
  margin: 0;
  padding: 0 9px 8px;
  font-size: 9px;
}

details dt,
.legacy-job-links dt,
.legacy-branch-list dt {
  color: var(--gray-400);
}

details dd,
.legacy-job-links dd,
.legacy-branch-list dd {
  min-width: 0;
  margin: 0;
  color: var(--gray-600);
  overflow-wrap: anywhere;
}

pre {
  max-height: 360px;
  margin: 0;
  padding: 0 9px 9px;
  overflow: auto;
  color: var(--gray-700);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.legacy-sending-row {
  display: flex;
  align-items: center;
  gap: 11px;
  color: var(--gray-500);
}

.legacy-sending-row > div {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
}

.legacy-thinking-dots {
  display: inline-flex;
  gap: 3px;
}

.legacy-thinking-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--main-color);
  animation: legacy-pulse 1.2s ease-in-out infinite;
}

.legacy-thinking-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.legacy-thinking-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

.legacy-job-list,
.legacy-branch-list {
  display: grid;
  gap: 9px;
}

.legacy-job-card,
.legacy-branch-list article {
  padding: 12px;
  border: 1px solid var(--gray-100);
  border-radius: 12px;
  background: var(--gray-0);
}

.legacy-job-card > header,
.legacy-branch-list article > header {
  display: flex;
  align-items: center;
  gap: 9px;
}

.legacy-job-icon,
.legacy-branch-list article > header > span {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border-radius: 8px;
  background: var(--main-50);
  color: var(--main-color);
}

.legacy-job-card > header > span:nth-child(2),
.legacy-branch-list article > header > div {
  display: grid;
  min-width: 0;
  gap: 1px;
  flex: 1;
}

.legacy-job-card header b,
.legacy-branch-list header b {
  color: var(--gray-800);
  font-size: 11px;
}

.legacy-job-card header small,
.legacy-branch-list header code {
  overflow: hidden;
  color: var(--gray-400);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.legacy-job-facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}

.legacy-job-facts span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border-radius: 6px;
  background: var(--gray-50);
  color: var(--gray-500);
  font-size: 9px;
}

.legacy-job-links,
.legacy-branch-list dl {
  margin-top: 9px;
  padding: 0;
}

.legacy-job-card .legacy-record-details {
  margin-top: 9px;
}

.legacy-job-card .legacy-record-details details {
  flex: 1 1 280px;
}

.legacy-branch-list article > details {
  margin-top: 8px;
}

.legacy-readonly-footer,
.legacy-composer-wrap {
  padding: 10px max(24px, calc((100% - 900px) / 2)) 16px;
  border-top: 1px solid var(--gray-100);
  background: color-mix(in srgb, var(--gray-0) 94%, transparent);
}

.legacy-readonly-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--gray-500);
  font-size: 10px;
}

.legacy-composer {
  display: flex;
  align-items: flex-end;
  gap: 9px;
  padding: 9px 9px 9px 13px;
  border: 1px solid var(--gray-200);
  border-radius: 14px;
  background: var(--gray-0);
  box-shadow: 0 9px 28px color-mix(in srgb, var(--gray-900) 7%, transparent);
}

.legacy-composer:focus-within {
  border-color: var(--main-300);
  box-shadow:
    0 0 0 3px var(--main-50),
    0 9px 28px color-mix(in srgb, var(--gray-900) 7%, transparent);
}

.legacy-composer.sending {
  opacity: 0.72;
}

.legacy-composer textarea {
  min-height: 27px;
  max-height: 132px;
  flex: 1;
  resize: vertical;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--gray-900);
  font: inherit;
  font-size: 13px;
  line-height: 1.65;
}

.legacy-composer button {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border: 0;
  border-radius: 10px;
  background: var(--main-color);
  color: #fff;
  cursor: pointer;
}

.legacy-composer button:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

.legacy-composer-wrap > small {
  display: block;
  margin-top: 6px;
  color: var(--gray-400);
  font-size: 9px;
  text-align: center;
}

.spin {
  animation: legacy-spin 1s linear infinite;
}

@keyframes legacy-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes legacy-pulse {
  0%,
  70%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  35% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

@media (max-width: 720px) {
  .legacy-session-header,
  .legacy-session-scroll,
  .legacy-inline-state,
  .legacy-archive-banner,
  .legacy-readonly-footer,
  .legacy-composer-wrap {
    padding-right: 14px;
    padding-left: 14px;
  }

  .legacy-session-header {
    gap: 10px;
  }

  .legacy-session-heading h2 {
    font-size: 16px;
  }

  .legacy-session-scroll {
    padding-top: 17px;
  }

  .legacy-message.user .legacy-message-content {
    max-width: 88%;
  }

  .legacy-message-meta code {
    display: none;
  }

  .legacy-job-facts span {
    max-width: 100%;
    overflow-wrap: anywhere;
  }
}

@media (prefers-reduced-motion: reduce) {
  .spin,
  .legacy-thinking-dots i {
    animation: none;
  }
}
</style>
