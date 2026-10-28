<template>
  <a-result status="warning" title="页面暂时加载失败" sub-title="请刷新页面重试，已有任务会继续在后台执行。">
    <template #extra><a-button type="primary" @click="reload">刷新页面</a-button></template>
  </a-result>
</template>
<script setup>
const reload = () => window.location.reload()
</script>
