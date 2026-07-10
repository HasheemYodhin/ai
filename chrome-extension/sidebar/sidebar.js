class ChatState {
  constructor() {
    this.conversations = [];
    this.activeId = null;
    this.isStreaming = false;
    this.currentAbortController = null;
    this.files = [];
    this.includePageContext = true;
    this.pageContext = null;
  }

  get active() {
    return this.conversations.find((c) => c.id === this.activeId);
  }

  createNew() {
    const conv = {
      id: crypto.randomUUID(),
      title: 'New conversation',
      messages: [],
      model: 'dabba',
      temperature: 0.7,
      maxTokens: 4096,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    this.conversations.push(conv);
    this.activeId = conv.id;
    return conv;
  }

  addMessage(role, content) {
    const conv = this.active;
    if (!conv) return null;
    const msg = { id: crypto.randomUUID(), role, content, timestamp: Date.now() };
    conv.messages.push(msg);
    conv.updatedAt = Date.now();
    if (conv.messages.length === 1) {
      conv.title = content.slice(0, 60);
    }
    return msg;
  }

  updateLastMessage(content) {
    const conv = this.active;
    if (!conv || conv.messages.length === 0) return;
    conv.messages[conv.messages.length - 1].content += content;
  }

  clear() {
    this.conversations = [];
    this.activeId = null;
  }
}

class SidebarApp {
  constructor() {
    this.state = new ChatState();
    this.elements = this._getElements();
    this._init();
  }

  _getElements() {
    return {
      chatMessages: document.getElementById('chatMessages'),
      chatInput: document.getElementById('chatInput'),
      sendBtn: document.getElementById('sendBtn'),
      newChatBtn: document.getElementById('newChatBtn'),
      settingsBtn: document.getElementById('settingsBtn'),
      closeSettingsBtn: document.getElementById('closeSettingsBtn'),
      settingsPanel: document.getElementById('settingsPanel'),
      fileUploadBtn: document.getElementById('fileUploadBtn'),
      fileInput: document.getElementById('fileInput'),
      filePreview: document.getElementById('filePreview'),
      fileDropZone: document.getElementById('fileDropZone'),
      contextToggleBtn: document.getElementById('contextToggleBtn'),
      pageContextBar: document.getElementById('pageContextBar'),
      pageContextText: document.getElementById('pageContextText'),
      clearContextBtn: document.getElementById('clearContextBtn'),
      sidebarModelSelect: document.getElementById('sidebarModelSelect'),
      temperatureRange: document.getElementById('temperatureRange'),
      temperatureValue: document.getElementById('temperatureValue'),
      maxTokensRange: document.getElementById('maxTokensRange'),
      maxTokensValue: document.getElementById('maxTokensValue'),
      exportBtn: document.getElementById('exportBtn'),
      clearConvoBtn: document.getElementById('clearConvoBtn'),
      themeBtns: document.querySelectorAll('.theme-btn'),
    };
  }

  async _init() {
    await this._loadSettings();
    this._setupEventListeners();
    this._applyTheme();
    this._loadConversations();
    this._getPageContext();
    this._resizeInput();

    this.elements.chatInput.focus();
  }

  async _loadSettings() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_SETTINGS' });
      if (response) {
        if (response.model) this.elements.sidebarModelSelect.value = response.model;
        if (response.theme) this._setActiveTheme(response.theme);
      }
    } catch (e) {
      // background not accessible
    }
  }

  _setupEventListeners() {
    this.elements.chatInput.addEventListener('input', () => {
      this._onInputChange();
      this._resizeInput();
    });

    this.elements.chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._sendMessage();
      }
    });

    this.elements.sendBtn.addEventListener('click', () => this._sendMessage());
    this.elements.newChatBtn.addEventListener('click', () => this._newChat());
    this.elements.settingsBtn.addEventListener('click', () => this._toggleSettings(true));
    this.elements.closeSettingsBtn.addEventListener('click', () => this._toggleSettings(false));

    this.elements.fileUploadBtn.addEventListener('click', () => this.elements.fileInput.click());
    this.elements.fileInput.addEventListener('change', (e) => this._handleFiles(e.target.files));

    this.elements.contextToggleBtn.addEventListener('click', () => this._togglePageContext());
    this.elements.clearContextBtn.addEventListener('click', () => this._clearPageContext());

    this.elements.sidebarModelSelect.addEventListener('change', (e) => this._onModelChange(e));
    this.elements.temperatureRange.addEventListener('input', (e) => {
      this.elements.temperatureValue.textContent = e.target.value;
    });
    this.elements.maxTokensRange.addEventListener('input', (e) => {
      this.elements.maxTokensValue.textContent = e.target.value;
    });

    this.elements.exportBtn.addEventListener('click', () => this._exportConversations());
    this.elements.clearConvoBtn.addEventListener('click', () => this._clearConversations());

    this.elements.themeBtns.forEach((btn) => {
      btn.addEventListener('click', () => this._onThemeChange(btn.dataset.theme));
    });

    // suggestion chips
    document.querySelectorAll('.suggestion-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        this.elements.chatInput.value = chip.dataset.prompt;
        this._onInputChange();
        this._resizeInput();
        this._sendMessage();
      });
    });

    // drag and drop
    document.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.elements.fileDropZone.classList.remove('hidden');
      this.elements.fileDropZone.classList.add('dragover');
    });

    document.addEventListener('dragleave', (e) => {
      e.preventDefault();
      this.elements.fileDropZone.classList.remove('dragover');
      this.elements.fileDropZone.classList.add('hidden');
    });

    document.addEventListener('drop', (e) => {
      e.preventDefault();
      this.elements.fileDropZone.classList.remove('dragover', 'hidden');
      this._handleFiles(e.dataTransfer.files);
    });

    // Listen for prompt from content script
    window.addEventListener('dabba-sidebar-prompt', (e) => {
      const { prompt, context } = e.detail;
      this.state.pageContext = context;
      if (context) {
        this._showPageContext(context);
      }
      this.elements.chatInput.value = prompt;
      this._onInputChange();
      this._resizeInput();
      this._sendMessage();
    });
  }

  _onInputChange() {
    const text = this.elements.chatInput.value.trim();
    this.elements.sendBtn.disabled = !text || this.state.isStreaming;
  }

  _resizeInput() {
    this.elements.chatInput.style.height = 'auto';
    this.elements.chatInput.style.height = Math.min(this.elements.chatInput.scrollHeight, 120) + 'px';
  }

  async _getPageContext() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id) return;

      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_CONTEXT' });
      if (response?.success && response.data) {
        this.state.pageContext = response.data;
        this._showPageContext(response.data);
      }
    } catch {
      // content script not available
    }
  }

  _showPageContext(context) {
    if (!context) return;
    this.elements.pageContextBar.classList.remove('hidden');
    this.elements.pageContextText.textContent = context.title || context.url || 'Current page';
    this.elements.contextToggleBtn.style.opacity = '1';
  }

  _clearPageContext() {
    this.state.pageContext = null;
    this.elements.pageContextBar.classList.add('hidden');
  }

  _togglePageContext() {
    if (this.elements.pageContextBar.classList.contains('hidden')) {
      if (this.state.pageContext) {
        this._showPageContext(this.state.pageContext);
      } else {
        this._getPageContext();
      }
    } else {
      this._clearPageContext();
    }
  }

  _handleFiles(files) {
    if (!files.length) return;
    this.elements.filePreview.classList.remove('hidden');
    this.elements.filePreview.innerHTML = '';

    Array.from(files).forEach((file) => {
      const item = document.createElement('div');
      item.className = 'file-preview-item';
      item.innerHTML = `
        <span>${this._escapeHtml(file.name)}</span>
        <span class="remove-file" data-name="${this._escapeHtml(file.name)}">&times;</span>
      `;
      item.querySelector('.remove-file').addEventListener('click', () => {
        item.remove();
        this.state.files = this.state.files.filter((f) => f.name !== file.name);
        if (this.state.files.length === 0) {
          this.elements.filePreview.classList.add('hidden');
        }
      });
      this.elements.filePreview.appendChild(item);
      this.state.files.push(file);
    });
  }

  _newChat() {
    if (this.state.isStreaming) this._abortStream();
    this.state.createNew();
    this.elements.chatMessages.innerHTML = `
      <div class="welcome-screen">
        <div class="welcome-icon">◆</div>
        <h2 class="welcome-title">dabba AI Assistant</h2>
        <p class="welcome-text">Ask me anything about this page, or start a new conversation.</p>
        <div class="suggestions">
          <button class="suggestion-chip" data-prompt="Summarize this page">Summarize this page</button>
          <button class="suggestion-chip" data-prompt="What is this page about?">What is this page about?</button>
          <button class="suggestion-chip" data-prompt="Extract key points from this page">Extract key points</button>
          <button class="suggestion-chip" data-prompt="Explain the main concepts here">Explain main concepts</button>
        </div>
      </div>
    `;
    this.elements.chatInput.value = '';
    this._onInputChange();
    this.elements.chatInput.focus();
    this._saveToStorage();
  }

  async _sendMessage() {
    const text = this.elements.chatInput.value.trim();
    if (!text || this.state.isStreaming) return;

    let conv = this.state.active;
    if (!conv) {
      conv = this.state.createNew();
      this._clearWelcomeScreen();
    }

    const userMsg = this.state.addMessage('user', text);
    this._renderMessage(userMsg);
    this.elements.chatInput.value = '';
    this._onInputChange();
    this._resizeInput();

    this.state.isStreaming = true;
    this.elements.sendBtn.disabled = true;
    this.state.addMessage('assistant', '');

    const typingEl = document.createElement('div');
    typingEl.className = 'message assistant';
    typingEl.innerHTML = `
      <div class="message-header">
        <span class="message-role">dabba</span>
      </div>
      <div class="message-content">
        <div class="typing-indicator">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>
      </div>
    `;
    this.elements.chatMessages.appendChild(typingEl);
    this._scrollToBottom();

    const systemMessages = [];
    if (this.state.includePageContext && this.state.pageContext) {
      systemMessages.push({
        role: 'system',
        content: `You are helping with content from: ${this.state.pageContext.title}\nURL: ${this.state.pageContext.url}\n\nPage content:\n${this.state.pageContext.text}`,
      });
    } else {
      systemMessages.push({
        role: 'system',
        content: 'You are a helpful AI assistant powered by dabba.',
      });
    }

    const messages = [
      ...systemMessages,
      ...conv.messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content })),
    ];

    try {
      await chrome.runtime.sendMessage({
        type: 'SEND_CHAT_MESSAGE',
        messages,
        conversationId: conv.id,
        target: 'sidepanel',
        model: this.elements.sidebarModelSelect.value,
        temperature: parseFloat(this.elements.temperatureRange.value),
        max_tokens: parseInt(this.elements.maxTokensRange.value),
      });

      this._startStreamListener(conv.id, typingEl);
    } catch (error) {
      this._removeTypingIndicator();
      const lastMsg = this.state.active?.messages?.pop();
      this._renderError(error.message || 'Failed to send message');
      this.state.isStreaming = false;
      this.elements.sendBtn.disabled = false;
    }
  }

  _startStreamListener(conversationId, typingEl) {
    const handler = (message) => {
      if (message.type !== 'CHAT_RESPONSE_STREAM' || message.conversationId !== conversationId) return;

      if (message.error) {
        chrome.runtime.onMessage.removeListener(handler);
        this._removeTypingIndicator();
        this._renderError(message.error);
        this.state.isStreaming = false;
        this.elements.sendBtn.disabled = false;
        return;
      }

      if (message.done) {
        chrome.runtime.onMessage.removeListener(handler);
        this._removeTypingIndicator();
        this.state.isStreaming = false;
        this.elements.sendBtn.disabled = false;
        this._scrollToBottom();
        this._saveToStorage();
        return;
      }

      if (message.content) {
        this.state.updateLastMessage(message.content);
        this._updateStreamingMessage(typingEl);
        this._scrollToBottom();
      }
    };

    chrome.runtime.onMessage.addListener(handler);
  }

  _updateStreamingMessage(typingEl) {
    const conv = this.state.active;
    if (!conv || conv.messages.length === 0) return;

    const lastMsg = conv.messages[conv.messages.length - 1];
    if (lastMsg.role !== 'assistant') return;

    const contentEl = typingEl.querySelector('.message-content');
    if (contentEl) {
      contentEl.innerHTML = this._renderMarkdown(lastMsg.content);
    }
  }

  _removeTypingIndicator() {
    const typing = this.elements.chatMessages.querySelector('.typing-indicator');
    if (typing) {
      const parent = typing.closest('.message');
      if (parent) parent.remove();
    }
  }

  _renderMessage(msg) {
    this._clearWelcomeScreen();

    const el = document.createElement('div');
    el.className = `message ${msg.role}`;
    el.dataset.messageId = msg.id;
    el.innerHTML = `
      <div class="message-header">
        <span class="message-role">${msg.role === 'user' ? 'You' : 'dabba'}</span>
      </div>
      <div class="message-content">${msg.role === 'user' ? this._escapeHtml(msg.content) : this._renderMarkdown(msg.content)}</div>
    `;
    this.elements.chatMessages.appendChild(el);
    this._scrollToBottom();
  }

  _renderError(text) {
    const el = document.createElement('div');
    el.className = 'message error';
    el.innerHTML = `
      <div class="message-header">
        <span class="message-role">Error</span>
      </div>
      <div class="message-content">${this._escapeHtml(text)}</div>
    `;
    this.elements.chatMessages.appendChild(el);
    this._scrollToBottom();
  }

  _clearWelcomeScreen() {
    const welcome = this.elements.chatMessages.querySelector('.welcome-screen');
    if (welcome) welcome.remove();
  }

  _renderMarkdown(text) {
    if (!text) return '';
    let html = this._escapeHtml(text);

    // code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const langClass = lang ? ` class="language-${lang}"` : '';
      return `<pre><code${langClass}>${this._escapeHtml(code)}</code></pre>`;
    });

    // inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // strikethrough
    html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');

    // links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // images
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" style="max-width:100%">');

    // blockquotes
    html = html.replace(/^&gt;\s(.+)$/gm, '<blockquote>$1</blockquote>');

    // headings
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // unordered lists
    html = html.replace(/^[-*]\s(.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // ordered lists
    html = html.replace(/^\d+\.\s(.+)$/gm, '<li>$1</li>');

    // line breaks
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');

    return `<p>${html}</p>`;
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  _scrollToBottom() {
    requestAnimationFrame(() => {
      this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    });
  }

  _toggleSettings(open) {
    if (open) {
      this.elements.settingsPanel.classList.remove('hidden');
    } else {
      this.elements.settingsPanel.classList.add('hidden');
    }
  }

  _onModelChange(e) {
    const model = e.target.value;
    chrome.runtime.sendMessage({
      type: 'SAVE_SETTINGS',
      settings: { model },
    }).catch(() => {});
  }

  _onThemeChange(theme) {
    this._setActiveTheme(theme);
    chrome.runtime.sendMessage({
      type: 'SAVE_SETTINGS',
      settings: { theme },
    }).catch(() => {});
  }

  _setActiveTheme(theme) {
    this.elements.themeBtns.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.theme === theme);
    });
    document.documentElement.setAttribute('data-theme', theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme
    );
  }

  _applyTheme() {
    // will be overridden by saved theme
  }

  async _exportConversations() {
    const data = JSON.stringify(this.state.conversations, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `dabba-conversations-${Date.now()}.json`;
    a.click();

    URL.revokeObjectURL(url);
  }

  async _clearConversations() {
    if (this.state.conversations.length === 0) return;
    if (!confirm('Delete all conversations? This cannot be undone.')) return;

    this.state.clear();
    await chrome.storage.sync.remove('conversations');
    this._newChat();
  }

  _loadConversations() {
    chrome.storage.sync.get('conversations', (result) => {
      if (result.conversations) {
        this.state.conversations = result.conversations;
      }
    });
  }

  _saveToStorage() {
    chrome.storage.sync.set({ conversations: this.state.conversations }).catch(() => {});
  }

  _abortStream() {
    chrome.runtime.sendMessage({ type: 'ABORT_REQUEST' }).catch(() => {});
    this.state.isStreaming = false;
    this.elements.sendBtn.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new SidebarApp();
});
