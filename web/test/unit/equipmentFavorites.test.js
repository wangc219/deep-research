import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  favoriteDimensions,
  favoriteDisplayRow,
  favoriteModules,
  favoriteSourceUnavailable
} from '../../src/utils/equipmentFavorites.js'

test('收藏快照与服务端可编辑字段合并时以服务端字段为准', () => {
  const row = favoriteDisplayRow({
    favorite_id: 'favorite-1',
    display_name: '',
    note: '服务端备注',
    tags: ['重点'],
    snapshot: { display_name: '旧名称', note: '旧备注', name: '能力卡' }
  })
  assert.equal(row.favorite_id, 'favorite-1')
  assert.equal(row.display_name, '')
  assert.equal(row.note, '服务端备注')
  assert.deepEqual(row.tags, ['重点'])
  assert.equal(row.name, '能力卡')
})

test('收藏五栏优先读取结构化模块并兼容旧画像正文', () => {
  assert.deepEqual(
    favoriteModules({ capability_portrait_modules: { overview: '结构化概述', winning_logic: '结构化机理' } }),
    [
      { key: 'overview', label: '概述', text: '结构化概述' },
      { key: 'winning_logic', label: '制胜逻辑机理', text: '结构化机理' }
    ]
  )
  const legacy = favoriteModules({ capability_image: '概述：旧概述\n装备与技术实现：旧实现\n制胜逻辑：旧机理' })
  assert.deepEqual(legacy.map((item) => item.text), ['旧概述', '旧实现', '旧机理'])
})

test('收藏维度去重且删除来源仍保留快照阅读语义', () => {
  assert.deepEqual(
    favoriteDimensions({ primary_dimension: '制空', secondary_dimensions: ['制空', '侦察'] }),
    ['制空', '侦察']
  )
  assert.equal(favoriteSourceUnavailable({ source_status: 'deleted' }), true)
  assert.equal(favoriteSourceUnavailable({ source_status: 'archived' }), false)
})

test('Vue 收藏页使用权威分页 CRUD 接口并成为正式收藏路由', () => {
  const view = readFileSync(new URL('../../src/views/equipment/EquipmentFavoritesView.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../../src/apis/equipment_api.js', import.meta.url), 'utf8')
  const router = readFileSync(new URL('../../src/router/index.js', import.meta.url), 'utf8')
  assert.match(view, /listFavoriteCards/)
  assert.match(view, /updateFavoriteCard/)
  assert.match(view, /deleteFavoriteCard/)
  assert.match(view, /favoriteModules/)
  assert.match(api, /\/api\/equipment\/favorites/)
  assert.match(api, /createFavoriteCard/)
  assert.match(router, /name: 'EquipmentFavorites',[\s\S]*?EquipmentFavoritesView\.vue/)
})

test('收藏详情将翻栏操作收进弹窗底部并避免窄屏越界', () => {
  const view = readFileSync(new URL('../../src/views/equipment/EquipmentFavoritesView.vue', import.meta.url), 'utf8')
  const reader = view.match(/<article class="reader"[\s\S]*?<\/article>/)?.[0] || ''

  assert.match(reader, /<footer class="reader-actions"/)
  assert.match(reader, /class="reader-nav previous"/)
  assert.match(reader, /class="reader-nav next"/)
  assert.match(view, /\.reader-nav\{position:static/)
  assert.match(view, /\.reader\{grid-template-rows:auto minmax\(0,1fr\) auto\}/)
})
