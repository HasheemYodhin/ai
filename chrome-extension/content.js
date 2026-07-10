class PageContextExtractor {
  static extract() {
    return {
      title: document.title,
      url: window.location.href,
      description: this._getMetaDescription(),
      text: this._getMainText(),
      headings: this._getHeadings(),
      language: document.documentElement.lang || navigator.language,
    };
  }

  static _getMetaDescription() {
    const meta = document.querySelector('meta[name="description"]');
    return meta?.getAttribute('content') || '';
  }

  static _getMainText() {
    const article = document.querySelector('article');
    if (article) return article.innerText.slice(0, 8000);

    const main = document.querySelector('main');
    if (main) return main.innerText.slice(0, 8000);

    const body = document.body;
    if (!body) return '';

    const clone = body.cloneNode(true);
    const selectors = [
      'script', 'style', 'noscript', 'iframe', 'svg',
      'nav', 'footer', 'header', '.sidebar', '.ad',
      '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    ];
    selectors.forEach((sel) => {
      clone.querySelectorAll(sel).forEach((el) => el.remove());
    });
    return (clone.innerText || '').slice(0, 8000);
  }

  static _getHeadings() {
    const headings = [];
    document.querySelectorAll('h1, h2, h3').forEach((h) => {
      headings.push({ level: h.tagName.toLowerCase(), text: h.innerText.trim() });
    });
    return headings;
  }

  static getSelectedText() {
    const selection = window.getSelection();
    return selection ? selection.toString().trim() : '';
  }
}

class SelectionHandler {
  static init() {
    document.addEventListener('mouseup', (e) => {
      const text = PageContextExtractor.getSelectedText();
      if (text.length > 10) {
        chrome.runtime.sendMessage({
          type: 'TEXT_SELECTED',
          text: text.slice(0, 200),
        }).catch(() => {});
      }
    });
  }
}

class InlineOverlay {
  constructor() {
    this.overlay = null;
  }

  show(text) {
    this.remove();
    this.overlay = document.createElement('div');
    this.overlay.id = 'dabba-inline-overlay';
    this.overlay.innerHTML = `
      <div class="dabba-inline-header">
        <span class="dabba-inline-title">dabba AI</span>
        <button class="dabba-inline-close">&times;</button>
      </div>
      <div class="dabba-inline-content">${this._escapeHtml(text)}</div>
    `;
    this.overlay.querySelector('.dabba-inline-close').onclick = () => this.remove();

    const styles = this._createStyles();
    document.head.appendChild(styles);
    document.body.appendChild(this.overlay);
  }

  remove() {
    if (this.overlay) {
      this.overlay.remove();
      this.overlay = null;
    }
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  _createStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #dabba-inline-overlay {
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 380px;
        max-height: 500px;
        background: #1e1e2e;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        z-index: 2147483647;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 14px;
        line-height: 1.5;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }
      .dabba-inline-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        background: #181825;
        border-bottom: 1px solid #45475a;
      }
      .dabba-inline-title {
        font-weight: 600;
        font-size: 13px;
        color: #cba6f7;
      }
      .dabba-inline-close {
        background: none;
        border: none;
        color: #a6adc8;
        font-size: 20px;
        cursor: pointer;
        padding: 0 4px;
        line-height: 1;
      }
      .dabba-inline-close:hover { color: #f38ba8; }
      .dabba-inline-content {
        padding: 16px;
        overflow-y: auto;
        flex: 1;
        white-space: pre-wrap;
        word-wrap: break-word;
      }
    `;
    return style;
  }
}

const overlay = new InlineOverlay();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case 'GET_PAGE_CONTEXT': {
      const context = PageContextExtractor.extract();
      sendResponse({ success: true, data: context });
      return true;
    }

    case 'OPEN_SIDEBAR_WITH_PROMPT': {
      const context = PageContextExtractor.extract();
      window.dispatchEvent(new CustomEvent('dabba-sidebar-prompt', {
        detail: { prompt: message.prompt, context },
      }));
      sendResponse({ success: true });
      return true;
    }

    case 'SHOW_INLINE_RESPONSE': {
      overlay.show(message.text);
      sendResponse({ success: true });
      return true;
    }

    case 'HIDE_INLINE_RESPONSE': {
      overlay.remove();
      sendResponse({ success: true });
      return true;
    }

    default:
      sendResponse({ success: false });
      return true;
  }
});

SelectionHandler.init();

window.__dabba = {
  getPageContext: () => PageContextExtractor.extract(),
  getSelectedText: () => PageContextExtractor.getSelectedText(),
};

export {};
