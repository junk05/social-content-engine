"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

globalThis.chrome = { runtime: { id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } };
require(path.join(__dirname, "..", "review_export_download.js"));

async function main() {
  const downloader = globalThis.SCE_REVIEW_EXPORT_DOWNLOAD;
  let request;
  let clicked;
  let revoked;
  const csv = new Blob(["\ufeffauthor_username,post_url,source_text\r\n作者,https://www.threads.net/@a/post/1,日本語\r\n"], {
    type: "text/csv; charset=utf-8",
  });
  const result = await downloader.download("POSTS", "DETAIL_ENRICHED", {
    fetch: async (url, options) => {
      request = { url, options };
      return {
        status: 200,
        headers: { get(name) { return name === "Content-Type" ? "text/csv; charset=utf-8" : null; } },
        async blob() { return csv; },
      };
    },
    document: {
      createElement(tag) {
        assert.equal("a", tag);
        return { click() { clicked = { href: this.href, download: this.download }; } };
      },
    },
    urlApi: {
      createObjectURL(blob) { assert.equal(blob, csv); return "blob:review-csv"; },
      revokeObjectURL(url) { revoked = url; },
    },
    setTimeout(callback, milliseconds) { assert.equal(milliseconds, 0); callback(); },
  });
  assert.deepEqual(result, { accepted: true, filename: "threads_posts.csv" });
  assert.equal(
    request.url,
    downloader.EXPORT_URL + "?kind=POSTS&status=DETAIL_ENRICHED",
  );
  assert.equal(request.options.credentials, "omit");
  assert.equal(
    request.options.headers["X-SCE-Extension-Origin"],
    "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  );
  assert.deepEqual(clicked, { href: "blob:review-csv", download: "threads_posts.csv" });
  assert.equal(revoked, "blob:review-csv");
  assert.equal((await csv.text()).includes("日本語"), true);

  assert.deepEqual(await downloader.download("UNKNOWN", "ALL"), {
    accepted: false, reason: "invalid_export_request",
  });
  assert.deepEqual(await downloader.download("THREAD_NODES", "UNKNOWN"), {
    accepted: false, reason: "invalid_export_request",
  });
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
