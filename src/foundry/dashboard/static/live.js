// Pages that report keep their numbers current: every 15 seconds the page is fetched again, and its main part and the side counts are swapped in when they changed.
// Never while someone is typing or has opened or closed something on the page, so nothing they are doing is lost. Pages with forms to fill are left alone.
(() => {
  const LIVE = /^\/(jobs(\/[^/]+)?|responses|work|log)?$/;
  const EVERY = 15000;
  const PARTS = ["#main", ".side-nav", ".tabbar"];
  if (!LIVE.test(location.pathname)) return;
  let touched = false;
  document.addEventListener("toggle", () => { touched = true; }, true);
  document.addEventListener("input", () => { touched = true; }, true);

  const typing = () => {
    const field = document.activeElement;
    return field && /^(INPUT|TEXTAREA|SELECT)$/.test(field.tagName);
  };

  setInterval(async () => {
    if (document.hidden || touched || typing()) return;
    try {
      const answer = await fetch(location.href, { credentials: "same-origin", cache: "no-store" });
      if (!answer.ok || answer.redirected) return;
      const fresh = new DOMParser().parseFromString(await answer.text(), "text/html");
      for (const part of PARTS) {
        const now = document.querySelector(part);
        const next = fresh.querySelector(part);
        if (now && next && now.innerHTML !== next.innerHTML) now.innerHTML = next.innerHTML;
      }
    } catch {
      // A missed refresh is tried again on the next one.
    }
  }, EVERY);
})();
