/* Dependency-free syntax highlighter.
   highlightCode(source, language) -> HTML string preserving exact whitespace,
   suitable for an overlay <pre> beneath a transparent <textarea>. */
(function () {
  const PY_KW = new Set(("False None True and as assert async await break class continue def del " +
    "elif else except finally for from global if import in is lambda nonlocal not or pass raise " +
    "return try while with yield match case").split(" "));
  const PY_BI = new Set(("print len range int float str bool list dict set tuple sum min max abs round " +
    "sorted enumerate zip map filter open type isinstance input reversed any all format object super " +
    "staticmethod classmethod property repr id hash next iter").split(" "));

  const AIDL_KW = new Set("if elif else for while in and or not print true false none break continue return def let".split(" "));
  const AIDL_BI = new Set("load classifier regressor range len str int float bool round abs min max sum sorted type print".split(" "));

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function highlight(src, language) {
    if (src == null) return "";
    const KW = language === "aidl" ? AIDL_KW : PY_KW;
    const BI = language === "aidl" ? AIDL_BI : PY_BI;
    let out = "";
    let i = 0;
    const n = src.length;
    let prevWord = null;

    while (i < n) {
      const ch = src[i];

      // comment to end of line
      if (ch === "#") {
        let j = i;
        while (j < n && src[j] !== "\n") j++;
        out += '<span class="tok-com">' + esc(src.slice(i, j)) + "</span>";
        i = j;
        prevWord = null;
        continue;
      }

      // strings (single/double, with escapes). triple-quote handled as run of same.
      if (ch === '"' || ch === "'") {
        const quote = ch;
        const triple = src.substr(i, 3) === quote + quote + quote;
        let j = i + (triple ? 3 : 1);
        if (triple) {
          while (j < n && src.substr(j, 3) !== quote + quote + quote) j++;
          j = Math.min(n, j + 3);
        } else {
          while (j < n && src[j] !== quote && src[j] !== "\n") {
            if (src[j] === "\\") j++;
            j++;
          }
          if (j < n && src[j] === quote) j++;
        }
        out += '<span class="tok-str">' + esc(src.slice(i, j)) + "</span>";
        i = j;
        prevWord = null;
        continue;
      }

      // numbers
      if (/[0-9]/.test(ch) && !(prevWord && /[A-Za-z0-9_]$/.test(prevWord))) {
        let j = i;
        while (j < n && /[0-9._eExXa-fA-F]/.test(src[j])) j++;
        out += '<span class="tok-num">' + esc(src.slice(i, j)) + "</span>";
        i = j;
        prevWord = null;
        continue;
      }

      // identifiers / keywords
      if (/[A-Za-z_]/.test(ch)) {
        let j = i;
        while (j < n && /[A-Za-z0-9_]/.test(src[j])) j++;
        const word = src.slice(i, j);
        let cls = null;
        if (KW.has(word)) cls = "tok-kw";
        else if (prevWord === "def" || prevWord === "class") cls = "tok-def";
        else if (BI.has(word)) cls = "tok-bi";
        out += cls ? '<span class="' + cls + '">' + esc(word) + "</span>" : esc(word);
        i = j;
        prevWord = word;
        continue;
      }

      // whitespace bookkeeping for prevWord (so "def name" still sees def)
      if (/\s/.test(ch)) {
        out += ch === "\n" ? "\n" : esc(ch);
        // keep prevWord across spaces, reset on newline
        if (ch === "\n") prevWord = null;
        i++;
        continue;
      }

      // any other char
      out += esc(ch);
      // operators reset "def" context except spaces handled above
      if (ch !== " " && ch !== "\t") prevWord = null;
      i++;
    }

    // keep final empty line height aligned with the textarea
    if (src.endsWith("\n")) out += " ";
    return out;
  }

  window.highlightCode = highlight;
})();
