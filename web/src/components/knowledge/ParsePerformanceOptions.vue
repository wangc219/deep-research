<template>
  <div class="parse-performance">
    <label>
      <span>同时解析文件数</span>
      <a-select
        :value="modelValue.parse_concurrency ?? 2"
        :disabled="disabled"
        @change="update('parse_concurrency', $event)"
      >
        <a-select-option :value="1">1 · 节省资源</a-select-option>
        <a-select-option :value="2">2 · 均衡（推荐）</a-select-option>
        <a-select-option :value="4">4 · 快速</a-select-option>
      </a-select>
    </label>
    <label v-if="modelValue.ocr_engine === 'rapid_ocr'">
      <span>优先读取 PDF 文字层</span>
      <a-switch
        :checked="modelValue.prefer_text_layer ?? true"
        :disabled="disabled"
        @change="update('prefer_text_layer', $event)"
      />
    </label>
    <p>扫描页自动使用 OCR。复杂图表或文字层不完整时，可关闭文字层优先。</p>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])
const update = (key, value) => emit('update:modelValue', { ...props.modelValue, [key]: value })
</script>

<style scoped>
.parse-performance {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}
label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.ant-select {
  min-width: 160px;
}
p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
