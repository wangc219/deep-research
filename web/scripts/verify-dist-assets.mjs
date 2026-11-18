import { access, readFile, readdir, stat } from 'node:fs/promises'
import { join, normalize, relative, resolve } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const TEXT_ASSET_EXTENSIONS = new Set(['.css', '.html', '.js', '.json', '.mjs', '.svg'])
const ASSET_REFERENCE_PATTERN = /(?:^|["'`()=:\s])\/?(assets(?:-[A-Za-z0-9._-]+)?\/[A-Za-z0-9_@./%+?=&-]*)/g

const extensionOf = (filename) => {
  const basename = filename.split('/').at(-1) || ''
  const dot = basename.lastIndexOf('.')
  return dot < 0 ? '' : basename.slice(dot)
}

const collectTextFiles = async (directory) => {
  const files = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const filename = join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...await collectTextFiles(filename))
      continue
    }
    if (entry.name.endsWith('.gz')) continue
    if (TEXT_ASSET_EXTENSIONS.has(extensionOf(entry.name))) files.push(filename)
  }
  return files
}

const referencedAssetPaths = (source) => {
  const references = new Set()
  for (const match of source.matchAll(ASSET_REFERENCE_PATTERN)) {
    const path = decodeURIComponent(match[1].split(/[?#]/, 1)[0])
    if (path) references.add(path)
  }
  return references
}

const assertWithinRoot = (root, filename) => {
  const target = resolve(root, normalize(filename))
  const relativePath = relative(root, target)
  if (relativePath.startsWith('..') || relativePath === '') {
    throw new Error(`非法静态资源路径：${filename}`)
  }
  return target
}

export const verifyDistAssets = async (distDirectory) => {
  const root = resolve(distDirectory)
  await access(join(root, 'index.html'))

  const missing = []
  const checked = new Set()
  for (const sourceFile of await collectTextFiles(root)) {
    const source = await readFile(sourceFile, 'utf8')
    for (const assetPath of referencedAssetPaths(source)) {
      const target = assertWithinRoot(root, assetPath)
      const key = `${relative(root, sourceFile)} -> ${assetPath}`
      try {
        await stat(target)
        checked.add(assetPath)
      } catch {
        missing.push(key)
      }
    }
  }

  if (missing.length > 0) {
    throw new Error(`构建产物引用了不存在的静态资源：\n${missing.sort().join('\n')}`)
  }
  return { checkedReferences: checked.size }
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : ''
if (invokedPath === fileURLToPath(import.meta.url)) {
  const distDirectory = resolve(process.argv[2] || fileURLToPath(new URL('../dist/', import.meta.url)))
  const result = await verifyDistAssets(distDirectory)
  console.log(`静态资源完整性校验通过：${result.checkedReferences} 个唯一引用`)
}
