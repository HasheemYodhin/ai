/**
 * In-browser OCR fallback. Used when the selected model can't see images —
 * we extract text from the image with Tesseract and feed that to the model
 * instead. tesseract.js is heavy (~a few MB + a language worker), so it is
 * lazy-imported only when OCR actually runs.
 */

/** Read a File into a base64 data URL (used for both display and vision send). */
export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file'))
    reader.readAsDataURL(file)
  })
}

/** OCR a single image (data URL or blob URL). Returns extracted text, trimmed. */
export async function ocrImage(
  image: string,
  onProgress?: (pct: number) => void,
): Promise<string> {
  const { createWorker } = await import('tesseract.js')
  const worker = await createWorker('eng', undefined, {
    logger: onProgress
      ? (m: { status: string; progress: number }) => {
          if (m.status === 'recognizing text') onProgress(Math.round(m.progress * 100))
        }
      : undefined,
  })
  try {
    const { data } = await worker.recognize(image)
    return (data.text ?? '').trim()
  } finally {
    await worker.terminate()
  }
}

/** OCR several images and return their combined text, separated per image. */
export async function ocrImages(
  images: string[],
  onProgress?: (pct: number) => void,
): Promise<string> {
  const parts: string[] = []
  for (let i = 0; i < images.length; i++) {
    const text = await ocrImage(images[i], onProgress)
    parts.push(images.length > 1 ? `--- Image ${i + 1} ---\n${text}` : text)
  }
  return parts.join('\n\n')
}
