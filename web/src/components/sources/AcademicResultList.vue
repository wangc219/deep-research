<script setup>
import { ACADEMIC_LEVEL_LABELS, academicSourceUrl } from '@/utils/aminer'

defineProps({ results: { type: Array, default: () => [] } })
</script>

<template>
  <div class="academic-results">
    <article
      v-for="(paper, index) in results"
      :key="paper.doi || paper.id || index"
      class="paper-card"
    >
      <div class="paper-heading">
        <a
          v-if="academicSourceUrl(paper.url)"
          :href="academicSourceUrl(paper.url)"
          target="_blank"
          rel="noopener noreferrer"
          >{{ paper.title }}</a
        >
        <strong v-else>{{ paper.title }}</strong>
        <span class="level">{{ ACADEMIC_LEVEL_LABELS[paper.content_level] || '题录' }}</span>
      </div>
      <p v-if="paper.title_zh && paper.title_zh !== paper.title" class="translated-title">
        {{ paper.title_zh }}
      </p>
      <div class="paper-meta">
        <span v-if="paper.authors?.length">{{ paper.authors.join('、') }}</span>
        <span v-if="paper.year">{{ paper.year }}</span
        ><span v-if="paper.venue">{{ paper.venue }}</span>
      </div>
      <div class="identifiers">
        <span>AMiner</span><span v-if="paper.doi">DOI：{{ paper.doi }}</span
        ><span v-if="paper.citation_bucket">被引档位：{{ paper.citation_bucket }}</span>
      </div>
      <details v-if="paper.content" class="abstract">
        <summary>展开{{ ACADEMIC_LEVEL_LABELS[paper.content_level] || '摘要' }}</summary>
        <p>{{ paper.content }}</p>
      </details>
      <p v-else class="no-abstract">仅题录，暂无摘要</p>
    </article>
  </div>
</template>

<style scoped lang="less">
.academic-results {
  display: grid;
  gap: 10px;
}
.paper-card {
  padding: 14px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-0);
  overflow-wrap: anywhere;
}
.paper-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  justify-content: space-between;
  font-size: 14px;
  line-height: 1.5;
}
a {
  color: var(--main-color);
  font-weight: 500;
  text-decoration: none;
}
a:hover {
  text-decoration: underline;
}
.level {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--gray-100);
  color: var(--gray-700);
  font-size: 11px;
}
.translated-title,
.paper-meta,
.identifiers,
.no-abstract {
  margin: 8px 0 0;
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.5;
}
.paper-meta,
.identifiers {
  display: flex;
  gap: 8px 12px;
  flex-wrap: wrap;
}
.abstract {
  margin-top: 12px;
  font-size: 12px;
}
summary {
  cursor: pointer;
  color: var(--main-color);
}
.abstract p {
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--gray-800);
  white-space: pre-wrap;
}
@media (max-width: 480px) {
  .paper-heading {
    flex-direction: column;
    gap: 6px;
  }
}
</style>
