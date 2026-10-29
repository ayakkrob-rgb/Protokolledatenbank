/* Protokolldatenbank – kleine Helfer ohne Abhängigkeiten. Alles funktioniert auch ohne JavaScript. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function formatEur(cents) {
    return (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
  }

  document.addEventListener("DOMContentLoaded", function () {
    /* Mobile Navigation */
    $$("[data-nav-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var nav = $(btn.getAttribute("data-nav-toggle"));
        if (!nav) return;
        var open = nav.classList.toggle("open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });

    /* Sicherheitsabfragen */
    $$("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
      });
    });
    $$("button[data-confirm]").forEach(function (btn) {
      btn.addEventListener("click", function (event) {
        if (!window.confirm(btn.getAttribute("data-confirm"))) event.preventDefault();
      });
    });

    /* Automatisch absenden (Filter) */
    $$("[data-autosubmit]").forEach(function (el) {
      el.addEventListener("change", function () { el.form && el.form.submit(); });
    });

    /* Alle auswählen */
    $$("[data-check-all]").forEach(function (box) {
      box.addEventListener("change", function () {
        var form = box.form || box.closest("form");
        $$('input[type="checkbox"][name="' + box.getAttribute("data-check-all") + '"]', form).forEach(function (cb) {
          cb.checked = box.checked;
        });
      });
    });

    /* In die Zwischenablage kopieren */
    $$("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var input = $(btn.getAttribute("data-copy"));
        if (!input) return;
        var done = function () {
          var old = btn.textContent;
          btn.textContent = "Kopiert ✓";
          setTimeout(function () { btn.textContent = old; }, 1600);
        };
        if (navigator.clipboard) {
          navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
        } else {
          input.select();
          document.execCommand("copy");
          done();
        }
      });
    });

    /* Live-Filter für Listen */
    $$("[data-filter]").forEach(function (input) {
      var scope = $(input.getAttribute("data-filter"));
      if (!scope) return;
      var empty = $(input.getAttribute("data-filter-empty") || "#__none__");
      input.addEventListener("input", function () {
        var q = input.value.trim().toLowerCase();
        var visible = 0;
        $$("[data-filter-text]", scope).forEach(function (item) {
          var match = !q || item.getAttribute("data-filter-text").toLowerCase().indexOf(q) !== -1;
          item.hidden = !match;
          if (match) visible += 1;
        });
        $$("[data-filter-group]", scope).forEach(function (group) {
          group.hidden = $$("[data-filter-text]", group).every(function (i) { return i.hidden; });
        });
        if (empty) empty.hidden = visible !== 0;
      });
    });

    /* Prüferauswahl */
    $$("[data-selection]").forEach(function (form) {
      var max = parseInt(form.getAttribute("data-max"), 10) || 4;
      var price = parseInt(form.getAttribute("data-price"), 10) || 0;
      var slots = parseInt(form.getAttribute("data-free-slots"), 10) || 0;
      var cards = $$(".examiner-card.selectable", form);
      var countEl = $("[data-selection-count]", form);
      var hintEl = $("[data-selection-hint]", form);
      var submit = $("[data-selection-submit]", form);

      function update() {
        var selected = cards.filter(function (c) { return $("input.select-input", c).checked; });
        var n = selected.length;
        cards.forEach(function (card) {
          var input = $("input.select-input", card);
          card.classList.toggle("is-selected", input.checked);
          card.classList.toggle("is-limit", n >= max && !input.checked);
        });
        if (countEl) countEl.textContent = n + " von " + max + " Prüfern ausgewählt";
        if (hintEl) {
          if (n === 0) hintEl.textContent = "Wähle die Prüfer aus deiner Prüfungskommission.";
          else if (slots > 0 && n <= slots) hintEl.textContent = "Kostenlos in dein bestehendes Paket übernehmbar.";
          else hintEl.textContent = "Paketpreis: " + formatEur(price);
        }
        if (submit) submit.disabled = n === 0;
      }

      cards.forEach(function (card) {
        var input = $("input.select-input", card);
        input.addEventListener("change", function () {
          var n = cards.filter(function (c) { return $("input.select-input", c).checked; }).length;
          if (input.checked && n > max) {
            input.checked = false;
            if (card.animate) card.animate([{ transform: "translateX(-3px)" }, { transform: "translateX(3px)" }, { transform: "none" }], { duration: 180 });
          }
          update();
        });
      });
      update();
    });

    /* Neuer Prüfer: Zusatzfelder ein-/ausblenden */
    function bindExaminerSelect(root) {
      $$("[data-examiner-select]", root).forEach(function (select) {
        var box = select.closest("[data-section]");
        var extra = box && $("[data-new-examiner]", box);
        var sync = function () { if (extra) extra.hidden = select.value !== "new"; };
        select.addEventListener("change", sync);
        sync();
      });
    }

    /* Zeichenzähler */
    function bindCounters(root) {
      $$("textarea[data-min-length]", root).forEach(function (area) {
        var min = parseInt(area.getAttribute("data-min-length"), 10) || 0;
        var out = document.createElement("p");
        out.className = "help";
        area.insertAdjacentElement("afterend", out);
        var sync = function () {
          var n = area.value.trim().length;
          out.textContent = n + " Zeichen" + (min ? (n < min ? " – mindestens " + min + " ohne Datei" : " ✓") : "");
        };
        area.addEventListener("input", sync);
        sync();
      });
    }

    /* Upload: weitere Prüfer-Abschnitte (Django-Formset) */
    $$("[data-formset]").forEach(function (wrap) {
      var prefix = wrap.getAttribute("data-formset");
      var max = parseInt(wrap.getAttribute("data-max"), 10) || 4;
      var list = $("[data-formset-list]", wrap);
      var template = $("template[data-formset-template]", wrap);
      var addBtn = $("[data-formset-add]", wrap);
      var total = $("#id_" + prefix + "-TOTAL_FORMS", wrap);
      var re = new RegExp(prefix + "-(\\d+|__prefix__)-", "g");

      function renumber() {
        var sections = $$("[data-section]", list);
        sections.forEach(function (section, index) {
          $$("[name], [id], [for]", section).forEach(function (el) {
            ["name", "id", "for"].forEach(function (attr) {
              var value = el.getAttribute(attr);
              if (value) el.setAttribute(attr, value.replace(re, prefix + "-" + index + "-"));
            });
          });
          var num = $("[data-section-num]", section);
          if (num) num.textContent = index + 1;
          var remove = $("[data-formset-remove]", section);
          if (remove) remove.hidden = sections.length === 1;
        });
        total.value = sections.length;
        if (addBtn) addBtn.hidden = sections.length >= max;
      }

      if (addBtn && template) {
        addBtn.addEventListener("click", function () {
          var count = $$("[data-section]", list).length;
          if (count >= max) return;
          var html = template.innerHTML.replace(/__prefix__/g, count);
          var holder = document.createElement("div");
          holder.innerHTML = html.trim();
          var section = holder.firstElementChild;
          list.appendChild(section);
          bindExaminerSelect(section);
          bindCounters(section);
          renumber();
          var first = $("select", section);
          if (first) first.focus();
        });
      }
      list.addEventListener("click", function (event) {
        var btn = event.target.closest("[data-formset-remove]");
        if (!btn) return;
        var section = btn.closest("[data-section]");
        if (section && $$("[data-section]", list).length > 1) {
          section.remove();
          renumber();
        }
      });
      renumber();
    });
    bindExaminerSelect(document);
    bindCounters(document);

    /* Tabs (Einstellungen) */
    $$("[data-tabs]").forEach(function (tabs) {
      var links = $$("a[href^='#']", tabs);
      var hidden = $(tabs.getAttribute("data-tabs-input") || "#__none__");
      function activate(id, push) {
        var found = false;
        links.forEach(function (link) {
          var on = link.getAttribute("href") === "#" + id;
          link.classList.toggle("active", on);
          var panel = document.getElementById(link.getAttribute("href").slice(1));
          if (panel) panel.classList.toggle("active", on);
          if (on) found = true;
        });
        if (hidden) hidden.value = id;
        if (push && history.replaceState) history.replaceState(null, "", "#" + id);
        return found;
      }
      links.forEach(function (link) {
        link.addEventListener("click", function (event) {
          event.preventDefault();
          activate(link.getAttribute("href").slice(1), true);
        });
      });
      var errored = links.filter(function (l) { return l.classList.contains("has-error"); })[0];
      var initial = errored ? errored.getAttribute("href").slice(1) : (location.hash || "").slice(1);
      if (!initial || !activate(initial, false)) {
        activate(links[0].getAttribute("href").slice(1), false);
      }
    });
  });
})();
