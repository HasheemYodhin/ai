import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
  },
  resolve: {
    alias: {
      // Real `vscode` module only exists inside the Extension Host — swap in
      // test/mocks/vscode.ts for unit tests. Integration tests that need the
      // real API belong in @vscode/test-electron instead, not here.
      vscode: path.resolve(__dirname, 'test/mocks/vscode.ts'),
    },
  },
});
