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
                scenario: "tab-scenarios", country: "tab-countries", group: "tab-units",
                bonus: "tab-bonuses" };
    if (kind === "tab") {
      var tabSec = document.getElementById("tab-" + id);
      if (tabSec) {
        setTab("tab-" + id);
        setTimeout(function () { tabSec.scrollIntoView({ behavior: "smooth", block: "start" }); }, 60);
      }
      return;
    }
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

  var zoomables = Array.prototype.slice.call(document.querySelectorAll("[data-zoom]"));
  if (zoomables.length) {
    var lightbox = document.createElement("div");
    lightbox.className = "lightbox";
    lightbox.hidden = true;
    var lightboxStage = document.createElement("div");
    lightboxStage.className = "lightbox-stage";
    var lightboxImg = document.createElement("img");
    lightboxImg.alt = "";
    lightboxImg.draggable = false;
    lightboxStage.appendChild(lightboxImg);
    var lightboxHint = document.createElement("div");
    lightboxHint.className = "lightbox-hint l10n";
    lightbox.appendChild(lightboxStage);
    lightbox.appendChild(lightboxHint);
    document.body.appendChild(lightbox);

    var zoomLevel = 1;
    var HINTS = {
      fit: ["Click the map to magnify · click the background or press Esc to close",
            "Haz clic en el mapa para ampliar · haz clic en el fondo o pulsa Esc para cerrar"],
      zoom: ["Click the map to fit again · drag to pan · press Esc to close",
             "Haz clic en el mapa para ajustar · arrastra para moverte · pulsa Esc para cerrar"]
    };
    function setHint(key) {
      lightboxHint.dataset.en = HINTS[key][0];
      lightboxHint.dataset.es = HINTS[key][1];
      lightboxHint.textContent = (currentLang === "es") ? HINTS[key][1] : HINTS[key][0];
    }
    setHint("fit");

    function naturalSize() {
      return {
        w: lightboxImg.naturalWidth || lightboxImg.width || 1600,
        h: lightboxImg.naturalHeight || lightboxImg.height || 1200
      };
    }
    function fitScale() {
      var n = naturalSize();
      var availW = window.innerWidth * 0.94;
      var availH = window.innerHeight * 0.84;
      return Math.min(availW / n.w, availH / n.h);
    }
    function applyZoom(center) {
      var n = naturalSize();
      var fit = fitScale();
      var scale = fit;
      if (zoomLevel > 1) {
        scale = Math.min(fit * 2.5, 1);
        if (scale <= fit) scale = fit * 2;
      }
      lightboxImg.style.width = Math.round(n.w * scale) + "px";
      lightboxImg.style.height = Math.round(n.h * scale) + "px";
      lightbox.classList.toggle("zoomed", zoomLevel > 1);
      setHint(zoomLevel > 1 ? "zoom" : "fit");
      if (center) {
        lightboxStage.scrollLeft = (lightboxStage.scrollWidth - lightboxStage.clientWidth) / 2;
        lightboxStage.scrollTop = (lightboxStage.scrollHeight - lightboxStage.clientHeight) / 2;
      }
    }
    function openLightbox(el) {
      zoomLevel = 1;
      lightboxImg.src = el.dataset.zoom;
      lightbox.hidden = false;
      if (lightboxImg.complete) applyZoom(false);
    }
    function closeLightbox() {
      lightbox.hidden = true;
      lightboxImg.removeAttribute("src");
    }
    lightboxImg.addEventListener("load", function () {
      if (!lightbox.hidden) applyZoom(zoomLevel > 1);
    });

    var dragging = false, moved = false;
    var startX = 0, startY = 0, startSL = 0, startST = 0;
    lightboxImg.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (moved) return;
      zoomLevel = (zoomLevel === 1) ? 2 : 1;
      applyZoom(zoomLevel === 2);
    });
    lightboxStage.addEventListener("pointerdown", function (ev) {
      if (zoomLevel < 2) return;
      dragging = true;
      moved = false;
      startX = ev.clientX; startY = ev.clientY;
      startSL = lightboxStage.scrollLeft; startST = lightboxStage.scrollTop;
      lightboxStage.setPointerCapture(ev.pointerId);
    });
    lightboxStage.addEventListener("pointermove", function (ev) {
      if (!dragging) return;
      var dx = ev.clientX - startX, dy = ev.clientY - startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      lightboxStage.scrollLeft = startSL - dx;
      lightboxStage.scrollTop = startST - dy;
    });
    ["pointerup", "pointercancel"].forEach(function (type) {
      lightboxStage.addEventListener(type, function () {
        if (!dragging) return;
        dragging = false;
        setTimeout(function () { moved = false; }, 0);
      });
    });
    lightbox.addEventListener("click", function (ev) {
      if (ev.target === lightbox) closeLightbox();
    });
    window.addEventListener("resize", function () {
      if (!lightbox.hidden && lightboxImg.complete) applyZoom(zoomLevel > 1);
    });

    zoomables.forEach(function (el) {
      el.addEventListener("click", function () { openLightbox(el); });
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openLightbox(el); }
      });
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !lightbox.hidden) closeLightbox();
    });
  }

  function routeFromHash() {
    var m = (location.hash || "").match(/^#(unit|artifact|event|scenario|country|group|bonus|tab)\/([\w_-]+)/);
    if (m) goto(m[1], m[2]);
  }
  window.addEventListener("hashchange", routeFromHash);
  setTab("tab-rules");
  setLang(currentLang);
  routeFromHash();
})();