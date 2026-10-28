/** 逐文件提交，保留暂存结果，重试时只处理未成功的文件。 */
export async function importWorkspaceSelection({ kbId, paths, staged, upload, submit, onSubmitted }) {
  const succeeded = []
  const failed = []
  for (const path of paths) {
    const key = JSON.stringify([kbId, path])
    try {
      let item = staged.get(key)
      if (!item) {
        const response = await upload(kbId, [path])
        item = response.items?.[0]
        if (!item?.file_path || !item.content_hash) throw new Error('文件暂存失败，请重试')
        staged.set(key, item)
      }
      const result = await submit(kbId, [item.file_path], {
        content_type: 'file', auto_index: true,
        content_hashes: { [item.file_path]: item.content_hash },
        file_sizes: { [item.file_path]: item.size }
      })
      succeeded.push(path)
      staged.delete(key)
      onSubmitted(result)
    } catch (error) {
      failed.push({ path, error: error.message || '提交失败，请重试' })
    }
  }
  return { succeeded, failed }
}
