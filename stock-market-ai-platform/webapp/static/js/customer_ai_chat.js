(() => {
  if (document.getElementById('ds-ai-chat-launcher')) return;

  const style = document.createElement('style');
  style.id = 'ds-ai-chat-style';
  style.textContent = `
    #ds-ai-chat-launcher{position:fixed;right:22px;bottom:22px;z-index:90000;width:58px;height:58px;border:1px solid rgba(54,216,255,.48);border-radius:50%;background:linear-gradient(145deg,#163455,#0b1b30);color:#36d8ff;font-weight:950;cursor:pointer;box-shadow:0 18px 42px rgba(0,0,0,.42)}
    #ds-ai-chat-panel{position:fixed;right:22px;bottom:92px;z-index:90000;display:none;flex-direction:column;width:min(390px,calc(100vw - 28px));height:min(560px,calc(100vh - 125px));border:1px solid #244261;border-radius:20px;background:#091628;color:#f2f6ff;box-shadow:0 28px 80px rgba(0,0,0,.58);overflow:hidden}
    #ds-ai-chat-panel.open{display:flex}
    .ds-chat-head{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid rgba(120,155,205,.16);background:#10223b}
    .ds-chat-head button{border:0;background:transparent;color:#91a6c2;font-size:1.35rem;cursor:pointer}
    #ds-chat-messages{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:11px}
    .ds-chat-message{max-width:88%;padding:10px 12px;border-radius:14px;line-height:1.45;font-size:.88rem;white-space:pre-wrap}
    .ds-chat-assistant{align-self:flex-start;background:#10223b;border:1px solid rgba(54,216,255,.18)}
    .ds-chat-user{align-self:flex-end;background:rgba(57,227,161,.12);border:1px solid rgba(57,227,161,.25)}
    .ds-chat-compose{display:grid;grid-template-columns:1fr auto;gap:9px;padding:12px;border-top:1px solid rgba(120,155,205,.16)}
    #ds-chat-input{min-width:0;resize:none;padding:11px 12px;border:1px solid #244261;border-radius:12px;background:#0d1c31;color:#f2f6ff;font:inherit}
    #ds-chat-send{padding:10px 14px;border:0;border-radius:12px;background:linear-gradient(90deg,#36d8ff,#39e3a1);color:#06151d;font-weight:950;cursor:pointer}
    #ds-chat-send:disabled{opacity:.55;cursor:wait}
    @media(max-width:520px){#ds-ai-chat-launcher{right:14px;bottom:14px}#ds-ai-chat-panel{right:14px;bottom:82px}}
  `;
  document.head.appendChild(style);

  const launcher = document.createElement('button');
  launcher.id = 'ds-ai-chat-launcher';
  launcher.type = 'button';
  launcher.setAttribute('aria-label', 'Open Data Shepherd AI assistant');
  launcher.textContent = 'AI';
  document.body.appendChild(launcher);

  const panel = document.createElement('section');
  panel.id = 'ds-ai-chat-panel';
  panel.setAttribute('aria-label', 'Data Shepherd AI assistant');
  panel.innerHTML = `
    <div class="ds-chat-head">
      <div><strong>Data Shepherd AI</strong><div style="color:#91a6c2;font-size:.72rem;margin-top:3px">Platform guide · not financial advice</div></div>
      <button type="button" data-chat-close aria-label="Close chat">×</button>
    </div>
    <div id="ds-chat-messages" aria-live="polite">
      <div class="ds-chat-message ds-chat-assistant">Hi! I can explain the dashboard, model comparisons, frozen holdouts, rankings, and platform terminology. What would you like to understand?</div>
    </div>
    <form class="ds-chat-compose">
      <textarea id="ds-chat-input" rows="2" maxlength="2000" placeholder="Ask about the platform…" aria-label="Message"></textarea>
      <button id="ds-chat-send" type="submit">SEND</button>
    </form>`;
  document.body.appendChild(panel);

  const messages = panel.querySelector('#ds-chat-messages');
  const input = panel.querySelector('#ds-chat-input');
  const send = panel.querySelector('#ds-chat-send');
  const add = (text, role) => {
    const node = document.createElement('div');
    node.className = `ds-chat-message ds-chat-${role}`;
    node.textContent = text;
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
  };

  launcher.addEventListener('click', () => {
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) input.focus();
  });
  panel.querySelector('[data-chat-close]').addEventListener('click', () => panel.classList.remove('open'));

  panel.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || send.disabled) return;
    add(message, 'user');
    input.value = '';
    send.disabled = true;
    send.textContent = '…';
    try {
      const response = await fetch('/api/customer-chat', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {'Content-Type':'application/json','Accept':'application/json'},
        body: JSON.stringify({message, page: window.location.pathname + window.location.search})
      });
      if (response.status === 401) {
        window.location.assign('/?reason=inactive');
        return;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      add(data.reply || 'I could not generate a response.', 'assistant');
    } catch (error) {
      add(`The assistant is temporarily unavailable. ${error.message}`, 'assistant');
    } finally {
      send.disabled = false;
      send.textContent = 'SEND';
      input.focus();
    }
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      panel.querySelector('form').requestSubmit();
    }
  });
})();
