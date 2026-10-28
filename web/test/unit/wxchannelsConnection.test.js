import assert from 'node:assert/strict'
import test from 'node:test'
import { selectWechatConnection } from '../../src/utils/wechatConnection.js'

test('视频号复用直连微信，音频服务单独判断', () => {
  const state = {
    api_available: true,
    mcp_available: true,
    wechat_available: true,
    ffmpeg_available: true,
    asr_available: true
  }
  assert.equal(selectWechatConnection(state).ready, true)
  assert.equal(selectWechatConnection(state).mode, 'central')
  assert.equal(selectWechatConnection({ ...state, asr_available: false }).ready, false)
  assert.equal(selectWechatConnection({ ...state, proxy_ready: false }).sourceReady, false)
})

test('直连断开后只选择在线且就绪的个人视频设备', () => {
  const state = {
    asr_available: true,
    devices: [
      { device_id: 'offline', online: false, state: { channels_ready: true } },
      { device_id: 'online', online: true, state: { channels_ready: true, ffmpeg_available: true } }
    ]
  }
  assert.equal(selectWechatConnection(state).deviceId, 'online')
  assert.equal(selectWechatConnection(state).mode, 'personal')
  assert.equal(selectWechatConnection(state).ready, true)
  assert.equal(selectWechatConnection({ ...state, ffmpeg_available: false }).ready, false)
  assert.equal(selectWechatConnection({ ...state, asr_available: false }).ready, false)
  assert.equal(selectWechatConnection(null).sourceReady, false)
})

test('云端统一采集断线时保持云端模式，不复用用户的个人微信', () => {
  const state = selectWechatConnection({
    central_managed: true,
    asr_available: true,
    ffmpeg_available: true,
    devices: [{ device_id: 'private', online: true, state: { channels_ready: true } }]
  })
  assert.equal(state.managedCloud, true)
  assert.equal(state.mode, 'central')
  assert.equal(state.sourceReady, false)
  assert.equal(state.deviceId, undefined)
})

test('云端采集就绪后普通用户无需个人设备即可转录', () => {
  const state = selectWechatConnection({
    central_managed: true,
    api_available: true,
    mcp_available: true,
    wechat_available: true,
    proxy_ready: true,
    asr_available: true,
    ffmpeg_available: true,
    devices: []
  })
  assert.equal(state.mode, 'central')
  assert.equal(state.ready, true)
  assert.equal(state.deviceId, undefined)
})
