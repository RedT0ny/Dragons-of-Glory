(function () {
  "use strict";

  var tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab-btn"));
  var sections = {};
  tabButtons.forEach(function (btn) { sections[btn.dataset.tab] = btn; });
  var searchInput = document.getElementById("wiki-search");
  var countEl = document.getElementById("search-count");
  var langBtn = document.getElementById("lang-btn");
  var currentLang = "en";
  try { var saved = localStorage.getItem("dog-wiki-lang"); if (saved) currentLang = saved; } catch (e) {}

  function setLang(lang) {
    currentLang = lang;
    try { localStorage.setItem("dog-wiki-lang", lang); } catch (e) {}
    document.documentElement.lang = lang;
    document.querySelectorAll(".l10n").forEach(function (el) {
      var value = (lang === "es" && el.dataset.es) ? el.dataset.es : (el.dataset.en || el.dataset.es || "");
      el.textContent = value;
    });
    langBtn.textContent = (currentLang === "en") ? "ES" : "EN";
    var title = document.querySelector("h1.l10n");
    if (title) document.title = title.textContent + " — Wiki";
    searchInput.placeholder = (currentLang === "en")
      ? "Search name, type, country, race..."
      : "Buscar nombre, tipo, nación, raza...";
    document.querySelectorAll(".empty .l10n").forEach(function (el) {
      el.textContent = (currentLang === "es" && el.dataset.es) ? el.dataset.es : (el.dataset.en || "");
    });
    applySearch();
  }

  function setTab(tabId) {
    tabButtons.forEach(function (btn) {
      var on = (btn.dataset.tab === tabId);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("section.tab").forEach(function (sec) {
      sec.classList.toggle("active", sec.id === tabId);
    });
    applySearch();
    manualScrollspy();
  }

  function activeSectionId() {
    var active = document.querySelector("section.tab.active");
    return active ? active.id : "tab-rules";
  }

  function applySearch() {
    var term = (searchInput.value || "").toLowerCase().trim();
    var sec = document.getElementById(activeSectionId());
    if (!sec) return;
    var total = 0, visible = 0;
    sec.querySelectorAll(".card").forEach(function (card) {
      total++;
      var ok = !term || (card.dataset.search || "").indexOf(term) !== -1;
      card.hidden = !ok;
      if (ok) visible++;
    });
    sec.querySelectorAll(".group").forEach(function (g) {
      var any = Array.prototype.some.call(g.querySelectorAll(".card"), function (c) { return !c.hidden; });
      g.hidden = !any;
    });
    sec.querySelectorAll(".alleg-sec").forEach(function (g) {
      var any = Array.prototype.some.call(g.querySelectorAll(".card"), function (c) { return !c.hidden; });
      g.hidden = !any;
    });
    var empty = sec.querySelector(".empty");
    if (empty) empty.hidden = !(term && visible === 0);
    countEl.textContent = (term && visible < total) ? visible + "/" + total : "";
  }

  function goto(kind, id) {
    var map = { unit: "tab-units", artifact: "tab-artifacts", event: "tab-events",
                country: "tab-countries", group: "tab-units", bonus: "tab-bonuses" };
    var tabId = map[kind] || "tab-units";
    setTab(tabId);
    var target = kind === "group" ? "group-" + id : kind + "-card-" + id;
    var el = document.getElementById(target);
    if (el) {
      setTimeout(function () {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        el.classList.add("flash");
        setTimeout(function () { el.classList.remove("flash"); }, 1800);
      }, 60);
    }
  }

  function manualScrollspy() {
    var links = Array.prototype.slice.call(document.querySelectorAll(".m-toc-link"));
    if (!links.length) return;
    var rulesActive = document.getElementById("tab-rules").classList.contains("active");
    var pos = window.scrollY + 150;
    var current = null;
    if (rulesActive) {
      links.forEach(function (l) {
        var sec = document.getElementById(l.dataset.sec);
        if (sec && sec.offsetTop <= pos) current = l.dataset.sec;
      });
    }
    links.forEach(function (l) { l.classList.toggle("active", l.dataset.sec === current); });
  }

  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () { setTab(btn.dataset.tab); });
  });
  window.addEventListener("scroll", manualScrollspy, { passive: true });
  searchInput.addEventListener("input", applySearch);
  searchInput.addEventListener("search", applySearch);
  langBtn.addEventListener("click", function () {
    setLang(currentLang === "en" ? "es" : "en");
  });
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest ? ev.target.closest("a.l-x") : null;
    if (!a) return;
    var parts = a.dataset.goto.split("/");
    if (!parts[1]) return;
    ev.preventDefault();
    goto(parts[0], parts[1]);
    try { history.replaceState(null, "", "#" + parts[0] + "/" + parts[1]); } catch (e) {}
  });

  function routeFromHash() {
    var m = (location.hash || "").match(/^#(unit|artifact|event|country|group|bonus)\/([\w_-]+)/);
    if (m) goto(m[1], m[2]);
  }
  window.addEventListener("hashchange", routeFromHash);
  setTab("tab-rules");
  setLang(currentLang);
  routeFromHash();
})();