/**
 * Captures a single frame from the browser's native screen/window/tab picker
 * (getDisplayMedia) and returns it as a PNG data URL. The user picks what to
 * share via the browser's own UI — we never have access to anything they
 * didn't explicitly select.
 */
export async function captureScreenshot(): Promise<string> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error('Screen capture is not supported in this browser')
  }

  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true })
  try {
    const video = document.createElement('video')
    video.srcObject = stream
    await video.play()
    // Give the video element a tick to report real dimensions.
    await new Promise<void>(resolve => {
      if (video.videoWidth > 0) return resolve()
      video.onloadedmetadata = () => resolve()
    })

    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas context unavailable')
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    return canvas.toDataURL('image/png')
  } finally {
    stream.getTracks().forEach(t => t.stop())
  }
}
