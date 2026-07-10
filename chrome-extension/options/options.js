class OptionsApp {
  constructor() {
    this._init();
  }

  async _init() {
    await this._loadSettings();
    this._setupEventListeners();
    this._applyTheme();
  }

  _getElements() {
    return {
      apiEndpoint: document.getElementById('apiEndpoint'),
      apiKey: document.getElementById('apiKey'),
      modelSelect: document.getElementById('modelSelect'),
      themeSelect: document.getElementById('themeSelect'),
      statusMessage: document.getElementById('statusMessage'),
      testConnectionBtn: document.getElementById('testConnectionBtn'),
      saveBtn: document.getElementById('saveBtn'),
      resetBtn: document.getElementById('resetBtn'),
      exportConfigBtn: document.getElementById('exportConfigBtn'),
      importConfigBtn: document.getElementById('importConfigBtn'),
      importFileInput: document.getElementById('importFileInput'),
    };
  }

  async _loadSettings() {
    const els = this._getElements();
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_SETTINGS' });
      if (response) {
        els.apiEndpoint.value = response.apiEndpoint || 'http://localhost:8080';
        els.apiKey.value = response.apiKey || '';
        els.modelSelect.value = response.model || 'dabba';
        els.themeSelect.value = response.theme || 'system';
      }
    } catch {
      this._showStatus('Could not load settings from storage.', 'error');
    }
  }

  _setupEventListeners() {
    const els = this._getElements();

    els.testConnectionBtn.addEventListener('click', () => this._testConnection());
    els.saveBtn.addEventListener('click', () => this._saveSettings());
    els.resetBtn.addEventListener('click', () => this._resetSettings());
    els.exportConfigBtn.addEventListener('click', () => this._exportConfig());
    els.importConfigBtn.addEventListener('click', () => els.importFileInput.click());
    els.importFileInput.addEventListener('change', (e) => this._importConfig(e));

    els.themeSelect.addEventListener('change', () => this._applyTheme());
  }

  async _testConnection() {
    const els = this._getElements();
    const endpoint = els.apiEndpoint.value.trim();
    const apiKey = els.apiKey.value.trim();

    if (!endpoint) {
      this._showStatus('Please enter an API endpoint URL.', 'error');
      return;
    }

    els.testConnectionBtn.disabled = true;
    els.testConnectionBtn.textContent = 'Testing...';
    this._showStatus('Testing connection...', 'info');

    try {
      const healthUrl = `${endpoint}/health`;
      const headers = { 'Content-Type': 'application/json' };
      if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

      const healthRes = await fetch(healthUrl, { headers, signal: AbortSignal.timeout(5000) });

      if (!healthRes.ok) {
        throw new Error(`Health check failed: ${healthRes.status}`);
      }

      const healthData = await healthRes.json();

      const modelsUrl = `${endpoint}/v1/models`;
      const modelsRes = await fetch(modelsUrl, { headers, signal: AbortSignal.timeout(5000) });

      if (modelsRes.ok) {
        const modelsData = await modelsRes.json();
        this._populateModels(modelsData);
      }

      this._showStatus(
        `Connected successfully! API version: ${healthData.version || 'unknown'}, Model loaded: ${healthData.model_loaded || false}`,
        'success'
      );
    } catch (error) {
      this._showStatus(`Connection failed: ${error.message}`, 'error');
    } finally {
      els.testConnectionBtn.disabled = false;
      els.testConnectionBtn.textContent = 'Test Connection';
    }
  }

  _populateModels(modelsData) {
    const els = this._getElements();
    const models = modelsData.data || [];

    if (models.length === 0) {
      els.modelSelect.innerHTML = '<option value="dabba">dabba</option>';
      return;
    }

    const currentValue = els.modelSelect.value;
    els.modelSelect.innerHTML = models
      .map((m) => `<option value="${m.id}">${m.id}</option>`)
      .join('');

    if ([...els.modelSelect.options].some((o) => o.value === currentValue)) {
      els.modelSelect.value = currentValue;
    }
  }

  async _saveSettings() {
    const els = this._getElements();
    const settings = {
      apiEndpoint: els.apiEndpoint.value.trim(),
      apiKey: els.apiKey.value.trim(),
      model: els.modelSelect.value,
      theme: els.themeSelect.value,
    };

    if (!settings.apiEndpoint) {
      this._showStatus('API endpoint URL is required.', 'error');
      return;
    }

    try {
      await chrome.runtime.sendMessage({
        type: 'SAVE_SETTINGS',
        settings,
      });
      this._showStatus('Settings saved successfully.', 'success');
    } catch (error) {
      this._showStatus(`Failed to save settings: ${error.message}`, 'error');
    }
  }

  async _resetSettings() {
    if (!confirm('Reset all settings to defaults? This cannot be undone.')) return;

    try {
      await chrome.runtime.sendMessage({ type: 'RESET_SETTINGS' });
      await this._loadSettings();
      this._applyTheme();
      this._showStatus('Settings reset to defaults.', 'success');
    } catch (error) {
      this._showStatus(`Failed to reset settings: ${error.message}`, 'error');
    }
  }

  async _exportConfig() {
    const els = this._getElements();
    const config = {
      version: '1.0.0',
      exportedAt: new Date().toISOString(),
      settings: {
        apiEndpoint: els.apiEndpoint.value.trim(),
        model: els.modelSelect.value,
        theme: els.themeSelect.value,
      },
    };

    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `dabba-config-${Date.now()}.json`;
    a.click();

    URL.revokeObjectURL(url);
    this._showStatus('Configuration exported.', 'success');
  }

  _importConfig(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
      try {
        const config = JSON.parse(event.target.result);
        if (!config.settings) {
          this._showStatus('Invalid configuration file.', 'error');
          return;
        }

        const els = this._getElements();
        if (config.settings.apiEndpoint) els.apiEndpoint.value = config.settings.apiEndpoint;
        if (config.settings.model) els.modelSelect.value = config.settings.model;
        if (config.settings.theme) els.themeSelect.value = config.settings.theme;

        this._applyTheme();
        this._showStatus('Configuration imported. Save to apply.', 'success');
      } catch (error) {
        this._showStatus(`Failed to import config: ${error.message}`, 'error');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  _applyTheme() {
    const els = this._getElements();
    const theme = els.themeSelect?.value || 'system';
    const resolved = theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme;

    document.documentElement.setAttribute('data-theme', resolved);
  }

  _showStatus(message, type = 'info') {
    const els = this._getElements();
    els.statusMessage.textContent = message;
    els.statusMessage.className = `status-message ${type}`;
    els.statusMessage.classList.remove('hidden');

    clearTimeout(this._statusTimeout);
    this._statusTimeout = setTimeout(() => {
      els.statusMessage.classList.add('hidden');
    }, 5000);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new OptionsApp();
});
