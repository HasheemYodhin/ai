class PopupApp {
  constructor() {
    this.elements = this._getElements();
    this.state = {
      isLoading: false,
      settings: null,
      conversations: [],
    };
    this._init();
  }

  _getElements() {
    return {
      quickInput: document.getElementById('quickInput'),
      sendBtn: document.getElementById('sendBtn'),
      responseArea: document.getElementById('responseArea'),
      responseContent: document.getElementById('responseContent'),
      copyResponseBtn: document.getElementById('copyResponseBtn'),
      recentList: document.getElementById('recentList'),
      modelSelect: document.getElementById('modelSelect'),
      settingsBtn: document.getElementById('settingsBtn'),
      sidebarBtn: document.getElementById('sidebarBtn'),
      toggleThemeBtn: document.getElementById('toggleThemeBtn'),
      statusDot: document.getElementById('statusDot'),
      statusText: document.getElementById('statusText'),
    };
  }

  async _init() {
    await this._loadSettings();
    this._setupEventListeners();
    this._applyTheme();
    this._loadRecentConversations();
  }

  async _loadSettings() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_SETTINGS' });
      this.state.settings = response;

      if (response.model) {
        this.elements.modelSelect.value = response.model;
      }

      this._setStatus('connected', 'Connected');
    } catch {
      this._setStatus('error', 'Connection error');
    }
  }

  _setupEventListeners() {
    this.elements.quickInput.addEventListener('input', () => this._onInputChange());
    this.elements.quickInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._sendMessage();
      }
    });

    this.elements.sendBtn.addEventListener('click', () => this._sendMessage());
    this.elements.copyResponseBtn.addEventListener('click', () => this._copyResponse());
    this.elements.settingsBtn.addEventListener('click', () => this._openSettings());
    this.elements.sidebarBtn.addEventListener('click', () => this._openSidebar());
    this.elements.toggleThemeBtn.addEventListener('click', () => this._toggleTheme());
    this.elements.modelSelect.addEventListener('change', (e) => this._onModelChange(e));
  }

  _onInputChange() {
    const text = this.elements.quickInput.value.trim();
    this.elements.sendBtn.disabled = !text || this.state.isLoading;
  }

  async _sendMessage() {
    const text = this.elements.quickInput.value.trim();
    if (!text || this.state.isLoading) return;

    this.state.isLoading = true;
    this.elements.sendBtn.disabled = true;
    this.elements.responseArea.classList.remove('hidden');
    this.elements.responseContent.textContent = '';
    this.elements.responseContent.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
    this._setStatus('warning', 'Thinking...');

    try {
      const pageContext = await this._getPageContext();
      const systemMessage = pageContext
        ? { role: 'system', content: `You are helping with content from: ${pageContext.title}\nURL: ${pageContext.url}\n\nPage content:\n${pageContext.text}` }
        : { role: 'system', content: 'You are a helpful AI assistant powered by dabba.' };

      const response = await chrome.runtime.sendMessage({
        type: 'SEND_CHAT_MESSAGE',
        messages: [systemMessage, { role: 'user', content: text }],
        model: this.elements.modelSelect.value,
        stream: false,
      });

      this.elements.responseContent.textContent = '';

      if (response.success && response.data) {
        const content = response.data.choices?.[0]?.message?.content || response.data;
        this.elements.responseContent.textContent = content;
        this._setStatus('connected', 'Ready');
        await this._saveConversation(text, content);
      } else {
        throw new Error(response.error || 'Unknown error');
      }
    } catch (error) {
      this.elements.responseContent.textContent = `Error: ${error.message}`;
      this._setStatus('error', 'Error');
    } finally {
      this.state.isLoading = false;
      this.elements.sendBtn.disabled = false;
      this._onInputChange();
    }
  }

  async _getPageContext() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id) return null;

      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_CONTEXT' });
      if (response?.success) {
        return response.data;
      }
    } catch {
      // content script not available
    }
    return null;
  }

  async _loadRecentConversations() {
    try {
      const result = await chrome.storage.sync.get('conversations');
      const conversations = result.conversations || [];
      this.state.conversations = conversations.slice(-5).reverse();
      this._renderRecentList();
    } catch {
      // ignore
    }
  }

  async _saveConversation(question, answer) {
    const conversation = {
      id: crypto.randomUUID(),
      question: question.slice(0, 100),
      answer: answer.slice(0, 200),
      timestamp: Date.now(),
      model: this.elements.modelSelect.value,
    };

    const result = await chrome.storage.sync.get('conversations');
    const conversations = result.conversations || [];
    conversations.push(conversation);

    if (conversations.length > 50) {
      conversations.splice(0, conversations.length - 50);
    }

    await chrome.storage.sync.set({ conversations });
    await this._loadRecentConversations();
  }

  _renderRecentList() {
    const list = this.elements.recentList;

    if (this.state.conversations.length === 0) {
      list.innerHTML = '<p class="empty-state">No conversations yet</p>';
      return;
    }

    list.innerHTML = this.state.conversations
      .map(
        (conv) => `
        <div class="recent-item" data-id="${conv.id}">
          <span class="recent-item-text">${this._escapeHtml(conv.question)}</span>
          <span class="recent-item-time">${this._formatTime(conv.timestamp)}</span>
        </div>
      `
      )
      .join('');

    list.querySelectorAll('.recent-item').forEach((item) => {
      item.addEventListener('click', () => {
        const conv = this.state.conversations.find((c) => c.id === item.dataset.id);
        if (conv) {
          this.elements.quickInput.value = conv.question;
          this._onInputChange();
        }
      });
    });
  }

  async _copyResponse() {
    const text = this.elements.responseContent.textContent;
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      this.elements.copyResponseBtn.textContent = 'Copied!';
      setTimeout(() => {
        this.elements.copyResponseBtn.textContent = 'Copy';
      }, 2000);
    } catch {
      this.elements.copyResponseBtn.textContent = 'Failed';
    }
  }

  _openSettings() {
    chrome.runtime.openOptionsPage();
  }

  async _openSidebar() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id) {
        await chrome.sidePanel.open({ tabId: tab.id });
      }
    } catch (error) {
      this._setStatus('error', 'Could not open sidebar');
    }
  }

  async _toggleTheme() {
    const themes = { light: 'dark', dark: 'system', system: 'light' };
    const current = this.state.settings?.theme || 'system';
    const next = themes[current] || 'dark';

    this.state.settings.theme = next;
    await chrome.runtime.sendMessage({
      type: 'SAVE_SETTINGS',
      settings: { theme: next },
    });

    this._applyTheme();
  }

  _applyTheme() {
    const theme = this.state.settings?.theme || 'system';
    const resolved = theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme;

    document.documentElement.setAttribute('data-theme', resolved);
  }

  async _onModelChange(e) {
    const model = e.target.value;
    this.state.settings.model = model;
    await chrome.runtime.sendMessage({
      type: 'SAVE_SETTINGS',
      settings: { model },
    });
  }

  _setStatus(type, text) {
    this.elements.statusDot.className = 'status-dot' + (type !== 'connected' ? ` ${type}` : '');
    this.elements.statusText.textContent = text;
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  _formatTime(timestamp) {
    const diff = Date.now() - timestamp;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h`;
    const days = Math.floor(hours / 24);
    return `${days}d`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new PopupApp();
});
