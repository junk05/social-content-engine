"use strict";

(function exposeDetailBatchController(scope) {
  const STORAGE_KEY = "sce_detail_batch_v1";

  function createWorkerResultBroker(dependencies = {}) {
    const setTimer = dependencies.setTimeout || setTimeout;
    const clearTimer = dependencies.clearTimeout || clearTimeout;
    const timeoutMilliseconds = dependencies.timeoutMilliseconds || 15000;
    let serial = 0;
    let pending = null;

    function request(tabId, dispatch, url) {
      if (pending) return Promise.reject(new Error("worker_busy"));
      const correlation = "detail-" + tabId + "-" + (++serial);
      return new Promise((resolve, reject) => {
        const timer = setTimer(() => {
          pending = null;
          reject(new Error("worker_timeout"));
        }, timeoutMilliseconds);
        pending = { tabId, correlation, resolve, reject, timer };
        Promise.resolve(dispatch({ type: "SCE_BATCH_EXTRACT_DETAIL", url, correlation }))
          .catch((error) => {
            if (!pending || pending.correlation !== correlation) return;
            clearTimer(pending.timer);
            pending = null;
            reject(error);
          });
      });
    }

    function accept(message, sender) {
      if (!pending || !message || message.correlation !== pending.correlation
          || !sender || !sender.tab || sender.tab.id !== pending.tabId) return false;
      const current = pending;
      pending = null;
      clearTimer(current.timer);
      current.resolve(message.result);
      return true;
    }

    return Object.freeze({ request, accept, isPending: () => Boolean(pending) });
  }

  function createController(dependencies) {
    const { transport, tabWorker, storage } = dependencies;
    let running = false;

    async function persist(state) {
      await storage.set({ [STORAGE_KEY]: state });
    }

    function correlation(claim) {
      return {
        queue_item_id: claim.queue_item_id, batch_id: claim.batch_id,
        attempt: claim.attempt, lease_version: claim.lease_version,
      };
    }
    function validClaim(claim, batchId) {
      let canonicalUrl = false;
      try {
        const parsed = new URL(claim && claim.post_url);
        canonicalUrl = parsed.protocol === "https:" && parsed.hostname === "www.threads.net"
          && /^\/@[A-Za-z0-9._-]+\/post\/[A-Za-z0-9._-]+$/.test(parsed.pathname)
          && !parsed.search && !parsed.hash;
      } catch (_error) { canonicalUrl = false; }
      return claim && Number.isInteger(claim.queue_item_id) && claim.queue_item_id > 0
        && claim.batch_id === batchId && Number.isInteger(claim.attempt) && claim.attempt > 0
        && Number.isInteger(claim.lease_version) && claim.lease_version > 0
        && canonicalUrl;
    }

    async function run(batchId) {
      await persist({ batch_id: batchId, worker_tab_id: null });
      let tabId = null;
      try {
        while (true) {
          const claimed = await transport.claimNext(batchId);
          if (!claimed.accepted) return claimed;
          const claim = claimed.claim;
          if (!claim) {
            const finished = await transport.finishBatch(batchId, false);
            if (!finished.accepted) return finished;
            break;
          }
          if (!validClaim(claim, batchId)) {
            return { accepted: false, reason: "invalid_claim_response" };
          }
          const url = claim.post_url;
          try {
            tabId = tabId === null ? await tabWorker.open(url) : await tabWorker.navigate(tabId, url);
            await persist({ batch_id: batchId, worker_tab_id: tabId });
            const extracted = await tabWorker.extract(tabId, url);
            if (!extracted || !extracted.ok || !extracted.observation) {
              const reasonCodes = {
                dom_not_ready: "PAGE_TIMEOUT",
                activity_button_not_found: "ACTIVITY_BUTTON_NOT_FOUND",
                activity_dialog_timeout: "ACTIVITY_DIALOG_TIMEOUT",
              };
              const failure = await transport.failClaim({
                ...correlation(claim), error_code: reasonCodes[extracted && extracted.reason]
                  || "EXTRACTOR_MISMATCH",
              });
              if (!failure.accepted) return failure;
            } else {
              const accepted = await transport.sendObservation(extracted.observation);
              if (!accepted.accepted) {
                const failure = await transport.failClaim({
                  ...correlation(claim), error_code: "INGESTION_FAILED",
                });
                if (!failure.accepted) return failure;
              } else {
                const acceptedUrls = new Set([extracted.observation.post_url]);
                for (const child of Array.isArray(extracted.childObservations)
                  ? extracted.childObservations : []) {
                  const childAccepted = await transport.sendObservation(child);
                  if (childAccepted.accepted) acceptedUrls.add(child.post_url);
                }
                const observableNodes = Array.isArray(extracted.nodes)
                  ? extracted.nodes.filter((node) => acceptedUrls.has(node.post_url)) : [];
                if (!Number.isInteger(accepted.observationId)) {
                  const failure = await transport.failClaim({
                    ...correlation(claim), error_code: "INGESTION_FAILED",
                  });
                  if (!failure.accepted) return failure;
                  continue;
                }
                if (observableNodes.length > 0) {
                  try {
                    await transport.sendThreadSequence({
                      root_post_url: extracted.observation.post_url,
                      nodes: observableNodes,
                      detail_observation_id: accepted.observationId,
                      observed_at: extracted.observation.collected_at,
                      extractor_version: "threads_post_detail_extractor_v1",
                    });
                  } catch (_sequenceError) {
                    // Sequence evidence is optional; never infer it or fail valid root detail.
                  }
                }
                const completed = await transport.completeClaim({
                  ...correlation(claim), detail_observation_id: accepted.observationId,
                });
                if (!completed.accepted) return completed;
              }
            }
          } catch (_error) {
            const failure = await transport.failClaim({
              ...correlation(claim), error_code: "PAGE_TIMEOUT",
            });
            if (!failure.accepted) return failure;
          }
        }
        const summary = await transport.queueSummary(batchId);
        await storage.set({ [STORAGE_KEY]: null });
        return summary;
      } finally {
        if (tabId !== null) await tabWorker.close(tabId);
      }
    }

    async function exclusively(action) {
      if (running) return { accepted: false, reason: "batch_already_running" };
      running = true;
      try { return await action(); } finally { running = false; }
    }

    async function start(limit = 50) {
      return exclusively(async () => {
      const started = await transport.startBatch(limit);
      if (!started.accepted || !Number.isInteger(started.batchId)) return started;
      // `start` is duplicate-safe in the Source Store and can return a batch
      // left RUNNING by a service-worker restart. Recover its stale lease
      // before the first claim rather than requiring a different user action.
      const resumed = await transport.resumeBatch(started.batchId);
      if (!resumed.accepted) return resumed;
      return run(started.batchId);
      });
    }

    async function resume() {
      return exclusively(async () => {
      const stored = await storage.get(STORAGE_KEY);
      const hint = stored[STORAGE_KEY];
      if (!hint || !Number.isInteger(hint.batch_id)) {
        return { accepted: false, reason: "no_resumable_batch" };
      }
      const resumed = await transport.resumeBatch(hint.batch_id);
      if (!resumed.accepted) {
        await storage.set({ [STORAGE_KEY]: null });
        return resumed;
      }
      if (Number.isInteger(hint.worker_tab_id)) {
        try { await tabWorker.close(hint.worker_tab_id); } catch (_staleTabError) {
          // The previous dedicated tab may already have disappeared after a restart.
        }
      }
      return run(hint.batch_id);
      });
    }

    return Object.freeze({ start, resume, run });
  }

  scope.SCE_DETAIL_BATCH = Object.freeze({
    storageKey: STORAGE_KEY, createController, createWorkerResultBroker,
  });
})(globalThis);
