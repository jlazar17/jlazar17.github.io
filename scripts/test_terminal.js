// Headless functional test of the site's interactive prompt.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const SITE = "/Users/jlazar/website";
const pubs = JSON.parse(fs.readFileSync(path.join(SITE, "publications.json"), "utf8"));

let failures = 0;
function check(name, cond, detail) {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${name}${cond ? "" : "  <- " + detail}`);
  if (!cond) failures++;
}

async function boot(page) {
  const html = fs.readFileSync(path.join(SITE, page), "utf8");
  const dom = new JSDOM(html, { runScripts: "outside-only", url: "https://www.jefflazaris.online/" + page });
  const { window } = dom;
  window.fetch = (url) =>
    Promise.resolve({ ok: url.includes("publications.json"), status: 200, json: () => Promise.resolve(pubs) });
  window.open = (u) => { window.__opened = u; };
  const script = fs.readFileSync(path.join(SITE, "terminal.js"), "utf8");
  window.eval(script);
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));
  return window;
}

function type(window, text) {
  const input = window.document.querySelector(".term-input");
  input.value = text;
  const ev = new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true });
  input.dispatchEvent(ev);
  return input;
}

function lastOut(window) {
  const outs = window.document.querySelectorAll(".term-out");
  return outs.length ? outs[outs.length - 1].textContent.trim() : "";
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  console.log("index.html");
  let w = await boot("index.html");
  check("prompt input replaces the blinking cursor", !!w.document.querySelector(".term-input"), "no .term-input");
  check("hint is shown", /help/.test((w.document.querySelector(".term-hint") || {}).textContent || ""), "no hint");

  type(w, "help");
  check("help lists commands", /grep/.test(lastOut(w)) && /papers/.test(lastOut(w)), lastOut(w).slice(0, 60));

  type(w, "ls");
  check("ls lists pages and files", /research\//.test(lastOut(w)) && /cv\.pdf/.test(lastOut(w)), lastOut(w));

  type(w, "whoami");
  check("whoami", /Jeffrey P\. Lazar/.test(lastOut(w)), lastOut(w));

  type(w, "cat bio.txt");
  check("cat bio.txt reads the page's own text", /neutrino/i.test(lastOut(w)), lastOut(w).slice(0, 60));

  type(w, "cat nope.txt");
  check("unknown file errors", /no such file/.test(lastOut(w)), lastOut(w));

  type(w, "banana");
  check("unknown command errors", /command not found/.test(lastOut(w)), lastOut(w));

  type(w, "cat cv.pdf");
  check("cat on a pdf is refused", /binary file/.test(lastOut(w)), lastOut(w));

  type(w, "open arxiv:2507.08457");
  check("open arxiv: opens the abstract", w.__opened === "https://arxiv.org/abs/2507.08457", w.__opened);

  type(w, "history");
  check("history records commands", /1  help/.test(lastOut(w)), lastOut(w).slice(0, 40));

  // publication queries are async
  type(w, "grep solar");
  await wait(50);
  let out = lastOut(w);
  check("grep solar returns solar papers", /Sun|Solar/i.test(out), out.slice(0, 80));
  check("grep reports the match count", /records match/.test(out), out.slice(0, 60));

  type(w, "papers --year 2026 --first-author");
  await wait(50);
  out = lastOut(w);
  const expected = pubs.filter((p) => p.year === "2026" && /^J\. Lazar/.test(p.authors));
  check("papers --year --first-author filters", out.includes("2026") && !/2019/.test(out), out.slice(0, 80));
  check(`  (expected ${expected.length} matches)`, expected.length > 0, "none in data");

  type(w, "papers --no-collab --limit 3");
  await wait(50);
  out = lastOut(w);
  check("papers --no-collab excludes collaboration papers", !/Collaboration/.test(out), out.slice(0, 80));

  type(w, "grep");
  check("grep with no term shows usage", /usage/.test(lastOut(w)), lastOut(w));

  type(w, "clear");
  check("clear empties the output", w.document.querySelectorAll(".term-out").length === 0,
        w.document.querySelectorAll(".term-out").length + " left");

  console.log("\npublications.html");
  w = await boot("publications.html");
  check("prompt exists on generated page", !!w.document.querySelector(".term-input"), "no input");
  type(w, "papers --proceedings --limit 2");
  await wait(50);
  check("proceedings filter works", /\d{4}/.test(lastOut(w)), lastOut(w).slice(0, 60));
  check("collab toggle button still present", !!w.document.getElementById("collab-toggle"), "toggle missing");

  console.log("\ncv.html");
  w = await boot("cv.html");
  type(w, "cat summary.txt");
  check("cat summary.txt uses the page content", lastOut(w).length > 20, lastOut(w));

  console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
