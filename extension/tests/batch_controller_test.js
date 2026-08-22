"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
require(path.join(__dirname, "..", "batch_controller.js"));

async function main() {
  const saved = {}, events = [];
  let virtualNow = 0;
  const waits = [];
  const progress = [];
  const u1 = "https://www.threads.net/@fixture/post/U1";
  const u2 = "https://www.threads.net/@fixture/post/U2";
  const u3 = "https://www.threads.net/@fixture/post/U3";
  const claims = [
    { queue_item_id: 11, batch_id: 7, attempt: 1, lease_version: 2, post_url: u1 },
    { queue_item_id: 12, batch_id: 7, attempt: 1, lease_version: 3, post_url: u2 },
    { queue_item_id: 13, batch_id: 7, attempt: 2, lease_version: 4, post_url: u3 },
  ];
  const storage = {
    async set(value) { Object.assign(saved, value); },
    async get(key) { return { [key]: saved[key] }; },
  };
  const transport = {
    async startBatch(limit) { events.push(["start", limit]); return { accepted: true, batchId: 7 }; },
    async resumeBatch(batchId) { events.push(["resume", batchId]); return { accepted: true, batchId }; },
    async claimNext(batchId) { return { accepted: true, claim: claims.shift() || null }; },
    async queueSummary(batchId) { return { accepted: true, status: "COMPLETE", batchId }; },
    async finishBatch(batchId, stopped) { events.push(["finish", batchId, stopped]); return { accepted: true }; },
    async sendObservation(observation) {
      events.push(["observation", observation.post_url]);
      return { accepted: true, observationId: observation.post_url === u1 ? 101 : 103 };
    },
    async sendThreadSequence(sequence) { events.push(["sequence", sequence.nodes]); return { accepted: true }; },
    async completeClaim(value) { events.push(["complete", value]); return { accepted: true }; },
    async failClaim(value) { events.push(["fail", value]); return { accepted: true }; },
  };
  const tabWorker = {
    async open(url) { events.push(["open", url]); return 42; },
    async navigate(id, url) { events.push(["navigate", url]); return id; },
    async extract(_id, url) {
      events.push(["extract", url]);
      if (url === u2) throw new Error("isolated failure");
      return { ok: true, observation: { post_url: url, collected_at: "2026-08-16T00:00:00Z",
        public_counters: { view_count: url === u3 ? null : 0 } },
        childObservations: [{ post_url: url + "-child", collected_at: "2026-08-16T00:00:00Z" }], nodes: [
        { post_url: url, sequence_position: 0, reply_to_post_url: null, same_author_as_root: null },
        { post_url: url + "-child", sequence_position: 1, reply_to_post_url: url, same_author_as_root: null },
      ] };
    },
    async close(id) { events.push(["close", id]); },
  };
  const controller = globalThis.SCE_DETAIL_BATCH.createController({
    transport, tabWorker, storage,
    minimumInterItemIntervalMs: 4000,
    now: () => virtualNow,
    setTimeout(callback, milliseconds) {
      waits.push(milliseconds);
      virtualNow += milliseconds;
      queueMicrotask(callback);
      return waits.length;
    },
    onProgress(value) { progress.push(value); },
  });
  assert.equal((await controller.start(3)).accepted, true);
  assert.deepEqual(events.find((item) => item[0] === "resume"), ["resume", 7],
    "a duplicate-safe start recovers any stale processing lease before claim");
  assert.equal(events.filter((item) => item[0] === "open").length, 1);
  assert.equal(events.filter((item) => item[0] === "navigate").length, 2);
  assert.deepEqual(waits, [4000, 4000],
    "fixed minimum interval is applied before each later navigation without real sleeping");
  assert.equal(progress.filter((item) => item.status === "WAITING_NEXT_ITEM").length, 2);
  assert.equal(events.findIndex((item) => item[0] === "complete")
    < events.findIndex((item) => item[0] === "navigate"), true,
  "ingestion completion is persisted before the next navigation");
  assert.equal(events.some((item) => item[0] === "extract" && item[1] === u3), true);
  assert.equal(events.find((item) => item[0] === "sequence")[1].length, 2,
    "accepted child observation is sent before its sequence identity");
  assert.equal(events.findIndex((item) => item[0] === "observation" && item[1] === u1 + "-child")
    < events.findIndex((item) => item[0] === "sequence"), true);
  assert.deepEqual(events.find((item) => item[0] === "finish").slice(1), [7, false]);
  assert.deepEqual(events.find((item) => item[0] === "complete")[1], {
    queue_item_id: 11, batch_id: 7, attempt: 1, lease_version: 2, detail_observation_id: 101,
  });
  assert.deepEqual(events.find((item) => item[0] === "fail")[1], {
    queue_item_id: 12, batch_id: 7, attempt: 1, lease_version: 3, error_code: "PAGE_TIMEOUT",
  });
  assert.equal(events.filter((item) => item[0] === "fail").length, 1,
    "missing exact Views does not fail an otherwise valid detail observation");
  assert.deepEqual(events.filter((item) => item[0] === "complete")[1][1], {
    queue_item_id: 13, batch_id: 7, attempt: 2, lease_version: 4,
    detail_observation_id: 103,
  });
  assert.equal(saved[globalThis.SCE_DETAIL_BATCH.storageKey], null,
    "storage is a resume hint, not the durable queue SSOT");

  const sequenceEvents = [];
  let sequenceClaimed = false;
  const sequenceFailure = globalThis.SCE_DETAIL_BATCH.createController({
    transport: { ...transport,
      async startBatch() { return { accepted: true, batchId: 10 }; },
      async claimNext() {
        if (sequenceClaimed) return { accepted: true, claim: null };
        sequenceClaimed = true;
        return { accepted: true, claim: {
          queue_item_id: 20, batch_id: 10, attempt: 1, lease_version: 1, post_url: u1,
        } };
      },
      async sendThreadSequence() { return { accepted: false, reason: "receiver_rejected" }; },
      async failClaim(value) { sequenceEvents.push(["fail", value]); return { accepted: true }; },
      async completeClaim(value) { sequenceEvents.push(["complete", value]); return { accepted: true }; },
    }, tabWorker, storage, minimumInterItemIntervalMs: 0,
  });
  assert.equal((await sequenceFailure.start(1)).accepted, true);
  assert.equal(sequenceEvents.some((item) => item[0] === "fail"), false);
  assert.equal(sequenceEvents[0][0], "complete",
    "missing optional sequence leaves relationships unknown without failing valid detail");

  saved[globalThis.SCE_DETAIL_BATCH.storageKey] = { batch_id: 8, worker_tab_id: 77 };
  const resumeTransport = { ...transport,
    async resumeBatch(batchId) { return { accepted: true, batchId }; },
    async claimNext() { return { accepted: true, claim: null }; } };
  assert.equal((await globalThis.SCE_DETAIL_BATCH.createController({
    transport: resumeTransport, tabWorker, storage, minimumInterItemIntervalMs: 0,
  }).resume()).accepted, true);
  assert.equal(events.some((item) => item[0] === "close" && item[1] === 77), true,
    "resume closes the prior dedicated worker tab before opening a replacement");

  const resumeWaits = [];
  let resumedClaimed = false;
  saved[globalThis.SCE_DETAIL_BATCH.storageKey] = {
    batch_id: 18, worker_tab_id: null, total: 1, last_item_started_at_ms: 0,
  };
  const pacedResume = globalThis.SCE_DETAIL_BATCH.createController({
    transport: { ...transport,
      async resumeBatch(batchId) { return { accepted: true, batchId }; },
      async claimNext() {
        if (resumedClaimed) return { accepted: true, claim: null };
        resumedClaimed = true;
        return { accepted: true, claim: {
          queue_item_id: 30, batch_id: 18, attempt: 1, lease_version: 1, post_url: u1,
        } };
      },
    },
    tabWorker, storage, minimumInterItemIntervalMs: 4000, now: () => 2000,
    setTimeout(callback, milliseconds) {
      resumeWaits.push(milliseconds); queueMicrotask(callback); return 1;
    },
  });
  assert.equal((await pacedResume.resume()).accepted, true);
  assert.deepEqual(resumeWaits, [2000],
    "resume preserves the remaining fixed interval after an interrupted wait");

  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const locked = globalThis.SCE_DETAIL_BATCH.createController({
    transport: { ...transport, async startBatch() { await held; return { accepted: true, batchId: 9 }; },
      async claimNext() { return { accepted: true, claim: null }; },
    }, tabWorker, storage, minimumInterItemIntervalMs: 0,
  });
  const first = locked.start();
  assert.deepEqual(await locked.resume(), { accepted: false, reason: "batch_already_running" });
  release(); await first;

  const broker = globalThis.SCE_DETAIL_BATCH.createWorkerResultBroker({ timeoutMilliseconds: 1000 });
  let command;
  const pending = broker.request(42, (message) => { command = message; }, "u1");
  await assert.rejects(() => broker.request(43, () => {}, "u2"), /worker_busy/);
  assert.equal(broker.accept({ correlation: "stale", result: {} }, { tab: { id: 42 } }), false);
  assert.equal(broker.accept({ correlation: command.correlation, result: {} }, { tab: { id: 99 } }), false);
  assert.equal(broker.accept({ correlation: command.correlation, result: { ok: true } }, { tab: { id: 42 } }), true);
  assert.equal(command.domReadyTimeoutMilliseconds, 8000,
    "DOM-ready timeout is explicit and separate from the broker extraction timeout");
  assert.deepEqual(await pending, { ok: true });
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
