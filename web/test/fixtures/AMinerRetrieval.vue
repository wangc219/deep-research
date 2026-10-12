<script setup>
// 合成界面验收：只展示生产工具组件，不调用 AMiner 或发送会话。
import ToolCallRenderer from '@/components/ToolCallingResult/ToolCallRenderer.vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { useThemeStore } from '@/stores/theme'
const theme = useThemeStore()
const paper = {
  id: 'fixture-paper',
  doi: '10.48550/arXiv.1706.03762',
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani', 'Noam Shazeer'],
  year: 2017,
  venue: 'NeurIPS',
  url: 'https://doi.org/10.48550/arXiv.1706.03762',
  content_level: 'abstract',
  content: '合成验收摘要：本卡片用于验证展示层级、摘要展开和来源跳转，不代表本次实际检索结果。'
}
const calls = [
  {
    name: 'academic_search',
    args: { query: 'Transformer attention mechanism' },
    tool_call_result: {
      content: {
        status: 'ok',
        results: [
          paper,
          {
            ...paper,
            id: 'metadata',
            doi: '',
            title: '仅题录样例：缺失摘要',
            content: '',
            content_level: 'metadata'
          }
        ]
      }
    }
  },
  {
    name: 'academic_get_references',
    args: { paper_id: paper.id },
    tool_call_result: {
      content: {
        status: 'partial',
        relation: 'references',
        message: '参考文献预算已用尽，保留已有证据并使用网页或知识库补证',
        results: [paper]
      }
    }
  },
  {
    name: 'academic_search',
    tool_call_result: {
      content: {
        status: 'auth_failed',
        message: 'AMiner 鉴权失败，请检查用户 ID、API Key 和接口权限',
        results: []
      }
    }
  },
  { name: 'academic_search', tool_call_result: { content: { status: 'ok', results: [] } } },
  { name: 'academic_get_papers', args: { paper_ids: ['fixture-paper'] } }
]
</script>
<template>
  <main>
    <h1>AMiner 学术检索 · 合成界面验收</h1>
    <p>使用真实论文组件；以下数据为测试夹具，未请求供应商。</p>
    <button @click="theme.toggleTheme()">切换浅色 / 深色</button>
    <MarkdownPreview
      content='引用跳转验收：论文来源引用<cite source="https://doi.org/10.48550/arXiv.1706.03762" type="url">1</cite>，DOI 缩写引用<cite source="10.48550/arXiv.2205.14135" type="url">2</cite>。'
    />
    <ToolCallRenderer
      v-for="(call, index) in calls"
      :key="index"
      :tool-call="call"
      :default-expanded="true"
    />
  </main>
</template>
<style scoped>
main {
  max-width: 1000px;
  margin: auto;
  padding: 24px;
  color: var(--gray-900);
}
h1 {
  font-size: 20px;
}
p {
  font-size: 13px;
  margin-bottom: 16px;
  color: var(--gray-600);
}
button {
  padding: 8px 12px;
  margin-bottom: 16px;
  color: var(--gray-900);
  background: var(--gray-0);
  border: 1px solid var(--gray-300);
  border-radius: 6px;
}
</style>
