export const downloadBlob = (blob, filename) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
    // WebKit 的下载接管发生在 click 返回之后，不能在同一调用栈撤销 URL。
    window.setTimeout(() => window.URL.revokeObjectURL(url), 60_000)
  }
}
