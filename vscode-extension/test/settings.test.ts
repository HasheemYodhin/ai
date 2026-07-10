import { describe, it, expect, vi, beforeEach } from 'vitest';
import { workspace } from './mocks/vscode';
import { SettingsManager } from '../src/settings';

function makeContext() {
  const store = new Map<string, string>();
  return {
    secrets: {
      get: vi.fn(async (key: string) => store.get(key)),
      store: vi.fn(async (key: string, value: string) => { store.set(key, value); }),
      delete: vi.fn(async (key: string) => { store.delete(key); }),
    },
  } as unknown as import('vscode').ExtensionContext;
}

describe('SettingsManager', () => {
  beforeEach(() => {
    workspace.getConfiguration = vi.fn((_section?: string) => ({
      get: (_key: string, defaultValue: unknown) => defaultValue,
    })) as typeof workspace.getConfiguration;
  });

  it('returns defaults when no configuration is set', () => {
    const settings = new SettingsManager(makeContext());
    expect(settings.getSettings()).toEqual({
      apiEndpoint: 'http://localhost:8080',
      model: 'dabba',
      effort: 'medium',
      maxTokens: 4096,
      temperature: 0.7,
      autoReviewOnSave: false,
      enableDiagnostics: true,
      theme: 'auto',
    });
  });

  it('reflects overridden configuration values', () => {
    workspace.getConfiguration = vi.fn(() => ({
      get: (key: string, defaultValue: unknown) => {
        if (key === 'apiEndpoint') { return 'https://example.com'; }
        if (key === 'effort') { return 'high'; }
        return defaultValue;
      },
    })) as typeof workspace.getConfiguration;

    const settings = new SettingsManager(makeContext());
    const result = settings.getSettings();
    expect(result.apiEndpoint).toBe('https://example.com');
    expect(result.effort).toBe('high');
    expect(result.model).toBe('dabba'); // untouched key still falls back to default
  });

  it('stores, retrieves, and clears the API key via SecretStorage', async () => {
    const context = makeContext();
    const settings = new SettingsManager(context);

    expect(await settings.getApiKey()).toBeUndefined();

    await settings.setApiKey('sk-test-123');
    expect(await settings.getApiKey()).toBe('sk-test-123');

    await settings.clearApiKey();
    expect(await settings.getApiKey()).toBeUndefined();
  });

  it('fires onDidChangeSettings when the dabba configuration section changes', () => {
    let capturedHandler: ((e: { affectsConfiguration: (s: string) => boolean }) => void) | undefined;
    workspace.onDidChangeConfiguration = vi.fn((handler) => {
      capturedHandler = handler;
      return { dispose: () => {} };
    }) as typeof workspace.onDidChangeConfiguration;

    const settings = new SettingsManager(makeContext());
    const listener = vi.fn();
    settings.onDidChangeSettings(listener);

    capturedHandler?.({ affectsConfiguration: (s: string) => s === 'dabba' });
    expect(listener).toHaveBeenCalledTimes(1);

    capturedHandler?.({ affectsConfiguration: () => false });
    expect(listener).toHaveBeenCalledTimes(1); // unrelated section change is ignored
  });

  it('disposes its listeners cleanly', () => {
    const settings = new SettingsManager(makeContext());
    expect(() => settings.dispose()).not.toThrow();
  });
});
