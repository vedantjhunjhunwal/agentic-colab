/* Minimal, dependency-free Markdown -> HTML renderer.
   Supports: headings, bold/italic, inline code, fenced code, ordered/unordered
   lists, links, blockquotes, horizontal rules, simple tables, paragraphs.
   All HTML is escaped first to prevent injection. */
(function () {
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function inline(text) {
    // text is already HTML-escaped. Apply inline tokens.
    let t = text;
    // inline code (protect contents)
    const codes = [];
    t = t.replace(/`([^`]+)`/g, function (_, c) {
      codes.push(c);
      return "\u0000CODE" + (codes.length - 1) + "\u0000";
    });
    // links [text](url)
    t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, txt, url) {
      const safe = /^(https?:|mailto:|\/)/i.test(url) ? url : "#";
      return '<a href="' + safe + '" target="_blank" rel="noopener">' + txt + "</a>";
    });
    // bold then italic
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    t = t.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
    // restore code
    t = t.replace(/\u0000CODE(\d+)\u0000/g, function (_, i) {
      return "<code>" + codes[+i] + "</code>";
    });
    return t;
  }

  function render(src) {
    if (src == null) return "";
    const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
    let html = "";
    let i = 0;
    let listType = null; // 'ul' | 'ol'
    let para = [];

    function flushPara() {
      if (para.length) {
        html += "<p>" + inline(esc(para.join(" ").trim())) + "</p>";
        para = [];
      }
    }
    function closeList() {
      if (listType) { html += "</" + listType + ">"; listType = null; }
    }

    while (i < lines.length) {
      let line = lines[i];

      // fenced code block
      const fence = line.match(/^```(.*)$/);
      if (fence) {
        flushPara(); closeList();
        const buf = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++; // skip closing fence
        html += "<pre><code>" + esc(buf.join("\n")) + "</code></pre>";
        continue;
      }

      // horizontal rule
      if (/^\s*(?:---|\*\*\*|___)\s*$/.test(line)) {
        flushPara(); closeList(); html += "<hr>"; i++; continue;
      }

      // heading
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        flushPara(); closeList();
        const lvl = h[1].length;
        html += "<h" + lvl + ">" + inline(esc(h[2].trim())) + "</h" + lvl + ">";
        i++; continue;
      }

      // blockquote
      if (/^\s*>\s?/.test(line)) {
        flushPara(); closeList();
        const buf = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          buf.push(lines[i].replace(/^\s*>\s?/, "")); i++;
        }
        html += "<blockquote>" + inline(esc(buf.join(" "))) + "</blockquote>";
        continue;
      }

      // table (header | --- | rows)
      if (/\|/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && /-/.test(lines[i + 1])) {
        flushPara(); closeList();
        const headerCells = line.split("|").map(function (c) { return c.trim(); }).filter(function (c, idx, arr) { return !(idx === 0 && c === "") && !(idx === arr.length - 1 && c === ""); });
        i += 2;
        let tbl = "<table><thead><tr>";
        headerCells.forEach(function (c) { tbl += "<th>" + inline(esc(c)) + "</th>"; });
        tbl += "</tr></thead><tbody>";
        while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim() !== "") {
          const cells = lines[i].split("|").map(function (c) { return c.trim(); }).filter(function (c, idx, arr) { return !(idx === 0 && c === "") && !(idx === arr.length - 1 && c === ""); });
          tbl += "<tr>";
          cells.forEach(function (c) { tbl += "<td>" + inline(esc(c)) + "</td>"; });
          tbl += "</tr>";
          i++;
        }
        tbl += "</tbody></table>";
        html += tbl;
        continue;
      }

      // lists
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        flushPara();
        const want = ul ? "ul" : "ol";
        if (listType && listType !== want) closeList();
        if (!listType) { listType = want; html += "<" + want + ">"; }
        html += "<li>" + inline(esc((ul ? ul[1] : ol[1]).trim())) + "</li>";
        i++; continue;
      } else if (listType && line.trim() === "") {
        closeList(); i++; continue;
      }

      // blank line ends paragraph
      if (line.trim() === "") { flushPara(); i++; continue; }

      // accumulate paragraph
      closeList();
      para.push(line.trim());
      i++;
    }
    flushPara(); closeList();
    return html;
  }

  window.renderMarkdown = render;
})();
