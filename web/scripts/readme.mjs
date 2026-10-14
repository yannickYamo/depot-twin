// Render the README and the story as pages beside the site, so a reader can go from the running depot to
// the README without leaving the browser. A small renderer on purpose: the README
// uses headings, paragraphs, lists, tables, emphasis, links, pictures, inline code and fenced code. Run by
// `npm run build` (prebuild) and `npm run dev`; the output is generated and not committed.

import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
/** Pictures the documents show, as written in them; copied into the site after rendering. */
const pictures = new Set();
/** Where the repository's other files are read from a page that only carries two of its documents. */
const REPOSITORY = "https://github.com/yannickYamo/depot-twin/blob/main/";
/** The folder of the document being rendered, so a link beside it resolves to the right file. */
let folder = "";

/** A link as the page should carry it: one to another file of the repository goes to the repository. */
function target(href) {
  if (/^(https?:|#|mailto:)/.test(href)) return href;
  const parts = [];
  for (const part of `${folder}${href}`.split("/")) {
    if (part === "..") parts.pop();
    else if (part !== "." && part !== "") parts.push(part);
  }
  return REPOSITORY + parts.join("/");
}

const escape = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
/** Text that goes inside a quoted attribute: the text is already escaped, and a quote would end the attribute. */
const attribute = (text) => text.replace(/"/g, "&quot;");

/** Emphasis, inline code and links inside a line. Code is handled first so that nothing inside it is touched. */
function inline(text) {
  const parts = text.split(/(`[^`]*`)/);
  return parts
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`") && part.length > 1) return `<code>${escape(part.slice(1, -1))}</code>`;
      let html = escape(part);
      html = html.replace(/\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)/g, ""); // a linked badge
      // A picture that stands on its own line is kept: it is copied beside the page and shown at its base name.
      html = html.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, href) => {
        pictures.add(href);
        return `<img src="${attribute(href.split("/").pop())}" alt="${attribute(alt)}" loading="lazy" />`;
      });
      html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => `<a href="${attribute(target(href))}">${label}</a>`);
      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      html = html.replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
      return html;
    })
    .join("");
}

function render(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let paragraph = [];
  let code = null;
  let list = null; // { tag, items }
  let table = null; // rows of cells
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
  const flush = () => {
    if (paragraph.length > 0) html.push(`<p>${inline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const close = () => {
    if (list) html.push(`<${list.tag}>${list.items.map((item) => `<li>${inline(item)}</li>`).join("")}</${list.tag}>`);
    if (table) {
      const [head, , ...rows] = table;
      const row = (row, tag) => `<tr>${row.map((cell) => `<${tag}>${inline(cell)}</${tag}>`).join("")}</tr>`;
      html.push(`<div class="table"><table><thead>${row(head, "th")}</thead><tbody>${rows.map((r) => row(r, "td")).join("")}</tbody></table></div>`);
    }
    list = null;
    table = null;
  };
  for (const line of lines) {
    if (code !== null) {
      if (line.startsWith("```")) {
        html.push(`<pre><code>${escape(code.join("\n"))}</code></pre>`);
        code = null;
      } else code.push(line);
      continue;
    }
    if (line.startsWith("```")) {
      flush();
      code = [];
      continue;
    }
    const item = /^(\d+\.|-) (.*)$/.exec(line);
    if (item) {
      flush();
      const tag = item[1] === "-" ? "ul" : "ol";
      if (table || (list && list.tag !== tag)) close();
      list = list ?? { tag, items: [] };
      list.items.push(item[2]);
      continue;
    }
    if (line.startsWith("|")) {
      flush();
      if (list) close();
      table = table ?? [];
      table.push(cells(line));
      continue;
    }
    // A blank line between numbered items does not end the list; anything else does.
    if (line.trim() !== "") close();
    const heading = /^(#{1,3}) (.*)$/.exec(line);
    if (heading) {
      flush();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    if (line.trim() === "") {
      flush();
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  close();
  return html.join("\n");
}

function page(body, title) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500&display=swap" rel="stylesheet" />
    <style>
      :root { --page: #ffffff; --ink: #050f1e; --slate: #5d6e83; --line: #e5e9f0; --blue: #006fee; --stage: #050f1e; --mint: #00e89d; }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--page); color: var(--ink); font: 400 1.05rem/1.6 "Outfit", system-ui, sans-serif; letter-spacing: -0.005em; }
      main { max-width: 760px; margin: 0 auto; padding: 40px 16px 80px; }
      nav { max-width: 760px; margin: 0 auto; padding: 20px 16px 0; }
      nav a { color: var(--blue); text-decoration: none; min-height: 24px; display: inline-block; }
      nav a:hover { text-decoration: underline; text-underline-offset: 3px; }
      h1 { font: 500 2.2rem/1.15 "Outfit", system-ui, sans-serif; letter-spacing: -0.02em; margin: 8px 0 20px; }
      h2 { font: 500 1.5rem/1.2 "Outfit", system-ui, sans-serif; letter-spacing: -0.01em; margin: 44px 0 14px; padding-top: 18px; border-top: 1px solid var(--ink); }
      h3 { font: 500 1.15rem/1.3 "Outfit", system-ui, sans-serif; margin: 28px 0 8px; }
      p { margin: 0 0 16px; }
      p:first-of-type { font-size: 1.15rem; }
      a { color: var(--blue); }
      img { display: block; width: 100%; height: auto; margin: 4px 0 18px; border: 1px solid var(--line); border-radius: 12px; }
      code { font: 0.92em ui-monospace, SFMono-Regular, Menlo, monospace; background: #f3f5f8; padding: 1px 5px; border-radius: 4px; }
      pre { background: var(--stage); color: #e5e9f0; padding: 16px 18px; border-radius: 12px; overflow-x: auto; margin: 0 0 18px; }
      pre code { background: none; padding: 0; color: inherit; font-size: 0.9rem; line-height: 1.5; }
      ul, ol { margin: 0 0 16px; padding-left: 22px; }
      li { margin: 0 0 8px; }
      .table { overflow-x: auto; margin: 0 0 18px; }
      table { border-collapse: collapse; width: 100%; font-size: 0.92rem; font-variant-numeric: tabular-nums; }
      th, td { text-align: left; padding: 8px 12px 8px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
      th { font-weight: 500; color: var(--slate); border-bottom-color: var(--ink); }
      pre code::selection { background: var(--mint); color: var(--stage); }
      @media (max-width: 560px) { body { font-size: 1rem; } h1 { font-size: 1.8rem; } }
    </style>
  </head>
  <body>
    <nav><a href="./">← Back to the running depot</a></nav>
    <main>
${body}
    </main>
  </body>
</html>
`;
}

const docs = [
  ["README.md", "readme.html", "depot-twin: decisions and trade-offs"],
  ["docs/STORY.md", "story.html", "depot-twin: the story"],
];
for (const [file, name, title] of docs) {
  folder = file.includes("/") ? `${dirname(file)}/` : "";
  const body = render(readFileSync(join(here, "..", "..", file), "utf8"));
  const out = join(here, "..", "public", name);
  writeFileSync(out, page(body, title));
  console.log(`wrote ${out}`);
}
// Pictures are looked for beside the README and beside the story, and copied flat into the site.
for (const href of pictures) {
  const found = [join(here, "..", "..", href), join(here, "..", "..", "docs", href)].find((path) => existsSync(path));
  if (found) copyFileSync(found, join(here, "..", "public", href.split("/").pop()));
}
// The picture a shared link shows is no document's picture, so it is copied by name.
const preview = join(here, "..", "..", "docs", "images", "preview.png");
if (existsSync(preview)) copyFileSync(preview, join(here, "..", "public", "preview.png"));
