<template>
  <div class="agent-composer" :class="{ 'has-extra': showExtra && $slots.extra }">
    <div v-if="showExtra && $slots.extra" class="composer-extra-region" aria-label="对话上下文">
      <slot name="extra"></slot>
    </div>

    <div
      v-if="visibleSlashCommands.length"
      class="slash-command-palette"
      role="listbox"
      aria-label="对话命令"
      @mousedown.prevent
    >
      <div class="slash-command-heading"><Slash :size="13" />输入 / 调用命令</div>
      <button
        v-for="(command, index) in visibleSlashCommands"
        :key="command.id || command.command"
        type="button"
        role="option"
        :aria-selected="index === slashSelectedIndex"
        :class="{ active: index === slashSelectedIndex }"
        @mouseenter="slashSelectedIndex = index"
        @click="selectSlashCommand(command)"
      >
        <code>{{ command.command }}</code>
        <span><b>{{ command.label }}</b><small>{{ command.detail }}</small></span>
      </button>
    </div>

    <MessageInputComponent
      ref="inputRef"
      :model-value="modelValue"
      @update:modelValue="updateValue"
      :is-loading="isLoading"
      :disabled="disabled"
      :send-button-disabled="sendButtonDisabled"
      :placeholder="placeholder"
      :mention="mention"
      :thread-id="threadId"
      :file-upload-enabled="supportsFileUpload"
      :show-options-left="showInputOptions"
      @send="handleSend"
      @keydown="handleKeyDown"
      @paste-image="handlePastedImage"
      @drop-files="handleDroppedFiles"
    >
      <template #top>
        <div v-if="currentImage || previewAttachments.length" class="input-top-stack">
          <ImagePreviewComponent
            v-if="currentImage"
            :image-data="currentImage"
            @remove="handleImageRemoved"
            class="image-preview-wrapper"
          />

          <div v-if="previewAttachments.length" class="attachment-preview-list">
            <div
              v-for="attachment in previewAttachments"
              :key="attachment.fileId"
              class="attachment-file-card"
            >
              <div class="attachment-file-icon">
                <FileTypeIcon :name="attachment.name" :size="18" />
              </div>
              <div class="attachment-file-body">
                <div class="attachment-file-name" :title="attachment.name">
                  {{ attachment.name }}
                </div>
                <div class="attachment-file-meta">{{ attachment.meta }}</div>
              </div>
              <button
                class="attachment-remove-btn"
                type="button"
                :aria-label="`移除附件 ${attachment.name}`"
                @click.stop="handleAttachmentRemoved(attachment)"
              >
                <X :size="14" />
              </button>
            </div>
          </div>
        </div>
      </template>
      <template #options-left>
        <AttachmentOptionsComponent
          :disabled="disabled"
          :file-upload-enabled="supportsFileUpload"
          :mention="mention"
          @upload="handleAttachmentUpload"
          @upload-image="handleImageUpload"
          @upload-image-success="handleImageUploadSuccess"
          @select-mention="handleMentionSelect"
        />
      </template>
      <template #actions-left>
        <div class="input-actions-left">
          <slot name="actions-left-extra"></slot>
        </div>
      </template>
      <template #actions-right>
        <div class="input-actions-right">
          <slot name="actions-right-extra"></slot>
        </div>
      </template>
    </MessageInputComponent>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import MessageInputComponent from '@/components/MessageInputComponent.vue'
import ImagePreviewComponent from '@/components/ImagePreviewComponent.vue'
import AttachmentOptionsComponent from '@/components/AttachmentOptionsComponent.vue'
import { Slash, X } from '@lucide/vue'
import { filterSlashCommands } from '@/utils/slashCommands'
import { normalizeAttachmentPreviews } from '@/utils/file_utils'
import { uploadMultimodalImage } from '@/utils/multimodal_image_upload'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  sendButtonDisabled: { type: Boolean, default: false },
  mention: { type: Object, default: () => null },
  threadId: { type: String, default: '' },
  showExtra: { type: Boolean, default: false },
  supportsFileUpload: { type: Boolean, default: false },
  slashCommands: { type: Array, default: () => [] },
  attachments: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'keydown',
  'upload-attachment',
  'remove-attachment'
])

const inputRef = ref(null)
const currentImage = ref(null)
const slashSelectedIndex = ref(0)
const placeholder = '问点什么？使用 @ 可以选择文件、知识库或技能进行引用。'

const previewAttachments = computed(() => normalizeAttachmentPreviews(props.attachments))
const showInputOptions = computed(
  () =>
    props.supportsFileUpload ||
    Boolean(props.mention?.knowledgeBases?.length) ||
    Boolean(props.mention?.skills?.length)
)
const visibleSlashCommands = computed(() =>
  filterSlashCommands(props.modelValue, props.slashCommands)
)
const exactSlashCommand = computed(() => {
  const value = String(props.modelValue || '').trim()
  return props.slashCommands.find((item) => String(item?.command || '') === value) || null
})

watch(
  () => props.modelValue,
  () => {
    slashSelectedIndex.value = 0
  }
)

const updateValue = (val) => {
  emit('update:modelValue', val)
}

const handleAttachmentUpload = (files = []) => {
  emit('upload-attachment', files)
}

const handleImageUpload = (imageData) => {
  if (imageData && imageData.success) {
    currentImage.value = imageData
  }
}

const handlePastedImage = async (file) => {
  if (props.disabled || !props.supportsFileUpload) return

  try {
    const imageData = await uploadMultimodalImage(file)
    handleImageUpload(imageData)
  } catch (error) {
    console.error('图片上传失败:', error)
  }
}

const handleDroppedFiles = (files = []) => {
  if (props.disabled || !props.supportsFileUpload || !files.length) return
  handleAttachmentUpload(files)
}

const handleImageUploadSuccess = () => {
  if (inputRef.value) {
    inputRef.value.closeOptions()
  }
}

const handleMentionSelect = (item) => {
  inputRef.value?.insertMention(item)
  inputRef.value?.closeOptions()
}

const selectSlashCommand = async (command) => {
  const value = String(command?.command || '').trim()
  if (!value) return
  emit('update:modelValue', `${value} `)
  slashSelectedIndex.value = 0
  await nextTick()
  inputRef.value?.focus()
}

const handleImageRemoved = () => {
  currentImage.value = null
}

// 发送被后端拒绝时把旧图片恢复到输入区，覆盖等待期间可能新选的图片，
// 避免旧图片被悄悄丢弃；用户可重新选择新图片。
const restoreImage = (image) => {
  currentImage.value = image || null
}

const handleAttachmentRemoved = (attachment) => {
  emit('remove-attachment', attachment.raw)
}

const handleSend = () => {
  emit('send', { image: currentImage.value })
  currentImage.value = null
}

const handleKeyDown = (e) => {
  if (visibleSlashCommands.value.length) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      slashSelectedIndex.value =
        (slashSelectedIndex.value + 1) % visibleSlashCommands.value.length
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      slashSelectedIndex.value =
        (slashSelectedIndex.value - 1 + visibleSlashCommands.value.length) %
        visibleSlashCommands.value.length
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      emit('update:modelValue', '')
      return
    }
    if ((e.key === 'Enter' || e.key === 'Tab') && !exactSlashCommand.value) {
      e.preventDefault()
      const command =
        visibleSlashCommands.value[slashSelectedIndex.value] || visibleSlashCommands.value[0]
      void selectSlashCommand(command)
      return
    }
  }

  if (props.sendButtonDisabled) {
    return
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else {
    emit('keydown', e)
  }
}

defineExpose({
  focus: () => inputRef.value?.focus(),
  startMention: (group) => inputRef.value?.startMention(group),
  closeOptions: () => inputRef.value?.closeOptions(),
  restoreImage
})
</script>

<style lang="less" scoped>
@import '@/components/composerStyles.less';

.agent-composer {
  position: relative;
  width: 100%;
}

.slash-command-palette {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 20;
  display: grid;
  max-height: min(360px, 48vh);
  padding: 7px;
  overflow-y: auto;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-0);
  box-shadow: 0 16px 42px color-mix(in srgb, var(--gray-1000) 16%, transparent);
}

.slash-command-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 7px 7px;
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 600;
}

.slash-command-palette > button {
  display: grid;
  width: 100%;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 8px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--gray-700);
  text-align: left;
  cursor: pointer;
}

.slash-command-palette > button:hover,
.slash-command-palette > button.active {
  background: var(--main-50);
  color: var(--main-700);
}

.slash-command-palette code {
  color: var(--main-color);
  font-size: 12px;
  font-weight: 700;
}

.slash-command-palette button > span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.slash-command-palette b {
  color: var(--gray-850, var(--gray-900));
  font-size: 12px;
}

.slash-command-palette small {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 10px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-extra-region {
  .composer-top-attachment();
  display: flex;
  min-height: 36px;
  align-items: flex-start;
  gap: 6px;
  overflow-x: auto;
  padding: 4px 14px 2px;
}

.agent-composer.has-extra :deep(.input-box) {
  z-index: 1;
}

.input-actions-left {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}

.input-actions-right {
  display: flex;
  align-items: center;
  margin-right: 8px;
  gap: 2px;
}

.input-top-stack {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}

.attachment-preview-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.attachment-file-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  width: 220px;
  min-width: 0;
  padding: 10px 34px 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-0);
  box-shadow: 0 1px 4px var(--shadow-0);
}

.attachment-file-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--main-700);
  background: var(--main-30);
}

.attachment-file-body {
  min-width: 0;
}

.attachment-file-name {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-file-meta {
  margin-top: 2px;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.3;
}

.attachment-remove-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--gray-0);
  background: var(--gray-900);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    transform 0.15s ease;

  &:hover {
    background: var(--gray-700);
  }

  &:active {
    transform: scale(0.96);
  }
}

// 输入框操作按钮通用样式（穿透到 slot 内容）
:deep(.input-action-btn) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  height: 30px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--gray-600);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  background: transparent;
  border: none;

  &:hover {
    color: var(--gray-900);
    background: var(--gray-50);
  }

  &.active {
    color: var(--gray-900);
    background: var(--gray-100);
    font-weight: 500;
  }

  &.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }

  span {
    line-height: 1;
  }
}

// slot 内容的 hide-text 响应式样式
:deep(.hide-text) {
  @media (max-width: 768px) {
    display: none;
  }
}

@media (max-width: 768px) {
  .input-top-stack {
    gap: 8px;
    margin-bottom: 10px;
  }

  .attachment-file-card {
    width: min(220px, 100%);
  }

  .slash-command-palette > button {
    grid-template-columns: 80px minmax(0, 1fr);
  }
}
</style>
