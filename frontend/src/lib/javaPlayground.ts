import lzString from 'lz-string'
import { javaSourceFileName } from './download'

export function javaPlaygroundUrl(source: string): string {
  const payload = { title: 'Dabba Java snippet', files: [{ path: javaSourceFileName(source), content: source }] }
  return `https://javafiddle.leaningtech.com/#${lzString.compressToEncodedURIComponent(JSON.stringify(payload))}`
}
