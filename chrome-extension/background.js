const STORAGE_KEYS = {
  API_ENDPOINT: 'apiEndpoint',
  API_KEY: 'apiKey',
  MODEL: 'model',
  THEME: 'theme',
  CONVERSATIONS: 'conversations',
  ACTIVE_CONVERSATION: 'activeConversationId',
};

const DEFAULT_SETTINGS = {
  apiEndpoint: 'http://localhost:8080',
  apiKey: '',
  model: 'dabba',
  theme: 'system',
};

class StorageManager {
  static async get(key) {
    const result = await chrome.storage.sync.get(key);
    return result[key];
  }

  static async set(key, value) {
    await chrome.storage.sync.set({ [key]: value });
  }

  static async getAll(keys) {
    return chrome.storage.sync.get(keys);
  }

  static async getSettings() {
    const settings = await chrome.storage.sync.get(Object.values(STORAGE_KEYS));
    return { ...DEFAULT_SETTINGS, ...settings };
  }

  static async saveSettings(settings) {
    await chrome.storage.sync.set(settings);
  }

  static async resetSettings() {
    await chrome.storage.sync.clear();
  }
}

class ApiClient {
  constructor() {
    this.controller = null;
  }

  async getConfig() {
    const settings = await StorageManager.getSettings();
    return {
      endpoint: settings.apiEndpoint || DEFAULT_SETTINGS.apiEndpoint,
      apiKey: settings.apiKey || '',
      model: settings.model || DEFAULT_SETTINGS.model,
    };
  }

  async listModels() {
    const { endpoint, apiKey } = await this.getConfig();
    const url = `${endpoint}/v1/models`;
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

    const response = await fetch(url, { headers });
    if (!response.ok) throw new Error(`Failed to fetch models: ${response.status}`);
    return response.json();
  }

  async sendChatCompletion(messages, options = {}) {
    const { endpoint, apiKey, model } = await this.getConfig();
    const url = `${endpoint}/v1/chat/completions`;
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

    this.controller = new AbortController();
    const { signal } = this.controller;

    const body = JSON.stringify({
      model: options.model || model,
      messages,
      stream: options.stream ?? true,
      temperature: options.temperature ?? 0.7,
      max_tokens: options.max_tokens ?? 4096,
    });

    const response = await fetch(url, { method: 'POST', headers, body, signal });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || `API error: ${response.status}`);
    }

    if (!options.stream) {
      return response.json();
    }

    return this._handleStream(response, options.onChunk, options.onDone, options.onError);
  }

  async _handleStream(response, onChunk, onDone, onError) {
    try {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data: ')) continue;
          const data = trimmed.slice(6);
          if (data === '[DONE]') {
            if (onDone) onDone();
            return;
          }
          try {
            const parsed = JSON.parse(data);
            const content = parsed.choices?.[0]?.delta?.content || '';
            if (content && onChunk) onChunk(content);
          } catch {
            // skip malformed chunks
          }
        }
      }
      if (onDone) onDone();
    } catch (error) {
      if (error.name === 'AbortError') return;
      if (onError) onError(error);
    }
  }

  abort() {
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
  }
}

class ContextMenuManager {
  static createMenus() {
    chrome.contextMenus.removeAll(() => {
      chrome.contextMenus.create({
        id: 'ask-dabba',
        title: 'Ask dabba about selection',
        contexts: ['selection'],
      });
      chrome.contextMenus.create({
        id: 'explain-dabba',
        title: 'Explain this',
        contexts: ['selection'],
      });
      chrome.contextMenus.create({
        id: 'summarize-dabba',
        title: 'Summarize this',
        contexts: ['selection'],
      });
    });
  }

  static async handleClick(info, tab) {
    const selectedText = info.selectionText?.trim();
    if (!selectedText) return;

    let prompt;
    switch (info.menuItemId) {
      case 'ask-dabba':
        prompt = selectedText;
        break;
      case 'explain-dabba':
        prompt = `Explain this:\n\n${selectedText}`;
        break;
      case 'summarize-dabba':
        prompt = `Summarize this concisely:\n\n${selectedText}`;
        break;
      default:
        return;
    }

    await chrome.sidePanel.open({ tabId: tab.id });

    await chrome.tabs.sendMessage(tab.id, {
      type: 'OPEN_SIDEBAR_WITH_PROMPT',
      prompt,
      pageText: selectedText,
    }).catch(() => {
      // content script may not be loaded
    });
  }
}

class BadgeManager {
  static async update(text = '', color = '#4F46E5') {
    await chrome.action.setBadgeText({ text });
    if (text) {
      await chrome.action.setBadgeBackgroundColor({ color });
    }
  }

  static async showError(error) {
    await this.update('!', '#DC2626');
    console.error('[dabba]', error);
  }

  static async clear() {
    await this.update('');
  }
}

class MessageHandler {
  static apiClient = new ApiClient();

  static async handleMessage(message, sender, sendResponse) {
    switch (message.type) {
      case 'GET_SETTINGS':
        sendResponse(await StorageManager.getSettings());
        return true;

      case 'SAVE_SETTINGS':
        await StorageManager.saveSettings(message.settings);
        sendResponse({ success: true });
        return true;

      case 'RESET_SETTINGS':
        await StorageManager.resetSettings();
        sendResponse({ success: true });
        return true;

      case 'LIST_MODELS':
        try {
          const models = await this.apiClient.listModels();
          sendResponse({ success: true, data: models });
        } catch (error) {
          sendResponse({ success: false, error: error.message });
        }
        return true;

      case 'SEND_CHAT_MESSAGE':
        this._handleChatMessage(message, sender, sendResponse);
        return true;

      case 'ABORT_REQUEST':
        this.apiClient.abort();
        sendResponse({ success: true });
        return true;

      case 'GET_PAGE_CONTEXT':
        sendResponse({ success: true });
        return true;

      case 'SIDEBAR_OPENED':
        await BadgeManager.update('●');
        sendResponse({ success: true });
        return true;

      case 'SIDEBAR_CLOSED':
        await BadgeManager.clear();
        sendResponse({ success: true });
        return true;

      default:
        sendResponse({ success: false, error: 'Unknown message type' });
        return true;
    }
  }

  static async _handleChatMessage(message, sender, sendResponse) {
    const port = message.target === 'sidepanel'
      ? await this._findSidePanelPort()
      : null;

    if (port) {
      const forwardMsg = { type: 'CHAT_RESPONSE_STREAM', conversationId: message.conversationId };

      try {
        await this.apiClient.sendChatCompletion(message.messages, {
          stream: true,
          model: message.model,
          temperature: message.temperature,
          max_tokens: message.max_tokens,
          onChunk: (content) => {
            port.postMessage({ ...forwardMsg, content, done: false });
          },
          onDone: () => {
            port.postMessage({ ...forwardMsg, content: '', done: true });
          },
          onError: (error) => {
            port.postMessage({ ...forwardMsg, error: error.message, done: true });
          },
        });
        sendResponse({ success: true });
      } catch (error) {
        port.postMessage({ ...forwardMsg, error: error.message, done: true });
        sendResponse({ success: false, error: error.message });
      }
    } else {
      // No side panel connected — return via sendResponse
      let fullResponse = '';
      try {
        await this.apiClient.sendChatCompletion(message.messages, {
          stream: true,
          model: message.model,
          temperature: message.temperature,
          max_tokens: message.max_tokens,
          onChunk: (content) => { fullResponse += content; },
          onDone: () => {},
          onError: (error) => { throw error; },
        });
        sendResponse({ success: true, data: fullResponse });
      } catch (error) {
        sendResponse({ success: false, error: error.message });
      }
    }
  }

  static async _findSidePanelPort() {
    // Communication to side panel via storage + broadcast
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      try {
        await chrome.tabs.sendMessage(tab.id, { type: 'PING' });
      } catch {
        continue;
      }
    }
    return null;
  }
}

chrome.runtime.onInstalled.addListener(async (details) => {
  ContextMenuManager.createMenus();

  if (details.reason === 'install') {
    await StorageManager.saveSettings(DEFAULT_SETTINGS);
    await chrome.tabs.create({ url: 'options/options.html' });
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  ContextMenuManager.handleClick(info, tab);
});

chrome.action.onClicked.addListener(async (tab) => {
  const current = await chrome.sidePanel.getOptions({ tabId: tab.id });
  if (current.enabled) {
    await chrome.sidePanel.setOptions({
      tabId: tab.id,
      enabled: !current.enabled,
    });
  } else {
    await chrome.sidePanel.open({ tabId: tab.id });
    await chrome.sidePanel.setOptions({ tabId: tab.id, enabled: true });
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  return MessageHandler.handleMessage(message, sender, sendResponse);
});

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: false })
  .catch(() => {});

export {};
