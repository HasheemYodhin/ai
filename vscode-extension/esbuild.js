// Bundles src/extension.ts + everything it imports into a single
// out/extension.js, instead of tsc's previous one-output-file-per-module
// behavior. Reduces both extension activation time (one require() instead
// of N) and .vsix size. Type-checking is no longer esbuild's job — that's
// what `npm run check-types` (tsc --noEmit) is for; esbuild only transpiles.
const esbuild = require('esbuild');

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

async function main() {
  const ctx = await esbuild.context({
    entryPoints: ['src/extension.ts'],
    bundle: true,
    format: 'cjs',
    minify: production,
    sourcemap: !production,
    sourcesContent: false,
    platform: 'node',
    outfile: 'out/extension.js',
    // The real `vscode` module only exists inside the Extension Host at
    // runtime — never bundle it, just leave the require() call as-is.
    external: ['vscode'],
    logLevel: 'info',
  });

  if (watch) {
    await ctx.watch();
  } else {
    await ctx.rebuild();
    await ctx.dispose();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
