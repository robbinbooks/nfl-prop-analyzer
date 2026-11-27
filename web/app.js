const state = {
  board: null,
  marketId: "rec_yds",
  sort: "hit",
  direction: "desc",
  streakSide: "over",
  streakMin: 0,
  query: "",
  matchup: "",
  selectedId: null,
  sheetOpen: false,
  lines: new Map(),
};

const listEl = document.querySelector("#list");
const detailEl = document.querySelector("#detail");
const marketsEl = document.querySelector("#markets");

function esc(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function marketById(id) {
  return state.board.markets.find((market) => market.id === id);
}

function lineFor(player) {
  const key = `${player.id}:${state.marketId}`;
  if (state.lines.has(key)) return state.lines.get(key);
  return player.markets[state.marketId].line;
}

function setLine(player, next) {
  const line = Math.max(0.5, Math.round(next * 2) / 2);
  state.lines.set(`${player.id}:${state.marketId}`, line);
}

function lineRange(book, line) {
  const posted = book.sportsbook ? Number(book.sportsbook.line) : line;
  const peak = book.logs.reduce((max, game) => Math.max(max, Number(game.value) || 0), 0);
  const top = Math.max(peak, posted, line);
  return { min: 0.5, max: Math.max(Math.ceil((top + 25) * 2) / 2, line) };
}

function lineMeta(book, line) {
  const source = onBookLine(book, line)
    ? `${book.sportsbook.label} ${book.sportsbook.odds}`
    : book.sportsbook
      ? `Moved off the ${book.sportsbook.label} ${book.sportsbook.line.toFixed(1)}`
      : "Season average";
  return `${source} · avg ${book.seasonAvg}`;
}

function formatLine(line, unit) {
  return `${line.toFixed(1)} ${unit}`;
}

function tone(score) {
  if (score >= 70) return "good";
  if (score >= 50) return "mid";
  return "bad";
}

function grade(logs, line) {
  const recent = logs.slice(-10);
  const dots = recent.map((game) => {
    if (game.value > line) return "hit";
    if (game.value < line) return "miss";
    return "push";
  });
  const decided = dots.filter((dot) => dot !== "push").length;
  const hits = dots.filter((dot) => dot === "hit").length;
  return {
    dots,
    hits,
    decided,
    pct: decided ? Math.round((100 * hits) / decided) : 0,
  };
}

function formatStat(value) {
  return Number.isInteger(value) ? String(value) : Number(value).toFixed(1);
}

function streakFor(logs, line, side) {
  const games = [];
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const game = logs[index];
    const made = side === "over" ? game.value > line : game.value < line;
    if (!made) break;
    games.push(game);
  }
  return { count: games.length, games };
}

function streakClass(count) {
  if (count >= 5) return "hot";
  if (count >= 3) return "warm";
  if (count >= 1) return "cold";
  return "neutral";
}

function snapSentence(marketId) {
  if (marketId === "rec_yds" || marketId === "receptions") {
    return "An offensive snap with no target and no yard counts as 0.";
  }
  if (marketId === "rush_yds" || marketId === "rush_att") {
    return "An offensive snap with no carry counts as 0 for running backs, quarterbacks, and receivers.";
  }
  if (marketId === "first_td") {
    return "Yes means this player scored the first touchdown of that game. An offensive snap with no score counts as No.";
  }
  return "";
}

function formatPlayed(value, marketId) {
  if (marketId === "first_td") return Number(value) >= 1 ? "Yes" : "No";
  return formatStat(value);
}

function hitSentence(result, line, market) {
  if (market.id === "first_td") {
    return `${result.hits} of last ${result.dots.length} scored the first touchdown`;
  }
  return `${result.hits} of last ${result.dots.length} cleared ${formatLine(line, market.unit)}`;
}

function emptyStreak(market) {
  if (market.id === "first_td") {
    return state.streakSide === "over"
      ? "No streak of scoring the first touchdown."
      : "No streak without scoring the first touchdown.";
  }
  return `No ${sideLabel(market).toLowerCase()} streak at this line.`;
}

function sideLabel(market) {
  if (market.id === "first_td") return state.streakSide === "over" ? "Yes" : "No";
  return state.streakSide === "over" ? "Over" : "Under";
}

function streakMark(count) {
  return count >= 5 ? `🔥 ${count}x` : `${count}x`;
}

function streakText(streak, line, market) {
  const word = sideLabel(market);
  const games = streak.games.map((game) => `Week ${game.week}: ${formatPlayed(game.value, market.id)} ✓`);
  const lines = [
    `${word} streak ${streak.count}x`,
    `Current line: ${formatLine(line, market.unit)}`,
    ...games,
    "All games are evaluated against the current line.",
  ];
  const snapLine = snapSentence(market.id);
  if (snapLine) lines.push(snapLine);
  return lines.join("\n");
}

function spot(player) {
  return player.home ? `vs ${player.opponent}` : `@ ${player.opponent}`;
}

function gameId(player) {
  const home = player.home ? player.team : player.opponent;
  const away = player.home ? player.opponent : player.team;
  return `${away}@${home}`;
}

function matchups() {
  const names = new Map();
  for (const player of state.board.players) {
    if (player.club) names.set(player.team, player.club);
  }
  const games = new Map();
  for (const player of state.board.players) {
    const id = gameId(player);
    if (games.has(id)) continue;
    const [away, home] = id.split("@");
    const awayName = names.get(away) || away;
    const homeName = names.get(home) || home;
    games.set(id, { id, label: `${awayName} @ ${homeName}` });
  }
  return [...games.values()].sort((a, b) => a.label.localeCompare(b.label));
}

function onBookLine(book, line) {
  const posted = book.sportsbook;
  return Boolean(posted) && Math.abs(posted.line - line) < 0.01;
}

function priceTag(book, line) {
  return onBookLine(book, line) ? ` · ${book.sportsbook.odds}` : "";
}

function rows() {
  const query = state.query.trim().toLowerCase();
  const market = marketById(state.marketId);
  return state.board.players
    .filter((player) => player.markets[state.marketId])
    .filter((player) => !state.matchup || gameId(player) === state.matchup)
    .filter((player) => {
      if (!query) return true;
      const hay = `${player.name} ${player.team} ${player.club || ""}`.toLowerCase();
      return hay.includes(query);
    })
    .map((player) => {
      const book = player.markets[state.marketId];
      const line = lineFor(player);
      return {
        player,
        book,
        line,
        grade: grade(book.logs.slice(-10), line),
        streak: streakFor(book.logs, line, state.streakSide),
        market,
      };
    })
    .filter((item) => item.streak.count >= state.streakMin)
    .sort((a, b) => {
      const dir = state.direction === "asc" ? 1 : -1;
      const primary = state.sort === "match"
        ? a.book.matchup.score - b.book.matchup.score
        : state.sort === "streak"
          ? a.streak.count - b.streak.count
          : a.grade.pct - b.grade.pct;
      const secondary = state.sort === "streak"
        ? a.grade.pct - b.grade.pct
        : a.book.matchup.score - b.book.matchup.score;
      return dir * primary || dir * secondary || a.player.name.localeCompare(b.player.name);
    });
}

function avatar(person, className) {
  const initials = person.name.split(" ").map((part) => part[0]).slice(0, 2).join("");
  if (!person.headshot) {
    return `<span class="avatar-fallback ${className || ""}">${esc(initials)}</span>`;
  }
  return `<img src="${esc(person.headshot)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'), {className: 'avatar-fallback', textContent: '${esc(initials)}'}))">`;
}

function renderBoard() {
  const scroll = listEl.scrollTop;
  const items = rows();
  const previousId = state.selectedId;
  if (!items.some((item) => item.player.id === state.selectedId)) {
    state.selectedId = items[0]?.player.id ?? null;
    if (state.selectedId !== previousId) state.sheetOpen = false;
  }

  if (!items.length) {
    const bits = [];
    if (state.matchup) {
      const game = matchups().find((item) => item.id === state.matchup);
      if (game) bits.push(esc(game.label));
    }
    if (state.query.trim()) bits.push(`“${esc(state.query.trim())}”`);
    if (state.streakMin) bits.push(`a ${state.streakMin}+ ${state.streakSide} streak`);
    const why = bits.length ? ` matching ${bits.join(" and ")}` : "";
    listEl.innerHTML = `<div class="empty">No players in this market${why}.</div>`;
    renderDetail(null);
    return;
  }

  listEl.innerHTML = items.map(({ player, line, grade: result, streak, market, book }) => {
    const hitTone = tone(result.pct);
    const matchTone = tone(book.matchup.score);
    const dots = result.dots.map((dot) => `<i class="dot ${dot}"></i>`).join("");
    const streakTitle = esc(streakText(streak, line, market)).replaceAll("\n", "&#10;");
    return `
      <button type="button" class="row ${player.injury ? "out" : ""} ${player.id === state.selectedId ? "selected" : ""}" data-id="${esc(player.id)}">
        <span class="who">
          ${avatar(player)}
          <span>
            <span class="name">${esc(player.name)}${player.injury ? `<span class="out-tag">OUT</span>` : ""}</span>
            <span class="meta">${esc(formatLine(line, market.unit))}${esc(priceTag(book, line))} · ${esc(spot(player))}</span>
          </span>
        </span>
        <span class="dots" aria-label="Last ${result.dots.length} games">${dots}</span>
        <span class="pct ${hitTone}">${result.pct}%</span>
        <span class="streak ${streakClass(streak.count)}" title="${streakTitle}">${streakMark(streak.count)}</span>
        <span class="match">
          <span class="bar" aria-hidden="true"><span class="fill ${matchTone}" style="width:${book.matchup.score}%"></span></span>
          <span class="score ${matchTone}">${book.matchup.score}</span>
        </span>
      </button>`;
  }).join("");
  listEl.scrollTop = scroll;

  renderDetail(items.find((item) => item.player.id === state.selectedId));
}

function mobileLayout() {
  return window.matchMedia("(max-width: 980px)").matches;
}

function closeSheet() {
  state.sheetOpen = false;
  syncSheet();
}

function syncSheet() {
  const open = mobileLayout() && state.sheetOpen && Boolean(state.selectedId);
  document.body.classList.toggle("player-open", open);
  const backdrop = document.querySelector("#sheet-backdrop");
  if (backdrop) backdrop.hidden = !open;
  detailEl.classList.toggle("is-open", open);
  if (open) {
    detailEl.setAttribute("role", "dialog");
    detailEl.setAttribute("aria-modal", "true");
    detailEl.setAttribute("aria-label", "Player card");
  } else {
    detailEl.removeAttribute("role");
    detailEl.removeAttribute("aria-modal");
    detailEl.removeAttribute("aria-label");
  }
}

function renderDetail(item) {
  if (!item) {
    detailEl.innerHTML = `<p class="blurb">Pick a player to see the game log and this week’s matchup.</p>`;
    syncSheet();
    return;
  }
  const { player, book, line, grade: result, streak, market } = item;
  const season = grade(book.logs, line);
  const range = lineRange(book, line);
  const sideWord = sideLabel(market);
  const streakGames = streak.games.map((game) => {
    const where = game.home ? "vs" : "@";
    return `<li>Week ${game.week}: ${formatPlayed(game.value, market.id)} ${where} ${esc(game.opp)} ✓</li>`;
  }).join("");
  const matchTone = tone(book.matchup.score);
  const snapNote = snapSentence(market.id) ? ` ${snapSentence(market.id)}` : "";
  const logRows = logMarkup(book.logs, result.dots, market.id);

  detailEl.innerHTML = `
    <div class="detail-bar">
      <p class="detail-kicker">Week ${state.board.week} · ${esc(market.label)}</p>
      <button type="button" class="detail-close" aria-label="Close player card">×</button>
    </div>
    <div class="detail-scroll">
    <div class="detail-hero">
      ${avatar(player)}
      <div>
        <h2>${esc(player.name)}${player.injury ? `<span class="out-tag">OUT</span>` : ""}</h2>
        <p>${esc(player.pos)} · ${esc(player.team)} ${esc(spot(player))}</p>
        ${player.injury ? `<p class="out-note">Ruled out${player.injury.detail ? ` · ${esc(player.injury.detail)}` : ""} for week ${state.board.week}.</p>` : ""}
      </div>
    </div>
    <div class="line-row">
      <div class="line-scroll">
        <div class="line-readout">
          <b id="line-value">${esc(formatLine(line, market.unit))}</b>
          <span class="meta" id="line-meta">${esc(lineMeta(book, line))}</span>
        </div>
        <input id="line-slider" class="line-slider" type="range" min="${range.min}" max="${range.max}" step="0.5" value="${line}" aria-label="Scroll the prop line">
      </div>
    </div>
    <div class="stat-pair">
      <div class="stat">
        <span>Hit rate</span>
        <strong id="hit-rate" class="${tone(result.pct)}">${result.pct}%</strong>
        <em id="hit-note">${esc(hitSentence(result, line, market))}</em>
      </div>
      <div class="stat">
        <span>Matchup</span>
        <strong class="${matchTone}">${book.matchup.score}</strong>
        <em>${book.matchup.rank ? `${book.matchup.rank} of ${book.matchup.teams} defenses` : "No defensive split"}</em>
      </div>
    </div>
    <p class="blurb" id="line-blurb">${esc(book.matchup.blurb)} Season hit rate at this line is ${season.pct}% across ${book.games} games.</p>
    <section class="streak-card">
      <div class="streak-head">
        <span>${sideWord} streak</span>
        <strong id="streak-mark" class="streak ${streakClass(streak.count)}">${streakMark(streak.count)}</strong>
      </div>
      <p id="streak-line">Current line: ${esc(formatLine(line, market.unit))}</p>
      <div id="streak-body">
        ${streak.games.length
          ? `<ol class="streak-games">${streakGames}</ol>`
          : `<p class="streak-empty">${emptyStreak(market)}</p>`}
      </div>
      <p class="streak-note">All games are evaluated against the current line. An exact result ends the streak. Games the player did not play are skipped.${snapNote} Hit rate is a separate count.</p>
    </section>
    <table class="log">
      <thead><tr><th>Week</th><th>Opp</th><th>Stat</th><th>Result</th></tr></thead>
      <tbody id="log-body">${logRows}</tbody>
    </table>
    </div>`;

  detailEl.querySelector(".detail-close").addEventListener("click", closeSheet);
  bindLineSlider(player);
  syncSheet();
}

function logMarkup(logs, dots, marketId) {
  return logs.slice(-10).reverse().map((game, index) => {
    const dot = dots[dots.length - 1 - index];
    const label = marketId === "first_td"
      ? (dot === "hit" ? "Yes" : dot === "miss" ? "No" : "Push")
      : (dot === "hit" ? "Over" : dot === "miss" ? "Under" : "Push");
    const where = game.home ? "vs" : "@";
    const shown = formatPlayed(game.value, marketId);
    return `<tr>
      <td>Wk ${game.week}</td>
      <td>${where} ${esc(game.opp)}</td>
      <td>${shown}</td>
      <td><span class="tag ${dot}">${label}</span></td>
    </tr>`;
  }).join("");
}

function paintLine(player) {
  const item = rows().find((row) => row.player.id === player.id);
  if (!item) return;
  const { book, line, grade: result, streak, market } = item;
  const season = grade(book.logs, line);
  const sideWord = sideLabel(market);
  document.querySelector("#line-value").textContent = formatLine(line, market.unit);
  document.querySelector("#line-meta").textContent = lineMeta(book, line);
  const hit = document.querySelector("#hit-rate");
  hit.textContent = `${result.pct}%`;
  hit.className = tone(result.pct);
  document.querySelector("#hit-note").textContent = hitSentence(result, line, market);
  document.querySelector("#line-blurb").textContent = `${book.matchup.blurb} Season hit rate at this line is ${season.pct}% across ${book.games} games.`;
  const mark = document.querySelector("#streak-mark");
  mark.textContent = streakMark(streak.count);
  mark.className = `streak ${streakClass(streak.count)}`;
  document.querySelector("#streak-line").textContent = `Current line: ${formatLine(line, market.unit)}`;
  const games = streak.games.map((game) => {
    const where = game.home ? "vs" : "@";
    return `<li>Week ${game.week}: ${formatPlayed(game.value, market.id)} ${where} ${esc(game.opp)} ✓</li>`;
  }).join("");
  document.querySelector("#streak-body").innerHTML = streak.games.length
    ? `<ol class="streak-games">${games}</ol>`
    : `<p class="streak-empty">${emptyStreak(market)}</p>`;
  document.querySelector("#log-body").innerHTML = logMarkup(book.logs, result.dots, market.id);

  const row = listEl.querySelector(`[data-id="${CSS.escape(player.id)}"]`);
  if (!row) return;
  row.querySelector(".who .meta").textContent = `${formatLine(line, market.unit)}${priceTag(book, line)} · ${spot(player)}`;
  const pct = row.querySelector(".pct");
  pct.textContent = `${result.pct}%`;
  pct.className = `pct ${tone(result.pct)}`;
  const streakEl = row.querySelector(":scope > .streak");
  streakEl.textContent = streakMark(streak.count);
  streakEl.className = `streak ${streakClass(streak.count)}`;
  streakEl.title = streakText(streak, line, market);
  row.querySelector(".dots").innerHTML = result.dots.map((dot) => `<i class="dot ${dot}"></i>`).join("");
}

function bindLineSlider(player) {
  const slider = document.querySelector("#line-slider");
  const scroller = document.querySelector(".line-scroll");
  const move = (next, rebuild) => {
    setLine(player, next);
    const value = lineFor(player);
    if (value > Number(slider.max)) slider.max = String(value);
    slider.value = String(value);
    paintLine(player);
    if (rebuild) renderBoard();
  };
  slider.addEventListener("input", () => move(Number(slider.value), false));
  slider.addEventListener("change", () => renderBoard());
  scroller.addEventListener("wheel", (event) => {
    event.preventDefault();
    const direction = event.deltaY < 0 ? 1 : -1;
    const notches = Math.max(1, Math.round(Math.abs(event.deltaY) / 24));
    move(lineFor(player) + direction * notches * 0.5, true);
  }, { passive: false });
}

function renderChrome() {
  const board = state.board;
  document.querySelector("#week").textContent = board.week;
  const start = board.slateStart.slice(5).replace("-", "/");
  const end = board.slateEnd.slice(5).replace("-", "/");
  const posted = board.lines && board.lines.label;
  document.querySelector(".panel-label").textContent = posted
    ? `Analyze props · ${board.lines.label}`
    : "Analyze props";
  document.querySelector("#lede").textContent = posted
    ? `Week ${board.week} slate, ${start}–${end}. Every line is ${board.lines.label}, refreshed ${board.lines.fetchedOn}. Hit rate is the last 10 games over that number. Streak is the current run over or under the same line. Matchup 100 is the softest defense.`
    : `Week ${board.week} slate, ${start}–${end}. Hit rate is the last 10 games over the line. Streak is the current run over or under that line. Matchup 100 is the softest defense.`;
  document.querySelector("#note").textContent = posted
    ? `${board.lines.matched} props use the ${board.lines.label} number. A card with no price is still on the season average because that book has no line. Move a line and the price drops off. Hit rate and streak both update, and they stay separate. Stats through week ${board.throughWeek}. This is a research view, not a sportsbook.`
    : `Lines start at the season average, snapped to a half point, until a SportsGameOdds key is added. Move the line and the hit rate and streak update separately. Stats through week ${board.throughWeek}. Source: ${board.source}. This is a research view, not a sportsbook.`;

  const matchup = document.querySelector("#matchup");
  const selected = state.matchup;
  matchup.innerHTML = `<option value="">All matchups</option>${matchups().map((game) => `
    <option value="${esc(game.id)}"${game.id === selected ? " selected" : ""}>${esc(game.label)}</option>`).join("")}`;

  marketsEl.innerHTML = board.markets.map((market) => `
    <button type="button" role="tab" aria-selected="${market.id === state.marketId}" data-market="${market.id}">
      ${esc(market.label)}
    </button>`).join("");
}

function bind() {
  marketsEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-market]");
    if (!button) return;
    state.marketId = button.dataset.market;
    marketsEl.querySelectorAll("button").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab === button));
    });
    renderBoard();
  });

  document.querySelector("#search").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderBoard();
  });

  document.querySelector("#matchup").addEventListener("change", (event) => {
    state.matchup = event.target.value;
    renderBoard();
  });

  document.querySelector("#sort-hit").addEventListener("click", () => setSort("hit"));
  document.querySelector("#sort-streak").addEventListener("click", () => setSort("streak"));
  document.querySelector("#sort-match").addEventListener("click", () => setSort("match"));
  document.querySelector("#sort-dir").addEventListener("click", () => setDirection());

  document.querySelector("#streak-side").addEventListener("click", (event) => {
    const button = event.target.closest("[data-side]");
    if (!button) return;
    state.streakSide = button.dataset.side;
    document.querySelectorAll("#streak-side button").forEach((tab) => {
      tab.setAttribute("aria-pressed", String(tab === button));
    });
    renderBoard();
  });

  document.querySelector("#streak-min").addEventListener("click", (event) => {
    const button = event.target.closest("[data-min]");
    if (!button) return;
    state.streakMin = Number(button.dataset.min);
    document.querySelectorAll("#streak-min button").forEach((tab) => {
      tab.setAttribute("aria-pressed", String(tab === button));
    });
    renderBoard();
  });

  listEl.addEventListener("click", (event) => {
    const row = event.target.closest("[data-id]");
    if (!row) return;
    state.selectedId = row.dataset.id;
    state.sheetOpen = true;
    renderBoard();
    detailEl.querySelector(".detail-scroll")?.scrollTo(0, 0);
    detailEl.querySelector(".detail-close")?.focus();
  });

  document.querySelector("#sheet-backdrop").addEventListener("click", closeSheet);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSheet();
  });
  window.matchMedia("(max-width: 980px)").addEventListener("change", () => {
    if (!mobileLayout()) state.sheetOpen = false;
    syncSheet();
  });
}

function setSort(sort) {
  state.sort = sort;
  document.querySelector("#sort-hit").setAttribute("aria-pressed", String(sort === "hit"));
  document.querySelector("#sort-streak").setAttribute("aria-pressed", String(sort === "streak"));
  document.querySelector("#sort-match").setAttribute("aria-pressed", String(sort === "match"));
  renderBoard();
}

function setDirection() {
  state.direction = state.direction === "desc" ? "asc" : "desc";
  const button = document.querySelector("#sort-dir");
  const descending = state.direction === "desc";
  button.textContent = descending ? "Desc" : "Asc";
  button.setAttribute("aria-pressed", String(!descending));
  button.setAttribute("aria-label", descending ? "Sort descending" : "Sort ascending");
  renderBoard();
}

async function main() {
  const response = await fetch("data/board.json", { cache: "no-store" });
  state.board = await response.json();
  renderChrome();
  bind();
  renderBoard();
}

main().catch((error) => {
  document.querySelector("#lede").textContent = `Could not load the board. ${error.message}`;
});
