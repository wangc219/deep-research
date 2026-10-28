<template>
  <section class="failed-retry-card" aria-label="抽取失败恢复">
    <div class="failed-retry-copy">
      <span class="failed-retry-icon" aria-hidden="true">
        <RotateCcw :size="16" />
      </span>
      <div>
        <strong>抽取失败恢复</strong>
        <p>仅重跑 {{ count }} 个失败 Chunk，不影响已构建数据。</p>
      </div>
    </div>
    <a-button
      size="small"
      type="primary"
      danger
      :loading="loading"
      :disabled="disabled || count <= 0"
      @click="$emit('retry')"
    >
      {{ disabled ? '构建中' : `重跑失败项 (${count})` }}
    </a-button>
  </section>
</template>

<script setup>
import { RotateCcw } from '@lucide/vue'

defineProps({
  count: {
    type: Number,
    default: 0
  },
  loading: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  }
})

defineEmits(['retry'])
</script>

<style scoped lang="less">
.failed-retry-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--color-error-200, #ffccc7);
  border-radius: 8px;
  background: var(--color-error-50, #fff2f0);
}

.failed-retry-copy {
  display: flex;
  align-items: flex-start;
  min-width: 0;
  gap: 8px;

  strong {
    display: block;
    color: var(--gray-900);
    font-size: 12px;
  }

  p {
    margin: 2px 0 0;
    color: var(--gray-600);
    font-size: 11px;
    line-height: 1.4;
  }
}

.failed-retry-icon {
  display: inline-flex;
  flex: none;
  margin-top: 1px;
  color: var(--color-error-600, #cf1322);
}

@media (max-width: 720px) {
  .failed-retry-card {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
