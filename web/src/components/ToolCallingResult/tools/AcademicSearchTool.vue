<script setup>
import { computed } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'
import AcademicResultList from '@/components/sources/AcademicResultList.vue'
import { parseAcademicResult } from '@/utils/aminer'
import { getToolCallId, getToolName, parseToolCallArgs } from '../toolRegistry'

const props = defineProps({
  toolCall: { type: Object, required: true },
  appearance: { type: String, default: 'card' },
  defaultExpanded: { type: Boolean, default: false }
})
const query = computed(() => parseToolCallArgs(props.toolCall)?.query || '')
</script>

<template>
  <BaseToolCall
    :tool-call="toolCall"
    :appearance="appearance"
    :default-expanded="defaultExpanded"
    :hide-params="true"
  >
    <template #header
      ><span>{{ getToolName(getToolCallId(toolCall)) }}</span
      ><span v-if="query" class="query">{{ query }}</span></template
    >
    <template #result="{ resultContent }">
      <div class="academic-tool-result">
        <p v-if="parseAcademicResult(resultContent).relation === 'references'" class="notice">
          以下是该论文引用的参考文献，非后续引用者列表。
        </p>
        <p v-if="parseAcademicResult(resultContent).message" class="notice" role="status">
          {{ parseAcademicResult(resultContent).message }}
        </p>
        <AcademicResultList
          v-if="parseAcademicResult(resultContent).results?.length"
          :results="parseAcademicResult(resultContent).results"
        />
        <p v-else-if="parseAcademicResult(resultContent).status === 'ok'" class="empty">
          未找到相关论文或可用参考文献
        </p>
        <p v-if="parseAcademicResult(resultContent).cached" class="notice">检索命中缓存</p>
      </div>
    </template>
    <template #error="{ resultContent, errorMessage }">
      <p class="notice" role="alert">
        {{
          parseAcademicResult(resultContent).message ||
          errorMessage ||
          '论文检索暂不可用，请使用已有证据继续回答'
        }}
      </p>
    </template>
  </BaseToolCall>
</template>

<style scoped lang="less">
.query {
  margin-left: 12px;
  color: var(--gray-600);
  font-size: 12px;
}
.notice,
.empty {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--gray-600);
  line-height: 1.6;
}
.empty {
  padding: 12px;
  text-align: center;
}
</style>
