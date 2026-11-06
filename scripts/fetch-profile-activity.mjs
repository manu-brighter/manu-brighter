import { execFile } from "node:child_process";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

export const OWNER = "manu-brighter";
export const REPOSITORIES = Object.freeze([
  "joggediballa-mainpage",
  "fly-connectome-sim",
  "claude-code-kit",
  "manus-portfolio",
]);
const DAY = 86_400_000;
const MONTHS = 12;
const execute = promisify(execFile);
const SCOPE = "Public commits authored by manu-brighter on each listed repository's default branch, including merge commits. Grouped by UTC committer date across 12 calendar months; the last month may be partial and contains only complete UTC days. Each default-branch head is pinned before pagination. This is project commit activity, not GitHub contribution totals.";

export function utcWindow(until, now = new Date()) {
  const boundary = until ?? now.toISOString().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(boundary)) throw new Error("--until must be YYYY-MM-DD");
  const end = Date.parse(`${boundary}T00:00:00Z`);
  if (!Number.isFinite(end) || new Date(end).toISOString().slice(0, 10) !== boundary) {
    throw new Error("--until is not a valid calendar date");
  }
  if (boundary > now.toISOString().slice(0, 10)) throw new Error("--until cannot include incomplete or future UTC days");
  const lastDay = new Date(end - DAY);
  const startMonth = lastDay.getUTCMonth() - (MONTHS - 1);
  const start = Date.UTC(lastDay.getUTCFullYear(), startMonth, 1);
  if (start < Date.parse("1970-01-02T00:00:00Z") || end > Date.parse("2099-12-31T00:00:00Z")) {
    throw new Error("Window is outside GitHub's supported Git timestamp range");
  }
  const dates = Array.from({ length: (end - start) / DAY }, (_, index) => new Date(start + index * DAY).toISOString().slice(0, 10));
  const months = Array.from({ length: MONTHS }, (_, index) => new Date(Date.UTC(lastDay.getUTCFullYear(), startMonth + index, 1)).toISOString().slice(0, 7));
  return { start, end, dates, months, from: dates[0], to: dates.at(-1) };
}

export function createGitHubRequest({ token = process.env.GITHUB_TOKEN, fetchImpl = fetch } = {}) {
  return async (endpoint) => {
    if (!endpoint.startsWith(`/repos/${OWNER}/`)) throw new Error("Unexpected GitHub API path");
    if (token) {
      let response;
      try {
        response = await fetchImpl(`https://api.github.com${endpoint}`, {
          headers: {
            Accept: "application/vnd.github+json",
            Authorization: `Bearer ${token}`,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "manu-brighter-profile-activity",
          },
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        });
      } catch {
        throw new Error("GitHub API request failed; existing activity data was not replaced");
      }
      if (!response.ok) throw new Error(`GitHub API returned HTTP ${response.status}; activity refresh aborted`);
      try {
        return await response.json();
      } catch {
        throw new Error("GitHub API returned invalid JSON");
      }
    }

    // Let gh use its own authenticated session; never extract or print its token.
    const candidates = ["gh"];
    if (process.platform === "win32") {
      candidates.push(join(process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"), "Microsoft", "WinGet", "Packages", "GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe", "bin", "gh.exe"));
    }
    for (const candidate of candidates) {
      try {
        const { stdout } = await execute(candidate, [
          "api", "--method", "GET", endpoint,
          "-H", "Accept: application/vnd.github+json",
          "-H", "X-GitHub-Api-Version: 2022-11-28",
        ], {
          encoding: "utf8",
          maxBuffer: 8 * 1024 * 1024,
          timeout: 30_000,
          windowsHide: true,
          env: { ...process.env, GH_PROMPT_DISABLED: "1", NO_COLOR: "1" },
        });
        return JSON.parse(stdout);
      } catch (error) {
        if (error.code === "ENOENT") continue;
        throw new Error("gh api failed; check GitHub authentication and API availability. Existing activity data was not replaced.");
      }
    }
    throw new Error("Set GITHUB_TOKEN or make the authenticated gh CLI available");
  };
}

function assertRepository(metadata, name) {
  if (metadata?.private !== false || metadata?.visibility !== "public") {
    throw new Error(`${name} is not explicitly public; refusing to collect its commits`);
  }
  if (metadata.full_name !== `${OWNER}/${name}` || metadata.owner?.login !== OWNER || metadata.fork !== false) {
    throw new Error(`${name} is not the expected user-owned repository`);
  }
  if (metadata.html_url !== `https://github.com/${OWNER}/${name}` || typeof metadata.default_branch !== "string" || !metadata.default_branch) {
    throw new Error(`${name} has invalid repository metadata`);
  }
  if (!Number.isSafeInteger(metadata.stargazers_count) || metadata.stargazers_count < 0) {
    throw new Error(`${name} has an invalid star count`);
  }
  if (metadata.language !== null && typeof metadata.language !== "string") throw new Error(`${name} has an invalid language`);
  if (metadata.pushed_at !== null && !Number.isFinite(Date.parse(metadata.pushed_at))) throw new Error(`${name} has an invalid push timestamp`);
}

export async function collectActivity({ until, now = new Date(), request = createGitHubRequest() } = {}) {
  const window = utcWindow(until, now);
  const repositories = [];
  for (const name of REPOSITORIES) {
    const prefix = `/repos/${OWNER}/${name}`;
    const metadata = await request(prefix);
    assertRepository(metadata, name);
    const branch = await request(`${prefix}/branches/${encodeURIComponent(metadata.default_branch)}`);
    const head = branch?.commit?.sha;
    if (!/^[a-f0-9]{40}$/.test(head ?? "")) throw new Error(`${name} has no valid default-branch head`);
    const counts = new Map(window.dates.map((date) => [date, 0]));
    const seen = new Set();
    for (let page = 1; ; page += 1) {
      if (page > 1000) throw new Error(`${name} exceeded the pagination limit; refusing partial data`);
      const params = new URLSearchParams({
        author: OWNER,
        sha: head,
        // Ask across both boundaries, then apply an exact half-open UTC window.
        since: new Date(window.start - 1000).toISOString(),
        until: new Date(window.end).toISOString(),
        per_page: "100",
        page: String(page),
      });
      const commits = await request(`${prefix}/commits?${params}`);
      if (!Array.isArray(commits) || commits.length > 100) throw new Error(`${name} returned an invalid commit page`);
      for (const commit of commits) {
        if (!/^[a-f0-9]{40}$/.test(commit?.sha ?? "")) throw new Error(`${name} returned an invalid commit SHA`);
        if (commit.author?.login?.toLowerCase() !== OWNER) throw new Error(`${name} returned a commit outside the requested author scope`);
        const committed = Date.parse(commit.commit?.committer?.date);
        if (!Number.isFinite(committed)) throw new Error(`${name} returned an invalid commit timestamp`);
        if (seen.has(commit.sha)) continue;
        seen.add(commit.sha);
        if (committed < window.start || committed >= window.end) continue;
        const date = new Date(committed).toISOString().slice(0, 10);
        counts.set(date, counts.get(date) + 1);
      }
      if (commits.length < 100) break;
    }
    const daily = [...counts].map(([date, count]) => ({ date, count }));
    repositories.push({
      name,
      url: metadata.html_url,
      stars: metadata.stargazers_count,
      language: metadata.language,
      default_branch: metadata.default_branch,
      head_sha: head,
      pushed_at: metadata.pushed_at,
      daily,
      total: daily.reduce((sum, day) => sum + day.count, 0),
    });
  }
  const daily = window.dates.map((date, index) => ({
    date,
    count: repositories.reduce((sum, repository) => sum + repository.daily[index].count, 0),
  }));
  const data = {
    schema_version: 2,
    fetched_at: now.toISOString(),
    from: window.from,
    to: window.to,
    days: window.dates.length,
    months: window.months,
    timezone: "UTC",
    scope: SCOPE,
    repositories,
    daily,
    total: daily.reduce((sum, day) => sum + day.count, 0),
  };
  validateActivity(data);
  return data;
}

export function validateActivity(data) {
  if (data?.schema_version !== 2 || !Number.isSafeInteger(data.days) || data.days < 1 || data.timezone !== "UTC" || data.scope !== SCOPE) throw new Error("Invalid activity schema or scope");
  const fetched = new Date(data.fetched_at);
  if (!Number.isFinite(fetched.getTime())) throw new Error("Invalid activity fetch timestamp");
  const until = new Date(Date.parse(`${data.to}T00:00:00Z`) + DAY).toISOString().slice(0, 10);
  const window = utcWindow(until, fetched);
  if (data.from !== window.from || data.to !== window.to || data.days !== window.dates.length) throw new Error("Invalid activity date range");
  if (!Array.isArray(data.months) || data.months.length !== MONTHS || data.months.some((month, index) => month !== window.months[index])) throw new Error("Invalid activity months");
  const validateDays = (daily, total) => {
    if (!Array.isArray(daily) || daily.length !== window.dates.length) throw new Error("Incomplete daily activity data");
    daily.forEach((day, index) => {
      if (day.date !== window.dates[index] || !Number.isSafeInteger(day.count) || day.count < 0) throw new Error("Invalid daily activity count or date");
    });
    if (!Number.isSafeInteger(total) || daily.reduce((sum, day) => sum + day.count, 0) !== total) throw new Error("Activity total does not match its daily counts");
  };
  if (!Array.isArray(data.repositories) || data.repositories.length !== REPOSITORIES.length) throw new Error("Unexpected activity repository set");
  data.repositories.forEach((repository, index) => {
    if (repository.name !== REPOSITORIES[index] || repository.url !== `https://github.com/${OWNER}/${repository.name}`) throw new Error("Unexpected activity repository");
    if (!Number.isSafeInteger(repository.stars) || repository.stars < 0 || !/^[a-f0-9]{40}$/.test(repository.head_sha ?? "")) throw new Error("Invalid activity repository metadata");
    validateDays(repository.daily, repository.total);
  });
  validateDays(data.daily, data.total);
  data.daily.forEach((day, index) => {
    if (day.count !== data.repositories.reduce((sum, repository) => sum + repository.daily[index].count, 0)) throw new Error("Activity aggregate does not match repository counts");
  });
}

async function main() {
  const args = process.argv.slice(2);
  let output = resolve(dirname(fileURLToPath(import.meta.url)), "../design/data/activity.json");
  let until;
  for (let index = 0; index < args.length; index += 1) {
    const option = args[index];
    if (!["--output", "--until"].includes(option) || !args[index + 1] || args[index + 1].startsWith("--")) {
      throw new Error("Usage: node scripts/fetch-profile-activity.mjs [--output path] [--until YYYY-MM-DD]");
    }
    if (option === "--output") output = resolve(args[++index]);
    else until = args[++index];
  }
  const data = await collectActivity({ until });
  await mkdir(dirname(output), { recursive: true });
  const temporary = `${output}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  await rename(temporary, output);
  console.log(`Saved ${data.total} public default-branch commits across ${data.repositories.length} repositories (${data.from} to ${data.to}, UTC).`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
