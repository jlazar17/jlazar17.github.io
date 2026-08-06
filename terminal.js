/*
 * An interactive prompt for the terminal-styled pages.
 *
 * Progressive enhancement: without JavaScript the pages render exactly as they
 * did before, ending in a blinking cursor. With it, that cursor becomes a real
 * input that understands a small shell vocabulary, including commands that
 * query the publication list in publications.json.
 */
(function () {
    "use strict";

    var PAGES = {
        "~": "index.html",
        "home": "index.html",
        "research": "research.html",
        "publications": "publications.html",
        "cv": "cv.html"
    };

    var COMMANDS = [
        "help", "ls", "cd", "open", "cat", "grep", "papers",
        "whoami", "pwd", "history", "clear", "uname"
    ];

    // Fallbacks for `cat` when the file's content is not on the current page.
    var FILES = {
        "bio.txt": {
            selector: "cat bio.txt",
            text: "Postdoctoral researcher in high-energy neutrino astrophysics: neutrino\n" +
                  "telescope simulation, machine-learning event reconstruction, and searches\n" +
                  "for new physics with IceCube and next-generation detectors."
        },
        "contact.txt": {
            selector: "cat contact.txt",
            text: "email    jeff.p.lazar@gmail.com\n" +
                  "github   github.com/jlazar17\n" +
                  "inspire  inspirehep.net/authors/1771794\n" +
                  "arxiv    arxiv.org/a/lazar_j_1"
        },
        "overview.md": {
            selector: "cat overview.md",
            text: "Research at the intersection of high-energy astrophysics, particle physics,\n" +
                  "and computational methods, centred on neutrinos."
        },
        "summary.txt": { selector: "cat summary.txt", text: "See the cv page for positions, education, and software." }
    };

    var pubs = null;          // lazily fetched publications.json
    var history = [];
    var historyIndex = 0;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function esc(s) {
        return String(s).replace(/[&<>"]/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
        });
    }

    // ── the prompt ────────────────────────────────────────────────────────────

    function build() {
        var cursor = document.querySelector(".cmd .cursor");
        if (!cursor) return null;
        var line = cursor.closest(".cmd");
        var ps1 = cursor.closest(".ps1");

        var input = el("input", "term-input");
        input.type = "text";
        input.setAttribute("autocomplete", "off");
        input.setAttribute("autocapitalize", "off");
        input.setAttribute("spellcheck", "false");
        input.setAttribute("aria-label", "Terminal input. Type help for available commands.");
        cursor.parentNode.replaceChild(input, cursor);

        var hint = el("div", "term-hint", "type `help` and press enter");
        line.parentNode.insertBefore(hint, line.nextSibling);

        return { line: line, ps1: ps1, input: input, hint: hint };
    }

    function promptHTML(ps1) {
        return ps1 ? ps1.innerHTML.replace(/<input[\s\S]*?>/, "") : "$ ";
    }

    function echoCommand(term, text) {
        var block = el("div", "cmd");
        var span = el("span", "ps1");
        span.innerHTML = promptHTML(term.ps1) + " " + esc(text);
        block.appendChild(span);
        term.line.parentNode.insertBefore(block, term.line);
    }

    function write(term, html, className) {
        var out = el("div", "out term-out" + (className ? " " + className : ""));
        out.innerHTML = html;
        term.line.parentNode.insertBefore(out, term.line);
        return out;
    }

    // ── publication queries ───────────────────────────────────────────────────

    function loadPubs() {
        if (pubs) return Promise.resolve(pubs);
        return fetch("publications.json")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) { pubs = data; return pubs; });
    }

    function pubLine(p) {
        var link = p.arxiv
            ? ' <a href="https://arxiv.org/abs/' + esc(p.arxiv) + '" target="_blank">arXiv:' + esc(p.arxiv) + "</a>"
            : (p.doi ? ' <a href="https://doi.org/' + esc(p.doi) + '" target="_blank">doi</a>' : "");
        return '<span class="yellow">' + esc(p.year) + "</span>  " + esc(p.title) + link;
    }

    function renderPubs(term, list, note) {
        if (!list.length) {
            write(term, "no matching publications");
            return;
        }
        var shown = list.slice(0, 15);
        var html = shown.map(pubLine).join("<br>");
        if (list.length > shown.length) {
            html += '<br><span class="muted"># ' + (list.length - shown.length) +
                    " more; narrow the query or pass --limit</span>";
        }
        if (note) html = '<span class="muted"># ' + esc(note) + "</span><br>" + html;
        write(term, html);
    }

    function parseFlags(args) {
        var opts = { limit: 15, terms: [] };
        for (var i = 0; i < args.length; i++) {
            var a = args[i];
            if (a === "--year") opts.year = args[++i];
            else if (a === "--limit") opts.limit = parseInt(args[++i], 10) || 15;
            else if (a === "--collab") opts.collab = true;
            else if (a === "--no-collab") opts.collab = false;
            else if (a === "--first-author") opts.first = true;
            else if (a === "--proceedings") opts.kind = "proceedings";
            else if (a === "--papers") opts.kind = "paper";
            else opts.terms.push(a);
        }
        return opts;
    }

    function queryPubs(opts) {
        return pubs.filter(function (p) {
            if (opts.year && p.year !== String(opts.year)) return false;
            if (opts.collab === true && !p.collab) return false;
            if (opts.collab === false && p.collab) return false;
            if (opts.kind && p.kind !== opts.kind) return false;
            if (opts.first && !/^J\. Lazar/.test(p.authors)) return false;
            if (opts.terms.length) {
                var hay = (p.title + " " + p.authors + " " + p.venue).toLowerCase();
                return opts.terms.every(function (t) { return hay.indexOf(t.toLowerCase()) !== -1; });
            }
            return true;
        });
    }

    // ── commands ──────────────────────────────────────────────────────────────

    var HELP = [
        "available commands",
        "",
        "  help                 this message",
        "  ls                   list what is here",
        "  cd &lt;page&gt;            go to a page: research, publications, cv, ~",
        "  open &lt;target&gt;        a page, cv.pdf, or arxiv:2507.08457",
        "  cat &lt;file&gt;           bio.txt, contact.txt, overview.md",
        "  grep &lt;term&gt;          search titles, authors and venues",
        "  papers [flags]       --year 2025  --first-author  --collab / --no-collab",
        "                       --proceedings / --papers  --limit N",
        "  whoami, pwd, uname, history, clear"
    ].join("<br>");

    function run(term, raw) {
        var parts = raw.trim().split(/\s+/);
        var cmd = parts[0];
        var args = parts.slice(1);

        switch (cmd) {
        case "":
            return;
        case "help":
        case "?":
            write(term, HELP);
            return;
        case "ls":
            write(term,
                '<span class="cyan">research/</span>  <span class="cyan">publications/</span>  ' +
                "cv.pdf  bio.txt  contact.txt");
            return;
        case "cd":
        case "open": {
            var target = args[0] || "~";
            var m = /^arxiv:(.+)$/i.exec(target);
            if (m) {
                write(term, "opening arXiv:" + esc(m[1]));
                window.open("https://arxiv.org/abs/" + encodeURIComponent(m[1]), "_blank");
                return;
            }
            if (target === "cv.pdf") {
                write(term, "opening cv.pdf");
                window.open("cv.pdf", "_blank");
                return;
            }
            var page = PAGES[target.replace(/\/$/, "")];
            if (!page) {
                write(term, cmd + ": " + esc(target) + ": no such file or directory", "term-err");
                return;
            }
            write(term, "&rarr; " + esc(page));
            window.location.href = page;
            return;
        }
        case "cat": {
            var name = args[0] || "";
            if (name === "cv.pdf") {
                write(term, "cat: cv.pdf: binary file (try `open cv.pdf`)", "term-err");
                return;
            }
            var file = FILES[name];
            if (!file) {
                write(term, "cat: " + esc(name || "usage: cat <file>") + ": no such file", "term-err");
                return;
            }
            var found = null;
            var blocks = document.querySelectorAll(".cmd .c");
            for (var i = 0; i < blocks.length; i++) {
                if (blocks[i].textContent.trim() === file.selector) {
                    var out = blocks[i].closest(".cmd").nextElementSibling;
                    if (out && out.classList.contains("out")) found = out.innerHTML;
                    break;
                }
            }
            write(term, found || esc(file.text).replace(/\n/g, "<br>"));
            return;
        }
        case "whoami":
            write(term, "Jeffrey P. Lazar &mdash; neutrino physicist");
            return;
        case "pwd":
            write(term, "/home/jlazar" + (location.pathname.replace(/\/index\.html$|\/$/, "") || ""));
            return;
        case "uname":
            write(term, "neutrino-telescope 2.6.18 #1 SMP x86_64 GNU/Linux");
            return;
        case "history":
            write(term, history.map(function (h, i) {
                return "  " + (i + 1) + "  " + esc(h);
            }).join("<br>") || "no history yet");
            return;
        case "clear":
            var outs = term.line.parentNode.querySelectorAll(".term-out, .cmd");
            for (var j = 0; j < outs.length; j++) {
                if (outs[j] !== term.line) outs[j].remove();
            }
            var stale = term.line.parentNode.querySelectorAll(".out:not(.term-out)");
            for (var k = 0; k < stale.length; k++) stale[k].remove();
            return;
        case "grep":
        case "papers": {
            if (cmd === "grep" && !args.length) {
                write(term, "usage: grep &lt;term&gt;", "term-err");
                return;
            }
            var pending = write(term, '<span class="muted">searching…</span>');
            loadPubs().then(function () {
                var opts = parseFlags(args);
                var list = queryPubs(opts);
                pending.remove();
                renderPubs(term, list.slice(0, opts.limit),
                    list.length + " of " + pubs.length + " records match");
            }).catch(function (err) {
                pending.remove();
                write(term, "could not load publications.json (" + esc(err.message) + ")", "term-err");
            });
            return;
        }
        case "sudo":
            write(term, "jlazar is not in the sudoers file. This incident will be reported.", "term-err");
            return;
        default:
            write(term, esc(cmd) + ": command not found (try `help`)", "term-err");
        }
    }

    // ── wiring ────────────────────────────────────────────────────────────────

    function complete(value) {
        var parts = value.split(/\s+/);
        var pool = parts.length <= 1 ? COMMANDS : Object.keys(PAGES).concat(Object.keys(FILES));
        var stem = parts[parts.length - 1];
        var hits = pool.filter(function (c) { return c.indexOf(stem) === 0; });
        if (hits.length !== 1) return null;
        parts[parts.length - 1] = hits[0];
        return parts.join(" ");
    }

    document.addEventListener("DOMContentLoaded", function () {
        var term = build();
        if (!term) return;

        document.addEventListener("click", function (e) {
            if (window.getSelection().toString()) return;
            if (e.target.closest("a, button")) return;
            term.input.focus();
        });

        term.input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                var value = term.input.value;
                term.input.value = "";
                if (term.hint) { term.hint.remove(); term.hint = null; }
                if (value.trim()) {
                    history.push(value.trim());
                    historyIndex = history.length;
                }
                echoCommand(term, value);
                run(term, value);
                if (term.input.scrollIntoView) term.input.scrollIntoView({ block: "nearest" });
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                if (historyIndex > 0) term.input.value = history[--historyIndex];
            } else if (e.key === "ArrowDown") {
                e.preventDefault();
                if (historyIndex < history.length - 1) term.input.value = history[++historyIndex];
                else { historyIndex = history.length; term.input.value = ""; }
            } else if (e.key === "Tab") {
                e.preventDefault();
                var done = complete(term.input.value);
                if (done) term.input.value = done;
            } else if (e.key === "l" && e.ctrlKey) {
                e.preventDefault();
                run(term, "clear");
            }
        });
    });
}());
