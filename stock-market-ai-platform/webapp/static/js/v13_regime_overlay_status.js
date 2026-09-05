(() => {
  if (new URLSearchParams(window.location.search).get('view') === 'live') return;

  const text = (root, selector, value) => {
    const node = root.querySelector(selector);
    if (node) node.textContent = value ?? '—';
  };
  const words = value => String(value || '—').replaceAll('_', ' ');
  const percent = (value, target) => target ? Math.min(100, Math.max(0, value / target * 100)) : 0;
  const percentText = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(0)}%` : '—';
  const numberText = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
  const datetimeText = value => {
    if (!value) return 'Not yet published';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
  };
  const dateText = value => value ? String(value).slice(0, 10) : 'Not published';
  const sequenceText = value => Number.isFinite(Number(value)) ? String(Math.trunc(Number(value))).padStart(6, '0') : (value || 'ROOT');

  function render(root, data) {
    text(root, '[data-v13-display]', words(data.display_status));
    text(root, '[data-v13-control]', words(data.status));
    text(root, '[data-v13-health]', words(data.operational_status));
    text(root, '[data-v13-evidence]', words(data.evidence_status));
    text(root, '[data-v13-activation]', words(data.activation));
    text(root, '[data-v13-decisions]', numberText(data.decisions));
    text(root, '[data-v13-events]', numberText(data.journal_event_count));
    text(root, '[data-v13-scheduler]', words(data.scheduler_status));
    text(root, '[data-v13-collection]', data.collection_expected ? 'YES' : 'NO');
    text(root, '[data-v13-requests]', numberText(data.market_data_requests));
    text(root, '[data-v13-brokerage]', data.brokerage_orders ? 'ON' : 'OFF');
    text(root, '[data-v13-checked]', datetimeText(data.operational_checked_at_utc));
    text(root, '[data-v13-sha]', `${data.contract_sha_verified ? '✓' : '✕'} ${data.contract_sha256 || 'unavailable'}`);
    text(root, '[data-v13-approval]', words(data.manual_approval_status));
    text(root, '[data-v13-approval-artifact]', data.manual_approval_present ? 'PRESENT' : 'ABSENT');
    text(root, '[data-v13-lease]', data.activation_lease_present ? 'PRESENT' : 'ABSENT');
    text(root, '[data-v13-transition]', words(data.transition_status));
    text(root, '[data-v13-transition-gates]', `${numberText(data.transition_gates_passed)} / ${numberText(data.transition_gates_total)}`);
    text(root, '[data-v13-apply]', data.transition_application_present ? 'PRESENT' : 'ABSENT');
    text(root, '[data-v13-planned-state]', words(data.planned_activation_state));
    text(root, '[data-v13-lease-valid]', data.activation_lease_valid ? 'ACTIVE PAPER ONLY' : 'EXPIRED OR BLOCKED');
    text(root, '[data-v13-lease-expires]', datetimeText(data.activation_lease_expires_at_utc));
    text(root, '[data-v13-lease-operator]', data.activation_lease_operator || 'Not published');
    text(root, '[data-v13-lease-sequence]', sequenceText(data.activation_lease_sequence));
    text(root, '[data-v13-candidate]', data.candidate_id || 'Not published');
    text(root, '[data-v13-control-id]', data.control_id || 'Not published');
    text(root, '[data-v13-boundary]', dateText(data.fresh_evidence_boundary_utc));
    text(root, '[data-v13-context-status]', words(data.context_status));
    text(root, '[data-v13-context-target]', dateText(data.context_target_session));
    text(root, '[data-v13-context-source]', dateText(data.context_source_decision_session));
    text(root, '[data-v13-context-ranking-sha]', data.context_ranking_sha256 || 'Not published');
    text(root, '[data-v13-context-control-sha]', data.context_control_context_sha256 || 'Not published');
    text(root, '[data-v13-next-window]', datetimeText(data.next_decision_window_utc));

    const completed = Number(data.completed_sessions || 0);
    const minimum = Number(data.minimum_completed_sessions || 60);
    const eligible = Number(data.regime_eligible_sessions || 0);
    const eligibleMinimum = Number(data.minimum_regime_eligible_sessions || 15);
    text(root, '[data-v13-sessions]', `${completed} / ${minimum}`);
    text(root, '[data-v13-regime]', `${eligible} / ${eligibleMinimum}`);
    root.querySelector('[data-v13-sessions-bar]')?.style.setProperty('--v13-progress', `${percent(completed, minimum)}%`);
    root.querySelector('[data-v13-regime-bar]')?.style.setProperty('--v13-progress', `${percent(eligible, eligibleMinimum)}%`);

    const gates = data.confirmation_gates || {};
    const returnDelta = Number(gates.annualized_return_delta_minimum);
    text(
      root,
      '[data-v13-return-gate]',
      Number.isFinite(returnDelta)
        ? `≥ +${(returnDelta * 100).toFixed(1)} percentage points annualized net return versus V10 control`
        : 'Annualized net return delta versus V10 control —'
    );
    text(root, '[data-v13-win-gate]', `≥ ${percentText(gates.paired_session_win_rate_minimum)} paired-session win rate`);
    text(root, '[data-v13-turnover-gate]', `≤ ${numberText(gates.turnover_control_multiple_maximum)}× control turnover`);
    text(root, '[data-v13-feasibility-gate]', `${percentText(gates.small_account_feasibility_pass_rate)} small-account feasibility`);

    const failures = root.querySelector('[data-v13-failures]');
    if (failures) {
      failures.replaceChildren();
      const rows = Array.isArray(data.operational_failures) ? data.operational_failures : [];
      const messages = rows.length ? rows : ['No active operational failures.'];
      messages.forEach(message => {
        const item = document.createElement('li');
        item.textContent = String(message).replaceAll('_', ' ');
        failures.appendChild(item);
      });
    }
  }

  async function load() {
    const root = document.getElementById('v13-regime-overlay-status');
    if (!root) return;
    try {
      const response = await fetch('/api/v13/regime-overlay', {cache:'no-store', credentials:'same-origin'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(root, await response.json());
    } catch (error) {
      text(root, '[data-v13-display]', 'STATUS UNAVAILABLE');
      text(root, '[data-v13-health]', 'READ-ONLY API ERROR');
      const failures = root.querySelector('[data-v13-failures]');
      if (failures) {
        failures.replaceChildren();
        const item = document.createElement('li');
        item.textContent = `Dashboard status could not be loaded: ${error.message}`;
        failures.appendChild(item);
      }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load, {once:true});
  else load();
})();
