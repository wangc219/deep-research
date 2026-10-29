import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
import { fileURLToPath } from 'node:url'

// 构建时生成压缩副本，Nginx 按 Accept-Encoding 协商，避免逐请求重复压缩。
async function compressDirectory(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const filename = join(directory, entry.name)
    if (entry.isDirectory()) {
      await compressDirectory(filename)
      continue
    }
    if (!/\.(?:js|mjs|css|html|json|svg|wasm)$/.test(entry.name)) continue
    const source = await readFile(filename)
    if (source.length < 1024) continue
    const compressed = gzipSync(source, { level: 9 })
    if (compressed.length < source.length) await writeFile(`${filename}.gz`, compressed)
  }
}

await compressDirectory(fileURLToPath(new URL('../dist/', import.meta.url)))
