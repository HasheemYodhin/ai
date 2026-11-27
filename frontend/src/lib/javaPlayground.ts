import lzString from 'lz-string'

function javaPlaygroundSource(source: string): string {
  // Ignore comments and literals while keeping source offsets for the edit.
  const code = source.replace(/\/\*[\s\S]*?\*\/|\/\/[^\r\n]*|"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, match => match.replace(/[^\r\n]/g, ' '))
  const declarations = /[{}]|(?<![\w$])((?:(?:public|final|abstract|sealed|non-sealed|strictfp)\s+)*)(?:class|record|enum|interface)\s+([A-Za-z_$][\w$]*)/g
  let depth = 0
  let firstType: string | undefined
  let hasMain = false
  let publicType: { name: string; offset: number } | undefined

  for (const match of code.matchAll(declarations)) {
    if (match[0] === '{') depth += 1
    else if (match[0] === '}') depth -= 1
    else if (depth === 0) {
      const [, modifiers, name] = match
      firstType ??= name
      hasMain ||= name === 'Main'
      const publicOffset = modifiers.search(/\bpublic\b/)
      if (publicOffset >= 0) publicType ??= { name, offset: match.index + publicOffset }
    }
  }

  // JavaFiddle opens and runs Main.java. Keep the original type name and delegate from Main.
  const entryType = publicType?.name ?? firstType
  if (!entryType || entryType === 'Main') return source
  const content = publicType
    ? source.slice(0, publicType.offset) + source.slice(publicType.offset + 'public'.length)
    : source
  if (hasMain) return content
  return `${content}\n\nclass Main {\n    public static void main(String[] args) throws Throwable {\n        ${entryType}.main(args);\n    }\n}\n`
}

export function javaPlaygroundUrl(source: string): string {
  const payload = { title: 'Dabba Java snippet', files: [{ path: 'Main.java', content: javaPlaygroundSource(source) }] }
  return `https://javafiddle.leaningtech.com/#${lzString.compressToEncodedURIComponent(JSON.stringify(payload))}`
}
