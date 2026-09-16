(() => {
  if (document.getElementById('ds-ai-chat-launcher')) return;

  const style = document.createElement('style');
  style.id = 'ds-ai-chat-style';
  style.textContent = `
    #ds-ai-chat-launcher{position:fixed;right:22px;bottom:22px;z-index:90000;display:grid;place-items:center;width:46px;height:46px;padding:0;border:1px solid rgba(54,216,255,.7);border-radius:15px;background:linear-gradient(145deg,#36d8ff 0%,#28c9d8 45%,#39e3a1 100%);color:#06151d;cursor:pointer;box-shadow:0 18px 44px rgba(0,0,0,.46),0 0 0 3px rgba(54,216,255,.08);transition:transform .18s ease,box-shadow .18s ease}
    #ds-ai-chat-launcher:hover{transform:translateY(-3px) scale(1.03);box-shadow:0 22px 50px rgba(0,0,0,.5),0 0 0 4px rgba(54,216,255,.1)}
    #ds-ai-chat-launcher:focus-visible{outline:2px solid #f2f6ff;outline-offset:2px}
    #ds-ai-chat-launcher svg{width:24px;height:24px;display:block;transform:translate(2px,3px)}
    #ds-ai-chat-launcher::before{content:"AI";position:absolute;left:5px;top:4px;color:#06151d;font-size:.7rem;font-weight:1000;line-height:1;letter-spacing:-.03em}
    #ds-ai-chat-launcher::after{content:"Ask Data Shepherd";position:absolute;right:56px;top:50%;transform:translateY(-50%) translateX(7px);width:max-content;padding:8px 11px;border:1px solid #244261;border-radius:10px;background:#10223b;color:#f2f6ff;font-size:.76rem;font-weight:850;letter-spacing:.02em;box-shadow:0 10px 28px rgba(0,0,0,.35);opacity:0;visibility:hidden;transition:opacity .16s ease,transform .16s ease,visibility .16s ease;pointer-events:none}
    #ds-ai-chat-launcher:hover::after,#ds-ai-chat-launcher:focus-visible::after{opacity:1;visibility:visible;transform:translateY(-50%) translateX(0)}
    #ds-ai-chat-panel{position:fixed;right:22px;bottom:92px;z-index:90000;display:none;flex-direction:column;width:min(390px,calc(100vw - 28px));height:min(560px,calc(100vh - 125px));border:1px solid #244261;border-radius:20px;background:#091628;color:#f2f6ff;box-shadow:0 28px 80px rgba(0,0,0,.58);overflow:hidden}
    #ds-ai-chat-panel.open{display:flex}
    .ds-chat-head{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid rgba(120,155,205,.16);background:#10223b}
    .ds-chat-head button{border:0;background:transparent;color:#91a6c2;font-size:1.35rem;cursor:pointer}
    #ds-chat-messages{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:11px}
    .ds-chat-message{max-width:88%;padding:10px 12px;border-radius:14px;line-height:1.45;font-size:.88rem;white-space:pre-wrap}
    .ds-chat-assistant{align-self:flex-start;background:#10223b;border:1px solid rgba(54,216,255,.18)}
    .ds-chat-user{align-self:flex-end;background:rgba(57,227,161,.12);border:1px solid rgba(57,227,161,.25)}
    .ds-chat-suggestions{display:flex;flex-wrap:wrap;gap:7px;padding:0 16px 12px}
    .ds-chat-suggestion{padding:7px 9px;border:1px solid rgba(54,216,255,.28);border-radius:999px;background:rgba(54,216,255,.07);color:#bfefff;font-size:.72rem;font-weight:750;cursor:pointer;text-align:left}
    .ds-chat-suggestion:hover,.ds-chat-suggestion:focus-visible{background:rgba(54,216,255,.16);outline:none}
    .ds-chat-compose{display:grid;grid-template-columns:1fr auto;gap:9px;padding:12px;border-top:1px solid rgba(120,155,205,.16)}
    #ds-chat-input{min-width:0;resize:none;padding:11px 12px;border:1px solid #244261;border-radius:12px;background:#0d1c31;color:#f2f6ff;font:inherit}
    #ds-chat-send{padding:10px 14px;border:0;border-radius:12px;background:linear-gradient(90deg,#36d8ff,#39e3a1);color:#06151d;font-weight:950;cursor:pointer}
    #ds-chat-send:disabled{opacity:.55;cursor:wait}
    @media(max-width:520px){#ds-ai-chat-launcher{right:14px;bottom:14px;width:44px;height:44px;border-radius:14px}#ds-ai-chat-launcher::after{display:none}#ds-ai-chat-panel{right:14px;bottom:82px}}
  `;
  document.head.appendChild(style);

  const launcher = document.createElement('button');
  launcher.id = 'ds-ai-chat-launcher';
  launcher.type = 'button';
  launcher.setAttribute('aria-label', 'Open Data Shepherd AI assistant');
  launcher.innerHTML = `
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 3.5c.8 6.9 4.6 11 11.5 12.5C20.6 17.5 16.8 21.6 16 28.5 15.2 21.6 11.4 17.5 4.5 16 11.4 14.5 15.2 10.4 16 3.5Z" fill="currentColor"/>
      <path d="M25.2 4.6c.25 2.15 1.45 3.35 3.6 3.8-2.15.45-3.35 1.65-3.6 3.8-.25-2.15-1.45-3.35-3.6-3.8 2.15-.45 3.35-1.65 3.6-3.8ZM7.3 22.6c.2 1.65 1.1 2.55 2.75 2.9-1.65.35-2.55 1.25-2.75 2.9-.2-1.65-1.1-2.55-2.75-2.9 1.65-.35 2.55-1.25 2.75-2.9Z" fill="currentColor" opacity=".82"/>
    </svg>`;
  document.body.appendChild(launcher);

  const pageKey = (() => {
    if (window.location.pathname === '/') return 'landing';
    if (window.location.pathname === '/dashboard' && new URLSearchParams(window.location.search).get('view') === 'live') return 'live';
    if (window.location.pathname === '/dashboard') return 'research';
    if (window.location.pathname === '/crypto-visual') return 'crypto_visual';
    if (window.location.pathname === '/crypto') return 'crypto';
    return 'platform';
  })();
  const pageGuides = {
    landing: {
      label: 'Platform introduction',
      welcome: 'Hi! I can explain what Data Shepherd Engineering does, how model evidence is validated, and what frozen holdouts mean.',
      prompts: ['What is Data Shepherd?', 'How are results validated?', 'What is a frozen holdout?']
    },
    research: {
      label: 'Model Research guide',
      welcome: 'Hi! I can explain the model comparison, frozen V8, V10 Cycle 3, and the difference between reconstructed and genuine forward evidence.',
      prompts: ['Explain the model comparison', 'What is frozen V8?', 'What is V10 Cycle 3?']
    },
    live: {
      label: 'Live Stock Viewer guide',
      welcome: 'Hi! I can help you read the live stock charts, rankings, indicators, and provisional live-data labels.',
      prompts: ['How do I read this chart?', 'What does a V8 rank mean?', 'Why is live data provisional?']
    },
    crypto: {
      label: 'Crypto Model Research guide',
      welcome: 'Hi! I can explain the crypto model tabs, evidence boundaries, monitoring states, and research terminology.',
      prompts: ['Explain these crypto models', 'What does data freshness mean?', 'Are these live trading signals?']
    },
    crypto_visual: {
      label: 'Crypto Live guide',
      welcome: 'Hi! I can explain Crypto Live prices, history ranges, market relationships, and evidence labels.',
      prompts: ['How do I read this visual?', 'What do the ranges change?', 'What evidence is forward-only?']
    },
    platform: {
      label: 'Platform guide',
      welcome: 'Hi! I can explain the platform, model evidence, dashboards, and terminology.',
      prompts: ['Explain this page', 'What is forward evidence?', 'How are models validated?']
    }
  };
  const guide = pageGuides[pageKey];

  const panel = document.createElement('section');
  panel.id = 'ds-ai-chat-panel';
  panel.setAttribute('aria-label', 'Data Shepherd AI assistant');
  panel.innerHTML = `
    <div class="ds-chat-head">
      <div><strong>Data Shepherd AI</strong><div style="color:#91a6c2;font-size:.72rem;margin-top:3px">${guide.label} · not financial advice</div></div>
      <button type="button" data-chat-close aria-label="Close chat">×</button>
    </div>
    <div id="ds-chat-messages" aria-live="polite">
      <div class="ds-chat-message ds-chat-assistant">${guide.welcome}</div>
    </div>
    <div class="ds-chat-suggestions" aria-label="Suggested questions">${guide.prompts.map(prompt => `<button type="button" class="ds-chat-suggestion">${prompt}</button>`).join('')}</div>
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
  panel.querySelectorAll('.ds-chat-suggestion').forEach(button => {
    button.addEventListener('click', () => {
      input.value = button.textContent;
      panel.querySelector('form').requestSubmit();
    });
  });

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
        body: JSON.stringify({message, page: pageKey})
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
