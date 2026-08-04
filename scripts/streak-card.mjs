// Renders the streak card from GitHub's own contribution calendar.
// Replaces streak-stats.demolab.com so the README stops depending on a
// third-party instance being up at the moment someone loads the profile.

const USER = process.env.USERNAME ?? process.env.GITHUB_REPOSITORY_OWNER;
const TOKEN = process.env.GITHUB_TOKEN;
const OUT_DIR = process.env.OUT_DIR ?? "dist";

if (!USER) throw new Error("USERNAME (or GITHUB_REPOSITORY_OWNER) is required");
if (!TOKEN) throw new Error("GITHUB_TOKEN is required");

const FONT =
  "'Cascadia Code', ui-monospace, Menlo, Consolas, 'DejaVu Sans Mono', monospace";

const THEMES = {
  dark: {
    file: "streak-dark.svg",
    ring: "#b89aff",
    fire: "#ff6ba0",
    currLabel: "#b89aff",
    currNum: "#f0e8dc",
    sideLabels: "#b9a99e",
    sideNums: "#f0e8dc",
    dates: "#b9a99e",
  },
  light: {
    file: "streak.svg",
    ring: "#8b6fd8",
    fire: "#e0447e",
    currLabel: "#8b6fd8",
    currNum: "#1a0e12",
    sideLabels: "#8a7a72",
    sideNums: "#1a0e12",
    dates: "#8a7a72",
  },
};

async function graphql(query, variables) {
  const res = await fetch("https://api.github.com/graphql", {
    method: "POST",
    headers: {
      Authorization: `bearer ${TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "streak-card",
    },
    body: JSON.stringify({ query, variables }),
  });
  if (!res.ok) throw new Error(`GitHub API ${res.status}: ${await res.text()}`);
  const body = await res.json();
  if (body.errors) throw new Error(JSON.stringify(body.errors));
  return body.data;
}

// contributionsCollection accepts at most one year per call, so walk the
// account's lifetime in yearly windows and stitch the calendars together.
async function fetchContributionDays(login) {
  const { user } = await graphql(
    `query ($login: String!) { user(login: $login) { createdAt } }`,
    { login },
  );
  if (!user) throw new Error(`No such user: ${login}`);

  const created = new Date(user.createdAt);
  const now = new Date();
  const days = new Map();

  for (let year = created.getUTCFullYear(); year <= now.getUTCFullYear(); year++) {
    const from = new Date(Date.UTC(year, 0, 1));
    const to = new Date(Date.UTC(year, 11, 31, 23, 59, 59));
    const data = await graphql(
      `query ($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
          contributionsCollection(from: $from, to: $to) {
            contributionCalendar {
              weeks { contributionDays { date contributionCount } }
            }
          }
        }
      }`,
      {
        login,
        from: (from < created ? created : from).toISOString(),
        to: (to > now ? now : to).toISOString(),
      },
    );
    for (const week of data.user.contributionsCollection.contributionCalendar
      .weeks) {
      for (const day of week.contributionDays) {
        days.set(day.date, day.contributionCount);
      }
    }
  }

  return [...days.entries()]
    .map(([date, count]) => ({ date, count }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function computeStats(days) {
  const total = days.reduce((sum, d) => sum + d.count, 0);
  const first = days.find((d) => d.count > 0) ?? days[0];

  let longest = { length: 0, start: null, end: null };
  let run = { length: 0, start: null, end: null };
  for (const day of days) {
    if (day.count > 0) {
      run = {
        length: run.length + 1,
        start: run.length === 0 ? day.date : run.start,
        end: day.date,
      };
      if (run.length > longest.length) longest = { ...run };
    } else {
      run = { length: 0, start: null, end: null };
    }
  }

  // A quiet today does not break the streak until the day is actually over,
  // so start counting back from yesterday when today is still empty.
  let i = days.length - 1;
  if (i >= 0 && days[i].count === 0) i--;
  let current = { length: 0, start: null, end: null };
  for (; i >= 0 && days[i].count > 0; i--) {
    current = {
      length: current.length + 1,
      start: days[i].date,
      end: current.length === 0 ? days[i].date : current.end,
    };
  }

  return {
    total,
    totalStart: first ? first.date : null,
    current,
    longest,
  };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmt(iso, withYear = true) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}${withYear ? `, ${y}` : ""}`;
}

function range(streak) {
  if (!streak.length) return "—";
  const sameYear = streak.start.slice(0, 4) === streak.end.slice(0, 4);
  if (streak.start === streak.end) return fmt(streak.start);
  return `${fmt(streak.start, !sameYear)} - ${fmt(streak.end)}`;
}

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
}

function render(stats, t) {
  const W = 495;
  const H = 185;
  const [cLeft, cMid, cRight] = [82.5, 247.5, 412.5];

  const text = (x, y, s, fill, size, weight = 400) =>
    `<text x="${x}" y="${y}" text-anchor="middle" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}">${esc(s)}</text>`;
  const num = (x, y, s, fill, size = 28) => text(x, y, s, fill, size, 700);
  const label = (x, y, s, fill) => text(x, y, s, fill, 13, 700);
  // Cross-year ranges ("Feb 10, 2024 - Mar 15, 2025") are wider than a column,
  // so shrink the date line just enough to keep it inside one.
  const COL_W = 158;
  const date = (x, y, s) => {
    const fitted = Math.min(11, COL_W / Math.max(1, s.length * 0.62));
    return text(x, y, s, t.dates, Math.round(fitted * 100) / 100);
  };

  // Side columns sit level with the ring so the three blocks read as one row.
  const side = (x, value, caption, sub) =>
    `<g>${num(x, 75, value, t.sideNums)}${label(x, 103, caption, t.sideLabels)}${date(x, 123, sub)}</g>`;

  const totalRange = stats.totalStart ? `${fmt(stats.totalStart)} - Present` : "";
  const flame = `<path transform="translate(${cMid - 12} 4)" d="M12 23 C 6.5 23 3 19.5 3 15.5 C 3 9.5 9 7 10 0 C 12 3.5 12.5 7 11.5 10.5 C 13 8.5 14 6.5 14 4 C 18 8 21 12 21 16 C 21 20 17.5 23 12 23 Z" fill="${t.fire}" />`;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="GitHub streak: ${stats.current.length} day current streak, ${stats.longest.length} day longest streak, ${stats.total} total contributions">
${side(cLeft, stats.total, "Total Contributions", totalRange)}
  <g>
    ${flame}
    <circle cx="${cMid}" cy="80" r="38" fill="none" stroke="${t.ring}" stroke-width="4" />
    ${num(cMid, 91, stats.current.length, t.currNum, 32)}
    ${label(cMid, 141, "Current Streak", t.currLabel)}
    ${date(cMid, 161, range(stats.current))}
  </g>
${side(cRight, stats.longest.length, "Longest Streak", range(stats.longest))}
</svg>
`;
}

const { writeFile, mkdir } = await import("node:fs/promises");

const days = await fetchContributionDays(USER);
const stats = computeStats(days);
await mkdir(OUT_DIR, { recursive: true });
for (const theme of Object.values(THEMES)) {
  await writeFile(`${OUT_DIR}/${theme.file}`, render(stats, theme));
}
console.log(
  `streak card: total=${stats.total} current=${stats.current.length} longest=${stats.longest.length}`,
);
