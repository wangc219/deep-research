import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import test from 'node:test'

import { verifyDistAssets } from '../../scripts/verify-dist-assets.mjs'

const withFixture = async (callback) => {
  const root = await mkdtemp(join(tmpdir(), 'deepquest-dist-assets-'))
  try {
    await callback(root)
  } finally {
    await rm(root, { force: true, recursive: true })
  }
}

test('accepts a complete Vite asset graph', async () => {
  await withFixture(async (root) => {
    await mkdir(join(root, 'assets'))
    await writeFile(join(root, 'index.html'), '<script src="/assets/index-a.js"></script>')
    await writeFile(join(root, 'assets/index-a.js'), 'const deps=[`assets/chunk-b.js`];')
    await writeFile(join(root, 'assets/chunk-b.js'), 'export const ready=true')

    const result = await verifyDistAssets(root)
    assert.equal(result.checkedReferences, 2)
  })
})

test('rejects a renamed asset directory with stale Vite dependency paths', async () => {
  await withFixture(async (root) => {
    await mkdir(join(root, 'assets-v6'))
    await writeFile(join(root, 'index.html'), '<script src="/assets-v6/index-a.js"></script>')
    await writeFile(join(root, 'assets-v6/index-a.js'), 'const deps=[`assets/chunk-b.js`];')
    await writeFile(join(root, 'assets-v6/chunk-b.js'), 'export const ready=true')

    await assert.rejects(
      verifyDistAssets(root),
      /assets\/chunk-b\.js/
    )
  })
})

test('ignores query strings while validating referenced files', async () => {
  await withFixture(async (root) => {
    await mkdir(join(root, 'assets'))
    await writeFile(join(root, 'index.html'), '<link href="/assets/app.css?v=7#theme">')
    await writeFile(join(root, 'assets/app.css'), 'body { color: black; }')

    const result = await verifyDistAssets(root)
    assert.equal(result.checkedReferences, 1)
  })
})
