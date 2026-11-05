import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { collectActivity, createGitHubRequest, OWNER, REPOSITORIES, utcWindow, validateActivity } from "./fetch-profile-activity.mjs";

const NOW = new Date("2026-11-05T18:00:00Z");
const UNTIL = "2026-11-05";
const sha = (value) => value.toString(16).padStart(40, "0");
const commit = (id, date, login = OWNER) => ({
  sha: sha(id),
  author: { login },
  commit: {
    author: { date: "2000-01-01T00:00:00Z", email: "not-for-export@example.test" },
    committer: { date },
    message: "This commit message must never enter the activity snapshot",
  },
  parents: [{ sha: sha(1001) }, { sha: sha(1002) }],
});

function fakeGitHub({ pages = [], metadata = {} } = {}) {
  const calls = [];
  const request = async (endpoint) => {
    calls.push(endpoint);
    const url = new URL(endpoint, "https://api.github.com");
    const name = url.pathname.split("/")[3];
    assert.ok(REPOSITORIES.includes(name));
    if (url.pathname.endsWith(`/repos/${OWNER}/${name}`)) {
      return {
        name,
        full_name: `${OWNER}/${name}`,
        owner: { login: OWNER },
        private: false,
        visibility: "public",
        fork: false,
        html_url: `https://github.com/${OWNER}/${name}`,
        default_branch: "main",
        stargazers_count: 2,
        language: "JavaScript",
        pushed_at: "2026-11-04T23:00:00Z",
        ...metadata,
      };
    }
    if (url.pathname.endsWith("/branches/main")) return { commit: { sha: sha(900) } };
    assert.ok(url.pathname.endsWith("/commits"));
    assert.equal(url.searchParams.get("author"), OWNER);
    assert.equal(url.searchParams.get("sha"), sha(900));
    assert.equal(url.searchParams.get("per_page"), "100");
    const page = Number(url.searchParams.get("page"));
    const response = name === REPOSITORIES[0] ? pages[page - 1] ?? [] : [];
    if (response instanceof Error) throw response;
    return response;
  };
  return { request, calls };
}

test("the window contains exactly 84 complete UTC dates, including leap days", () => {
  const window = utcWindow(UNTIL, NOW);
  assert.equal(window.from, "2026-08-13");
  assert.equal(window.to, "2026-11-04");
  assert.equal(window.dates.length, 84);
  assert.equal(utcWindow(undefined, new Date("2026-11-05T23:59:59Z")).to, "2026-11-04");
  const leap = utcWindow("2024-03-01", NOW);
  assert.equal(leap.dates.at(-1), "2024-02-29");
  assert.equal(new Set(leap.dates).size, 84);
  assert.throws(() => utcWindow("2026-02-30", NOW), /valid calendar date/);
  assert.throws(() => utcWindow("2026-11-06", NOW), /incomplete or future/);
  assert.throws(() => utcWindow("11-05-2026", NOW), /YYYY-MM-DD/);
});

test("pagination counts pinned-head author commits once and applies exact date boundaries", async () => {
  const firstPage = Array.from({ length: 100 }, (_, index) => commit(index + 1, "2026-08-13T00:00:00Z"));
  const api = fakeGitHub({ pages: [firstPage, [
    firstPage[5],
    commit(101, "2026-11-04T23:59:59Z"),
    commit(102, "2026-11-05T00:00:00Z"),
    commit(103, "2026-08-12T23:59:59Z"),
  ]] });
  const data = await collectActivity({ until: UNTIL, now: NOW, request: api.request });
  assert.equal(data.total, 101);
  assert.equal(data.daily[0].count, 100);
  assert.equal(data.daily.at(-1).count, 1);
  assert.equal(data.repositories[0].total, 101);
  assert.ok(data.repositories.slice(1).every((repository) => repository.total === 0));
  assert.ok(api.calls.some((endpoint) => endpoint.includes("page=2")));
  assert.equal(api.calls.filter((endpoint) => endpoint.includes("page=3")).length, 0);
  assert.ok(!JSON.stringify(data).includes("not-for-export"));
  assert.ok(!JSON.stringify(data).includes("This commit message"));
  assert.match(data.scope, /including merge commits/);
  validateActivity(data);
});

test("private or unconfirmed repository visibility stops collection before reading commits", async () => {
  for (const metadata of [{ private: true, visibility: "private" }, { visibility: undefined }, { owner: { login: "somebody-else" } }]) {
    const api = fakeGitHub({ metadata });
    await assert.rejects(collectActivity({ until: UNTIL, now: NOW, request: api.request }), /public|expected user-owned/);
    assert.equal(api.calls.length, 1);
  }
});

test("a failed later page cannot turn partial data into a successful snapshot", async () => {
  const firstPage = Array.from({ length: 100 }, (_, index) => commit(index + 1, "2026-09-01T12:00:00Z"));
  const api = fakeGitHub({ pages: [firstPage, new Error("API rate limit")] });
  await assert.rejects(collectActivity({ until: UNTIL, now: NOW, request: api.request }), /API rate limit/);
});

test("unexpected authors, malformed timestamps and malformed pages fail instead of becoming zeroes", async () => {
  for (const page of [
    [commit(1, "2026-09-01T12:00:00Z", "somebody-else")],
    [commit(1, "invalid-date")],
    { message: "API unavailable" },
  ]) {
    const api = fakeGitHub({ pages: [page] });
    await assert.rejects(collectActivity({ until: UNTIL, now: NOW, request: api.request }), /author scope|timestamp|commit page/);
  }
});

test("HTTP failures report the status without logging tokens or response bodies", async () => {
  const request = createGitHubRequest({
    token: "test-token-do-not-log",
    fetchImpl: async () => new Response("response body must stay private", { status: 403 }),
  });
  await assert.rejects(request(`/repos/${OWNER}/${REPOSITORIES[0]}`), (error) => {
    assert.match(error.message, /HTTP 403/);
    assert.ok(!error.message.includes("test-token"));
    assert.ok(!error.message.includes("response body"));
    return true;
  });
});

test("the validator rejects changed totals, negative counts and missing days", async () => {
  const data = await collectActivity({ until: UNTIL, now: NOW, request: fakeGitHub().request });
  const wrongTotal = structuredClone(data);
  wrongTotal.total = 1;
  assert.throws(() => validateActivity(wrongTotal), /total/);
  const negative = structuredClone(data);
  negative.repositories[0].daily[0].count = -1;
  assert.throws(() => validateActivity(negative), /count or date/);
  const missingDay = structuredClone(data);
  missingDay.daily.pop();
  assert.throws(() => validateActivity(missingDay), /Incomplete/);
});

test("the checked-in real snapshot is complete and contains only approved public aggregate fields", async () => {
  const data = JSON.parse(await readFile(new URL("../design/data/activity.json", import.meta.url), "utf8"));
  validateActivity(data);
  assert.deepEqual(Object.keys(data), ["schema_version", "fetched_at", "from", "to", "days", "timezone", "scope", "repositories", "daily", "total"]);
  for (const repository of data.repositories) {
    assert.deepEqual(Object.keys(repository), ["name", "url", "stars", "language", "default_branch", "head_sha", "pushed_at", "daily", "total"]);
    for (const day of repository.daily) assert.deepEqual(Object.keys(day), ["date", "count"]);
  }
});
