export function selectWechatConnection(video) {
  const device = (video?.devices || []).find((item) => item.online && item.state?.channels_ready)
  const direct = !!(
    video?.api_available &&
    video?.mcp_available &&
    video?.wechat_available &&
    video?.proxy_ready !== false
  )
  const managedCloud = video?.central_managed === true
  const sourceReady = direct || (!managedCloud && !!device)
  const mode = direct || managedCloud ? 'central' : 'personal'
  return {
    mode,
    managedCloud,
    deviceId: mode === 'personal' ? device?.device_id : undefined,
    sourceReady,
    contentReady: sourceReady,
    message: video?.message,
    ready:
      sourceReady &&
      !!(
        video?.asr_available &&
        video.ffmpeg_available !== false &&
        (direct ? video.ffmpeg_available : device?.state?.ffmpeg_available !== false)
      ),
    video
  }
}
