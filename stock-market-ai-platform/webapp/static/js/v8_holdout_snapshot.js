(() => {
  if (window.DataShepherdV8Snapshot) return;

  const MAX_AGE_MS = 25000;
  let payload = null;
  let fetchedAt = null;
  let inFlight = null;
  let lastError = null;

  const get = async ({force = false} = {}) => {
    const age = fetchedAt ? Date.now() - fetchedAt.getTime() : Infinity;
    if (!force && payload && age < MAX_AGE_MS) return payload;
    if (inFlight) return inFlight;

    inFlight = fetch('/api/v8/holdout', {cache: 'no-store'})
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(next => {
        payload = Object.freeze(next);
        fetchedAt = new Date();
        lastError = null;
        window.dispatchEvent(new CustomEvent('datashepherd:v8-snapshot', {
          detail: {payload, fetchedAtUtc: fetchedAt.toISOString()}
        }));
        return payload;
      })
      .catch(error => {
        lastError = error;
        if (payload) return payload;
        throw error;
      })
      .finally(() => { inFlight = null; });
    return inFlight;
  };

  window.DataShepherdV8Snapshot = Object.freeze({
    get,
    info: () => ({
      fetchedAtUtc: fetchedAt?.toISOString() || null,
      stale: Boolean(fetchedAt && Date.now() - fetchedAt.getTime() >= MAX_AGE_MS),
      lastError: lastError?.message || null,
      maxAgeMs: MAX_AGE_MS,
    }),
  });
})();
