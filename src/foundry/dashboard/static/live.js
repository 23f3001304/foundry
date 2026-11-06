// Pages that report keep their numbers current: every 15 seconds the page is fetched again, and its main part and the side counts are swapped in when they changed.
// Never while someone is typing or has opened or closed something on the page, so nothing they are doing is lost. Pages with forms to fill are left alone.
// The swap cross-fades where the browser can, and a number that changed pulses once so the eye finds it.
(() => {
  // Arrival motion plays once. After the first paint, refreshes swap parts in without replaying it.
  const settle = () => document.documentElement.classList.add("settled");
  window.addEventListener("load", () => setTimeout(settle, 900));
  window.addEventListener("pageshow", (event) => { if (event.persisted) settle(); });

  const LIVE = /^\/(jobs(\/[^/]+)?|responses|work|log)?$/;
  const EVERY = 15000;
  const PARTS = ["#main", ".side-nav", ".tabbar"];
  const NUMBERS = ".figure > dd:first-of-type, .cell-figure, .stage-count, .nav-item .count, .panel-strip b, .tally, .tabbar .count";
  if (!LIVE.test(location.pathname)) return;
  let touched = false;
  document.addEventListener("toggle", () => { touched = true; }, true);
  document.addEventListener("input", () => { touched = true; }, true);

  const typing = () => {
    const field = document.activeElement;
    return field && /^(INPUT|TEXTAREA|SELECT)$/.test(field.tagName);
  };

  const numbersIn = (root) => Array.from(root.querySelectorAll(NUMBERS), (el) => el.textContent.trim());

  const swap = (changes) => {
    for (const [now, next] of changes) {
      const before = numbersIn(now);
      now.innerHTML = next.innerHTML;
      now.querySelectorAll(NUMBERS).forEach((el, i) => {
        if (before[i] !== undefined && before[i] !== el.textContent.trim()) el.classList.add("bumped");
      });
    }
  };

  setInterval(async () => {
    if (document.hidden || touched || typing()) return;
    try {
      const answer = await fetch(location.href, { credentials: "same-origin", cache: "no-store" });
      if (!answer.ok || answer.redirected) return;
      const fresh = new DOMParser().parseFromString(await answer.text(), "text/html");
      const changes = [];
      for (const part of PARTS) {
        const now = document.querySelector(part);
        const next = fresh.querySelector(part);
        if (now && next && now.innerHTML !== next.innerHTML) changes.push([now, next]);
      }
      if (!changes.length) return;
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (document.startViewTransition && !still) {
        document.documentElement.classList.add("live-swap");
        document.startViewTransition(() => swap(changes)).finished.finally(() => document.documentElement.classList.remove("live-swap"));
      }
      else swap(changes);
    } catch {
      // A missed refresh is tried again on the next one.
    }
  }, EVERY);
})();
