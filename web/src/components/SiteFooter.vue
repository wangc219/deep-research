<template>
  <footer class="site-footer" aria-label="网站备案信息">
    <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">
      皖ICP备2026035589号
    </a>
  </footer>
</template>

<style scoped>
.site-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--site-footer-height);
  padding: 6px 16px calc(6px + env(safe-area-inset-bottom, 0px));
  background: var(--gray-0);
  color: var(--gray-700);
  font-size: 12px;
  line-height: 20px;
  text-align: center;
}

.site-footer a {
  color: inherit;
  text-decoration: none;
}

.site-footer a:hover {
  text-decoration: underline;
}

.site-footer a:focus-visible {
  outline: 2px solid var(--main-500);
  outline-offset: 3px;
  border-radius: 2px;
}
</style>
