const moneyList = document.querySelector("#money-list");
const moneyLede = document.querySelector("#money-lede");
const moneyNote = document.querySelector("#money-note");
const moneyWeek = document.querySelector("#money-week");
const railTabs = document.querySelectorAll(".rail-tab");

const view = { slate: null, open: null };

function signed(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return `${number > 0 ? "+" : ""}${number}`;
}

function price(value) {
  return value ? String(value) : "—";
}

function ordinal(rank) {
  if (!rank) return "—";
  const teen = rank % 100;
  const suffix = teen >= 11 && teen <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[rank % 10] || "th";
  return `${rank}${suffix}`;
}

function showView(name) {
  document.querySelector("#view-props").hidden = name !== "props";
  document.querySelector("#view-money").hidden = name !== "money";
  railTabs.forEach((tab) => tab.setAttribute("aria-pressed", String(tab.dataset.view === name)));
  if (name === "money" && !view.slate) loadSlate();
  history.replaceState(null, "", name === "money" ? "#money" : "#props");
}

railTabs.forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});

function meter(game, awayPct, homePct, caption) {
  const away = Math.max(0, Math.min(100, awayPct));
  return `
    <div class="meter-block">
      ${caption ? `<div class="meter-caption">${caption}</div>` : ""}
      <div class="meter" style="--away:${away}%;--away-color:${game.away.color};--home-color:${game.home.color}">
        <span>${game.away.abbr} ${away}%</span>
        <span>${100 - away}% ${game.home.abbr}</span>
        <span class="meter-track" aria-hidden="true"><i></i></span>
      </div>
    </div>`;
}

const WEEKDAYS = {
  Sun: "Sunday", Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday",
  Thu: "Thursday", Fri: "Friday", Sat: "Saturday",
};

function kickParts(game) {
  const [abbr, time, period] = game.kickoff.split(" ");
  return {
    day: `${WEEKDAYS[abbr] || abbr}, ${game.date}`,
    time: time && period ? `${time} ${period}` : game.kickoff,
  };
}

function oddsCell(line, juice) {
  const priceLine = juice && juice !== "—" ? `<small>${juice}</small>` : "";
  return `<span class="odds-cell"><b>${line}</b>${priceLine}</span>`;
}

function teamMark(team) {
  return `<span class="odds-team"><img src="${team.logo}" alt="">${team.abbr}</span>`;
}

function channelsOf(hex) {
  const raw = String(hex || "").replace("#", "");
  if (raw.length < 6) return [126, 182, 255];
  return [0, 2, 4].map((index) => parseInt(raw.slice(index, index + 2), 16));
}

function rgbToHsl(r, g, b) {
  const red = r / 255;
  const green = g / 255;
  const blue = b / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const light = (max + min) / 2;
  if (max === min) return [0, 0, light];
  const delta = max - min;
  const sat = light > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  let hue;
  if (max === red) hue = (green - blue) / delta + (green < blue ? 6 : 0);
  else if (max === green) hue = (blue - red) / delta + 2;
  else hue = (red - green) / delta + 4;
  return [hue * 60, sat, light];
}

function hslToHex(hue, sat, light) {
  const wrapped = ((hue % 360) + 360) % 360;
  const clampedSat = Math.max(0, Math.min(1, sat));
  const clampedLight = Math.max(0, Math.min(1, light));
  const chroma = (1 - Math.abs(2 * clampedLight - 1)) * clampedSat;
  const match = chroma * (1 - Math.abs((wrapped / 60) % 2 - 1));
  const base = clampedLight - chroma / 2;
  let red = 0;
  let green = 0;
  let blue = 0;
  if (wrapped < 60) [red, green, blue] = [chroma, match, 0];
  else if (wrapped < 120) [red, green, blue] = [match, chroma, 0];
  else if (wrapped < 180) [red, green, blue] = [0, chroma, match];
  else if (wrapped < 240) [red, green, blue] = [0, match, chroma];
  else if (wrapped < 300) [red, green, blue] = [match, 0, chroma];
  else [red, green, blue] = [chroma, 0, match];
  return `#${[red, green, blue].map((channel) => Math.round((channel + base) * 255).toString(16).padStart(2, "0")).join("")}`;
}

function hueGap(left, right) {
  const delta = Math.abs(left - right) % 360;
  return Math.min(delta, 360 - delta);
}

function barColors(awayHex, homeHex) {
  let [awayHue, awaySat, awayLight] = rgbToHsl(...channelsOf(awayHex));
  let [homeHue, homeSat, homeLight] = rgbToHsl(...channelsOf(homeHex));
  const lift = (light) => (light < 0.4 ? 0.48 : light > 0.76 ? 0.64 : light);
  const punch = (sat) => (sat < 0.12 ? sat : Math.min(1, sat + 0.12));
  awayLight = lift(awayLight);
  homeLight = lift(homeLight);
  awaySat = punch(awaySat);
  homeSat = punch(homeSat);
  const gap = hueGap(awayHue, homeHue);
  if (awaySat > 0.18 && homeSat > 0.18 && gap < 42) {
    const push = (42 - gap) / 2 + 8;
    const direction = ((homeHue - awayHue + 540) % 360) - 180;
    if (Math.abs(direction) < 1) {
      awayHue -= 26;
      homeHue += 26;
    } else {
      const sign = direction > 0 ? 1 : -1;
      awayHue -= sign * push;
      homeHue += sign * push;
    }
    awaySat = Math.max(awaySat, 0.78);
    homeSat = Math.max(homeSat, 0.78);
  }
  if (awaySat < 0.15 && homeSat < 0.15) {
    return [hslToHex(196, 0.72, 0.52), hslToHex(28, 0.78, 0.54)];
  }
  if (awaySat < 0.15) {
    awayHue = homeHue + 150;
    awaySat = 0.42;
    awayLight = 0.62;
  }
  if (homeSat < 0.15) {
    homeHue = awayHue + 150;
    homeSat = 0.42;
    homeLight = 0.62;
  }
  return [hslToHex(awayHue, awaySat, awayLight), hslToHex(homeHue, homeSat, homeLight)];
}

function splitBar(leftPct, leftNote, name, rightNote, rightPct, awayColor, homeColor) {
  if (leftPct == null || rightPct == null) return "";
  const fill = Math.max(0, Math.min(100, leftPct));
  return `
    <div class="split-row">
      <div class="split-meta">
        <span class="split-side"><b>${leftPct}%</b>${leftNote ? `<em>${leftNote}</em>` : ""}</span>
        <span class="split-name">${name}</span>
        <span class="split-side split-side-right">${rightNote ? `<em>${rightNote}</em>` : ""}<b>${rightPct}%</b></span>
      </div>
      <div class="split-bar" style="--fill:${fill}%;--away-color:${awayColor};--home-color:${homeColor}"><i></i></div>
    </div>`;
}

function splitGroup(game, label, moneyline, spread, totalLine, total) {
  if (!moneyline || moneyline.away == null || moneyline.home == null) return "";
  const [awayColor, homeColor] = barColors(game.away.color, game.home.color);
  const awaySpread = spreadParts(game.awayMarket.spread).line;
  const homeSpread = spreadParts(game.homeMarket.spread).line;
  return `
    <div class="split-group">
      <div class="split-head">
        <img src="${game.away.logo}" alt="">
        <b>${game.away.abbr} ${moneyline.away}%</b>
        <span>${label}</span>
        <b>${moneyline.home}% ${game.home.abbr}</b>
        <img src="${game.home.logo}" alt="">
      </div>
      ${splitBar(moneyline.away, "", "Moneyline", "", moneyline.home, awayColor, homeColor)}
      ${splitBar(spread.away, `${game.away.abbr} ${awaySpread}`, "Spread", `${game.home.abbr} ${homeSpread}`, spread.home, awayColor, homeColor)}
      ${splitBar(total.over, `Over ${totalLine}`, "Total", `Under ${totalLine}`, total.under, awayColor, homeColor)}
    </div>`;
}

function publicBlock(game) {
  if (!game.money) return "";
  const spread = game.spreadSplit || {};
  const total = game.totalSplit || {};
  const line = game.total?.line ?? "—";
  const tickets = game.tickets && game.tickets.away != null
    ? splitGroup(game, "Tickets", { away: game.tickets.away, home: game.tickets.home }, {
      away: spread.awayTickets, home: spread.homeTickets,
    }, line, { over: total.overTickets, under: total.underTickets })
    : "";
  return `
    <div class="public">
      ${splitGroup(game, "Money %", game.money, spread, line, total)}
      ${tickets}
    </div>`;
}

function signals(game) {
  const chips = game.signals || [];
  if (!chips.length) return "";
  return `<div class="signals">${chips.map((chip) => `<span class="signal" title="${chip.detail || ""}">${chip.label}</span>`).join("")}</div>`;
}

function spreadParts(market) {
  if (market.draftkings == null) return { line: "—", juice: "" };
  return { line: signed(market.draftkings), juice: price(market.draftkingsOdds) };
}

function detail(game) {
  const away = game.away;
  const home = game.home;
  const recent = (team) => team.recent.map((gameRow) =>
    `<li><span>Wk ${gameRow.week}</span> ${gameRow.home ? "vs" : "@"} ${gameRow.opp} <strong class="result-${String(gameRow.result).toLowerCase()}">${gameRow.result}</strong> ${gameRow.pf}–${gameRow.pa}</li>`
  ).join("") || "<li>No completed games.</li>";
  const injuries = (team) => team.injuries.length
    ? team.injuries.map((player) => `<li>${player.name}${player.detail ? ` · ${player.detail}` : ""}</li>`).join("")
    : "<li>No players listed out.</li>";
  const weather = game.indoors
    ? "Indoors"
    : game.weather
      ? game.weather.summary
      : "No forecast for this kickoff.";
  const split = (team, record) => `
    <div>
      <p>${team.abbr}</p>
      <ul>
        <li>${record}</li>
        <li>${team.ats} ATS</li>
        <li>${team.overs}–${team.unders} totals</li>
      </ul>
    </div>`;

  return `
    <div class="slate-detail">
      <section>
        <h3>Recent</h3>
        <div class="recent-pair">
          <div><p>${away.abbr}</p><ul>${recent(away)}</ul></div>
          <div><p>${home.abbr}</p><ul>${recent(home)}</ul></div>
        </div>
      </section>
      <section>
        <h3>Injuries</h3>
        <div class="recent-pair">
          <div><p>${away.abbr}</p><ul>${injuries(away)}</ul></div>
          <div><p>${home.abbr}</p><ul>${injuries(home)}</ul></div>
        </div>
      </section>
      <section>
        <h3>Home / away</h3>
        <div class="recent-pair">
          ${split(away, `${away.awayRecord} away`)}
          ${split(home, `${home.homeRecord} home`)}
        </div>
      </section>
      <section>
        <h3>Weather</h3>
        <p class="fine">${weather}</p>
        <p class="fine">${game.stadium}${game.roof ? ` · ${game.roof}` : ""}</p>
      </section>
    </div>`;
}

function card(game) {
  const open = view.open === game.id;
  const away = game.away;
  const home = game.home;
  const when = kickParts(game);
  const weather = game.indoors ? "Indoors" : game.weather ? game.weather.summary : "";
  const awaySpread = spreadParts(game.awayMarket.spread);
  const homeSpread = spreadParts(game.homeMarket.spread);
  const total = game.total.line ?? "—";
  const hasLine = game.awayMarket.moneyline.draftkings || awaySpread.line !== "—";
  const implied = game.implied?.away == null
    ? `<p class="no-line">${hasLine ? "Moneyline missing." : "No current price. This game is off the odds feed."}</p>`
    : meter(game, game.implied.away, game.implied.home, "Market implied");
  return `
    <article class="slate ${open ? "is-open" : ""}" data-id="${game.id}" style="--away-color:${away.color};--home-color:${home.color}">
      <button type="button" class="slate-hit" aria-expanded="${open}">
        <div class="hero">
          <p class="hero-league">NFL</p>
          <div class="hero-match">
            <div class="club">
              <img src="${away.logo}" alt="">
              <strong>${away.name}</strong>
              <span>${away.record}</span>
            </div>
            <div class="kick">
              <strong>${when.time}</strong>
              <span>${game.stadium}</span>
              ${weather ? `<span>${weather}</span>` : ""}
            </div>
            <div class="club club-home">
              <img src="${home.logo}" alt="">
              <strong>${home.name}</strong>
              <span>${home.record}</span>
            </div>
          </div>
        </div>
        <div class="odds-panel">
          <h3>Betting Odds</h3>
          <div class="odds-head"><span>Team</span><span>Spread</span><span>Total</span><span>Moneyline</span></div>
          <div class="odds-row">
            ${teamMark(away)}
            ${oddsCell(awaySpread.line, awaySpread.juice)}
            ${oddsCell(`O ${total}`, price(game.total.over.draftkings))}
            ${oddsCell(price(game.awayMarket.moneyline.draftkings))}
          </div>
          <div class="odds-row">
            ${teamMark(home)}
            ${oddsCell(homeSpread.line, homeSpread.juice)}
            ${oddsCell(`U ${total}`, price(game.total.under.draftkings))}
            ${oddsCell(price(game.homeMarket.moneyline.draftkings))}
          </div>
          <p class="odds-source">Odds provided by DraftKings</p>
          ${publicBlock(game)}
          ${signals(game)}
          ${implied}
          <div class="rank-table">
            <h3>Ranks</h3>
            <div class="odds-head"><span>Team</span><span>Offense</span><span>Defense</span></div>
            <div class="odds-row rank-row">
              ${teamMark(away)}
              <span class="odds-cell"><b>${ordinal(away.ranks.offense)}</b></span>
              <span class="odds-cell"><b>${ordinal(away.ranks.defense)}</b></span>
            </div>
            <div class="odds-row rank-row">
              ${teamMark(home)}
              <span class="odds-cell"><b>${ordinal(home.ranks.offense)}</b></span>
              <span class="odds-cell"><b>${ordinal(home.ranks.defense)}</b></span>
            </div>
          </div>
        </div>
      </button>
      ${open ? detail(game) : ""}
    </article>`;
}

function render() {
  const games = view.slate?.games || [];
  const groups = [];
  games.forEach((game) => {
    const label = kickParts(game).day;
    const last = groups[groups.length - 1];
    if (!last || last.label !== label) groups.push({ label, games: [game] });
    else last.games.push(game);
  });
  moneyList.innerHTML = groups.map((group) => `
    <section class="day-group">
      <h2>${group.label}</h2>
      ${group.games.map(card).join("")}
    </section>`).join("");
  moneyList.querySelectorAll(".slate-hit").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.parentElement.dataset.id;
      view.open = view.open === id ? null : id;
      render();
      if (view.open) {
        moneyList.querySelector(`[data-id="${view.open}"]`)?.scrollIntoView({ block: "nearest" });
      }
    });
  });
}

async function loadSlate() {
  const response = await fetch("data/slate.json", { cache: "no-store" });
  view.slate = await response.json();
  moneyWeek.textContent = view.slate.week;
  moneyLede.textContent = `${view.slate.games.length} games. Lines are ${view.slate.book}. Offense and defense ranks use weeks 1–${view.slate.throughWeek}.`;
  moneyNote.textContent = view.slate.handleAvailable
    ? "Money % is the share of dollars and Tickets is the share of bets, both a consensus across sportsbooks. They are not DraftKings’ own bet count. A lopsided split is not labeled smart money."
    : "Research view. The bar is the no-vig moneyline. Public splits appear after the daily Playbook pull.";
  render();
}

if (location.hash === "#money") showView("money");
