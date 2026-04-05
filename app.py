from flask import Flask, request, jsonify, render_template_string
import os, re, requests as req
import base64

app = Flask(__name__)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

MODE_PROMPTS = {
    "Standard":   "Rewrite naturally, human-written. Vary sentence structure and vocabulary. Keep word count within 10% of input.",
    "Academic":   "Rewrite in formal academic style with scholarly vocabulary. Keep word count within 10% of input.",
    "Creative":   "Rewrite with vivid expressive language and fresh phrasing. Keep word count within 15% of input.",
    "Formal":     "Rewrite in polished professional register for business. Keep word count within 10% of input.",
    "Simplified": "Rewrite in simple clear language with short sentences. Keep word count within 10% of input."
}

SYSTEM_BASE = """You are an expert text rewriter who rewrites text to sound 100% natural and human-written.
STRICT RULES:
1. Preserve EXACT meaning. Never drop or distort any fact.
2. Significantly change vocabulary, phrasing, and sentence structure.
3. NEVER repeat the same keyword or phrase unnecessarily.
4. Output ONLY the rewritten text. NO preamble like "Here is..." or "Sure,".
5. Works on ANY length: 20 words to 1000+ words.
6. Grammatically perfect, natural conversational flow.
7. Do NOT add any new content not in the original.
8. CRITICAL WORD COUNT RULE:
   Input=20 words  -> output=18-23 words
   Input=80 words  -> output=72-90 words (NOT 130!)
   Input=200 words -> output=180-220 words
9. HUMAN LANGUAGE RULES — Very Important:
   - NEVER use stiff formal openers like "I wish you are doing well" or "I hope this finds you well"
   - Instead use natural openers like "Hope you are doing well" or "Hope you are having a good week"
   - NEVER use overly formal words like "promptly", "aforementioned", "henceforth", "utilize"
   - Instead use natural words like "quickly", "mentioned", "from now on", "use"
   - NEVER use "at your earliest convenience" — use "whenever you have a moment" or "at your earliest"
   - Write like a confident, educated human — not like a corporate robot or AI assistant
   - Vary sentence length: mix short punchy sentences with longer ones
   - Use contractions naturally where appropriate (it's, you'll, we've, don't)"""

STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "is","are","was","were","be","been","being","have","has","had","do",
    "does","did","will","would","could","should","may","might","shall","can",
    "this","that","these","those","it","its","i","you","he","she","we","they",
    "me","him","her","us","them","my","your","his","our","their","not","no",
    "so","as","if","by","from","up","about","into","than","then","also",
    "just","more","some","such","which","who","when","where","what","how",
    "all","each","every","both","few","most","other","same","very","quite"
}

def cw(w):
    return re.sub(r"[^a-zA-Z]", "", w).lower()

def count_changed(orig, rew):
    os_ = {cw(w) for w in orig.split() if cw(w) and cw(w) not in STOP}
    return sum(1 for w in rew.split() if cw(w) and cw(w) not in STOP and cw(w) not in os_)

def human_pct(orig, rew):
    os_ = {cw(w) for w in orig.split() if cw(w) and cw(w) not in STOP}
    om  = [cw(w) for w in rew.split() if cw(w) and cw(w) not in STOP]
    if not om: return 0
    return min(round(sum(1 for w in om if w not in os_) / len(om) * 100), 100)

def highlight_html(orig, rew):
    os_ = {cw(w) for w in orig.split()}
    parts = []
    for t in re.split(r'(\s+|\n+)', rew):
        if re.match(r'^[\s\n]+$', t):
            parts.append(t.replace('\n', '<br>'))
            continue
        c = cw(t)
        if c and c not in STOP and c not in os_:
            parts.append('<span class="cw" data-word="' + c + '">' + t + '</span>')
        else:
            parts.append(t)
    return ''.join(parts)

HTML_PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Text Humanizer</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#060912;--sf:rgba(255,255,255,0.04);--br:rgba(255,255,255,0.09);--br2:rgba(255,255,255,0.16);--ac:#00d4ff;--ac2:#7c3aed;--ac3:#10b981;--tx:#e8eaf2;--dm:#8892a4;--dmr:#4a5568;}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{font-family:"DM Sans",sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;padding:20px;}
body::before{content:"";position:fixed;inset:0;background:radial-gradient(ellipse 55% 45% at 10% 15%,rgba(0,212,255,0.07) 0%,transparent 55%),radial-gradient(ellipse 45% 55% at 90% 85%,rgba(124,58,237,0.08) 0%,transparent 55%);pointer-events:none;z-index:0;}
.wrap{max-width:1300px;margin:0 auto;position:relative;z-index:1;}
.hdr{background:linear-gradient(135deg,rgba(0,212,255,0.08),rgba(124,58,237,0.08));border:1px solid var(--br2);border-radius:18px;padding:22px 28px;margin-bottom:16px;position:relative;overflow:hidden;}
.hdr::before{content:"";position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--ac),var(--ac2),transparent);}
.hdr h1{font-family:"Syne",sans-serif;font-size:26px;font-weight:800;background:linear-gradient(135deg,var(--ac),var(--ac2) 50%,var(--ac3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:5px;}
.hdr p{color:var(--dm);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:12px;}
.pills{display:flex;gap:8px;flex-wrap:wrap;}
.pill{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.05);border:1px solid var(--br2);border-radius:100px;padding:4px 12px;font-size:12px;color:var(--dm);}
.pill b{color:var(--tx);}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
.dot-a{background:var(--ac);box-shadow:0 0 6px var(--ac);}
.dot-b{background:var(--ac2);box-shadow:0 0 6px var(--ac2);}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:14px;}
@media(max-width:800px){.grid{grid-template-columns:1fr;}}
.panel{background:var(--sf);border:1px solid var(--br);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;}
.panel-hdr{padding:12px 16px;border-bottom:1px solid var(--br);background:rgba(255,255,255,0.02);font-family:"Syne",sans-serif;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);font-weight:700;}
textarea{flex:1;min-height:320px;padding:16px;background:transparent;border:none;outline:none;color:var(--tx);font-family:"DM Sans",sans-serif;font-size:15px;line-height:1.75;resize:none;font-weight:300;}
textarea::placeholder{color:var(--dmr);}
.controls{padding:12px 16px;border-top:1px solid var(--br);display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
select{background:rgba(255,255,255,0.05);border:1px solid var(--br2);border-radius:8px;color:var(--tx);padding:8px 12px;font-family:"DM Sans",sans-serif;font-size:13px;cursor:pointer;}
.btn-main{padding:10px 24px;border-radius:10px;border:none;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;font-family:"Syne",sans-serif;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 16px rgba(0,212,255,0.25);transition:all 0.2s;display:flex;align-items:center;gap:8px;}
.btn-main:hover{transform:translateY(-1px);}
.btn-main:disabled{opacity:0.5;cursor:not-allowed;transform:none;}
.btn-sec{padding:10px 18px;border-radius:10px;border:1px solid var(--br2);background:var(--sf);color:var(--tx);font-family:"DM Sans",sans-serif;font-size:13px;cursor:pointer;}
.output-body{flex:1;min-height:320px;padding:16px;overflow-y:auto;}
.empty{color:var(--dmr);font-style:italic;display:flex;align-items:center;justify-content:center;height:280px;flex-direction:column;gap:10px;text-align:center;font-size:14px;}
.prog-box{background:rgba(255,255,255,0.03);border:1px solid var(--br2);border-radius:12px;padding:14px 16px;margin-bottom:11px;}
.prog-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.prog-label{font-family:"Syne",sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);font-weight:700;}
.prog-val{font-weight:700;font-size:14px;}
.prog-track{height:9px;background:rgba(255,255,255,0.06);border-radius:100px;overflow:hidden;margin-bottom:4px;}
.prog-fill{height:100%;border-radius:100px;min-width:4px;}
.prog-scale{display:flex;justify-content:space-between;font-size:10px;color:var(--dmr);}
.wc-ok{background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:9px;padding:8px 13px;font-size:13px;color:rgba(16,185,129,0.9);margin-bottom:10px;}
.wc-warn{background:rgba(251,191,36,0.08);border:1px solid rgba(251,191,36,0.25);border-radius:9px;padding:8px 13px;font-size:13px;color:rgba(251,191,36,0.9);margin-bottom:10px;}
.wc-short{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:9px;padding:8px 13px;font-size:13px;color:rgba(239,68,68,0.85);margin-bottom:10px;}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:11px;}
.chip{padding:4px 11px;border-radius:7px;font-size:12px;border:1px solid;}
.ci{background:rgba(0,212,255,0.07);border-color:rgba(0,212,255,0.2);color:rgba(0,212,255,0.9);}
.co{background:rgba(16,185,129,0.07);border-color:rgba(16,185,129,0.2);color:rgba(16,185,129,0.9);}
.cc{background:rgba(251,191,36,0.08);border-color:rgba(251,191,36,0.25);color:rgba(251,191,36,0.9);}
.cm{background:rgba(255,255,255,0.04);border-color:var(--br2);color:var(--dm);}
.out-box{background:rgba(255,255,255,0.02);border:1px solid var(--br);border-radius:11px;padding:15px 17px;}
.out-text{font-size:15px;line-height:1.8;font-weight:300;color:var(--tx);}
.cw{background:rgba(251,191,36,0.15);color:#fbbf24;border-bottom:1.5px solid rgba(251,191,36,0.5);border-radius:4px;padding:1px 4px;font-weight:500;cursor:pointer;position:relative;}
.cw:hover{background:rgba(251,191,36,0.28);}
.syn-popup{position:fixed;background:#1a1f35;border:1px solid rgba(255,255,255,0.16);border-radius:10px;padding:5px;z-index:9999;min-width:130px;box-shadow:0 8px 24px rgba(0,0,0,0.5);display:none;}
.syn-popup.show{display:block;}
.syn-item{padding:7px 12px;border-radius:7px;font-size:13px;color:#e8eaf2;cursor:pointer;font-family:"DM Sans",sans-serif;}
.syn-item:hover{background:rgba(0,212,255,0.12);color:#00d4ff;}
.copy-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;margin-top:10px;}
.copy-btn{padding:6px 14px;border-radius:8px;border:1px solid rgba(16,185,129,0.3);background:rgba(16,185,129,0.08);color:#10b981;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:5px;font-family:"DM Sans",sans-serif;transition:all 0.2s;}
.copy-btn:hover{background:rgba(16,185,129,0.15);}
.copy-btn.copied{color:#10b981;border-color:rgba(16,185,129,0.5);}
.plain-box{margin-top:10px;}
.plain-label{font-family:"Syne",sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);display:block;margin-bottom:6px;}
.plain-ta{min-height:90px;background:rgba(255,255,255,0.02);border:1px solid var(--br);border-radius:10px;padding:12px;font-size:14px;color:var(--tx);width:100%;resize:vertical;font-family:"DM Sans",sans-serif;outline:none;}
.stats{background:rgba(0,212,255,0.04);border:1px solid rgba(0,212,255,0.1);border-radius:9px;padding:8px 14px;font-size:12px;color:var(--dm);margin-bottom:14px;}
.legend{font-size:12px;color:var(--dm);margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.lgnd-sw{width:12px;height:12px;background:rgba(251,191,36,0.2);border:1px solid rgba(251,191,36,0.4);border-radius:3px;display:inline-block;flex-shrink:0;}
.ftr{text-align:center;padding:12px 0 0;color:var(--dmr);font-size:12px;border-top:1px solid var(--br);line-height:1.8;}
.ftr b{color:var(--dm);}
.upload-bar{padding:10px 16px;border-top:1px solid var(--br);display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.upload-btn{padding:6px 14px;border-radius:8px;border:1px dashed rgba(0,212,255,0.3);background:rgba(0,212,255,0.04);color:var(--ac);font-size:12px;cursor:pointer;font-family:"DM Sans",sans-serif;transition:all 0.2s;}
.upload-btn:hover{background:rgba(0,212,255,0.1);border-color:var(--ac);}
.upload-hint{font-size:11px;color:var(--dmr);}
.upload-progress{font-size:11px;color:var(--ac3);display:none;}
.history-wrap{margin-bottom:14px;}
.history-panel{background:var(--sf);border:1px solid var(--br);border-radius:16px;overflow:hidden;}
.history-hdr{padding:12px 16px;border-bottom:1px solid var(--br);background:rgba(255,255,255,0.02);font-family:"Syne",sans-serif;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);font-weight:700;display:flex;justify-content:space-between;align-items:center;}
.history-list{max-height:220px;overflow-y:auto;}
.history-item{padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.15s;display:flex;justify-content:space-between;align-items:center;gap:10px;}
.history-item:hover{background:rgba(255,255,255,0.04);}
.history-item:last-child{border-bottom:none;}
.hi-text{font-size:13px;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;}
.hi-meta{font-size:11px;color:var(--dmr);white-space:nowrap;}
.hi-score{font-size:11px;font-weight:600;white-space:nowrap;}
.history-empty{padding:20px;text-align:center;color:var(--dmr);font-size:12px;font-style:italic;}
.clear-hist{font-size:11px;color:#ef4444;cursor:pointer;background:none;border:none;font-family:"DM Sans",sans-serif;padding:0;}
.clear-hist:hover{opacity:0.7;}
#fileInput{display:none;}
.loader{display:none;width:14px;height:14px;border:2px solid rgba(255,255,255,0.2);border-top-color:#fff;border-radius:50%;animation:spin 0.7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#ef4444;padding:12px;font-size:14px;}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>AI Text Humanizer</h1>
    <p>Paraphrase and Refine</p>
    <div class="pills">
      <span class="pill"><span class="dot dot-a"></span>Developed by: <b><a href="https://github.com/ghulamawais-ai" target="_blank" style="color:#e8eaf2;text-decoration:none;">Ghulam Awais</a></b></span>
      <span class="pill"><span class="dot dot-b"></span>Supervised by: <b>Sir Mohsin Abbas</b></span>
    </div>
  </div>
  <div class="grid">
    <div class="panel">
      <div class="panel-hdr">Original Text</div>
      <textarea id="inputText" placeholder="Yahan apna text paste karein..."></textarea>
      <div class="upload-bar">
        <button class="upload-btn" onclick="document.getElementById('fileInput').click()">📎 PDF / DOCX / TXT Upload</button>
        <span class="upload-hint" id="uploadHint">ya file drag karein</span>
        <span class="upload-progress" id="uploadProgress">Extracting...</span>
        <input type="file" id="fileInput" accept=".pdf,.docx,.txt" onchange="handleFileUpload(this)">
      </div>
      <div class="controls">
        <select id="mode">
          <option>Standard</option><option>Academic</option>
          <option>Creative</option><option>Formal</option><option>Simplified</option>
        </select>
        <select id="intensity">
          <option>Mild</option><option selected>Medium</option><option>Strong</option>
        </select>
        <button class="btn-main" onclick="doHumanize()" id="mainBtn">
          Humanize Text <span class="loader" id="loader"></span>
        </button>
        <button class="btn-sec" onclick="clearAll()">Clear</button>
      </div>
    </div>
    <div class="panel">
      <div class="panel-hdr">Humanized Output</div>
      <div class="output-body" id="outputBody">
        <div class="empty">
          <div style="font-size:32px;opacity:0.25">✦</div>
          <div>Humanized text yahan appear hoga<br>
          <small style="font-size:11px">Golden words = changed &nbsp;|&nbsp; Bar = humanization %</small></div>
        </div>
      </div>
    </div>
  </div>
  <div class="stats" id="statsBar" style="display:none"></div>
  <!-- HISTORY -->
  <div class="history-wrap">
    <div class="history-panel">
      <div class="history-hdr">
        <span>📋 Recent History (Last 10)</span>
        <button class="clear-hist" onclick="clearHistory()">Clear All</button>
      </div>
      <div class="history-list" id="historyList">
        <div class="history-empty">Koi history nahi — pehle text humanize karein</div>
      </div>
    </div>
  </div>

  <div class="ftr">
    <b>AI Text Humanizer</b> &nbsp;·&nbsp;
    Developed by <b><a href="https://github.com/ghulamawais-ai" target="_blank" style="color:#00d4ff;text-decoration:none;">Ghulam Awais</a></b> &nbsp;·&nbsp;
    Supervised by <b>Sir Mohsin Abbas</b>
  </div>
</div>
<script>
async function doHumanize() {
  const text = document.getElementById("inputText").value.trim();
  const mode = document.getElementById("mode").value;
  const intensity = document.getElementById("intensity").value;
  if (!text) { alert("Pehle text darj karein!"); return; }
  const btn = document.getElementById("mainBtn");
  const loader = document.getElementById("loader");
  btn.disabled = true; loader.style.display = "inline-block";
  document.getElementById("outputBody").innerHTML = "<div class='empty'><div>Processing...</div></div>";
  try {
    const res = await fetch("/humanize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, mode, intensity})
    });
    const data = await res.json();
    if (data.error) {
      document.getElementById("outputBody").innerHTML = `<div class='err'>${data.error}</div>`;
    } else {
      document.getElementById("outputBody").innerHTML = data.html;
      // Set plain text safely via JS to avoid HTML injection issues
      const pta = document.getElementById("plainOutput");
      if(pta && data.plain_output) pta.value = data.plain_output;
      const sb = document.getElementById("statsBar");
      sb.textContent = data.stats; sb.style.display = "block";
    }
  } catch(e) {
    document.getElementById("outputBody").innerHTML = `<div class='err'>Error: ${e.message}</div>`;
  }
  btn.disabled = false; loader.style.display = "none";
}
function clearAll() {
  document.getElementById("inputText").value = "";
  document.getElementById("outputBody").innerHTML = "<div class='empty'><div style='font-size:32px;opacity:0.25'>✦</div><div>Humanized text yahan appear hoga</div></div>";
  document.getElementById("statsBar").style.display = "none";
}
document.getElementById("inputText").addEventListener("keydown", function(e) {
  if (e.ctrlKey && e.key === "Enter") doHumanize();
});

// ── File Upload ───────────────────────────────────────────────────
async function handleFileUpload(input) {
  const file = input.files[0];
  if (!file) return;
  const hint = document.getElementById("uploadHint");
  const prog = document.getElementById("uploadProgress");
  hint.style.display = "none";
  prog.style.display = "inline";
  prog.textContent = "Reading file...";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/extract-text", { method: "POST", body: formData });
    const data = await res.json();
    if (data.error) {
      prog.textContent = data.error;
      prog.style.color = "#ef4444";
    } else {
      document.getElementById("inputText").value = data.text;
      prog.textContent = "✓ " + file.name + " loaded!";
      prog.style.color = "#10b981";
    }
  } catch(e) {
    prog.textContent = "Error: " + e.message;
    prog.style.color = "#ef4444";
  }
  setTimeout(() => {
    prog.style.display = "none";
    hint.style.display = "inline";
    hint.textContent = file.name;
  }, 3000);
}

// Drag & drop support
const inputPanel = document.querySelector(".panel");
if (inputPanel) {
  inputPanel.addEventListener("dragover", e => { e.preventDefault(); inputPanel.style.borderColor = "var(--ac)"; });
  inputPanel.addEventListener("dragleave", () => { inputPanel.style.borderColor = ""; });
  inputPanel.addEventListener("drop", e => {
    e.preventDefault();
    inputPanel.style.borderColor = "";
    const file = e.dataTransfer.files[0];
    if (file) {
      const fi = document.getElementById("fileInput");
      const dt = new DataTransfer();
      dt.items.add(file);
      fi.files = dt.files;
      handleFileUpload(fi);
    }
  });
}

// ── History ───────────────────────────────────────────────────────
function loadHistory() {
  try { return JSON.parse(localStorage.getItem("aiHumanHistory") || "[]"); }
  catch { return []; }
}
function saveHistory(arr) {
  localStorage.setItem("aiHumanHistory", JSON.stringify(arr.slice(0, 10)));
}
function addToHistory(orig, hpct, mode, intensity) {
  const h = loadHistory();
  h.unshift({
    text: orig.slice(0, 100),
    hpct: hpct,
    mode: mode,
    intensity: intensity,
    time: new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})
  });
  saveHistory(h);
  renderHistory();
}
function renderHistory() {
  const h = loadHistory();
  const el = document.getElementById("historyList");
  if (!el) return;
  if (!h.length) {
    el.innerHTML = "<div class='history-empty'>Koi history nahi — pehle text humanize karein</div>";
    return;
  }
  el.innerHTML = h.map((item, i) => {
    const scoreColor = item.hpct >= 75 ? "#10b981" : item.hpct >= 50 ? "#00d4ff" : "#fbbf24";
    return `<div class="history-item" onclick="loadFromHistory(${i})">
      <div class="hi-text">${item.text.replace(/</g,"&lt;")}...</div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px">
        <span class="hi-score" style="color:${scoreColor}">${item.hpct}%</span>
        <span class="hi-meta">${item.mode} · ${item.time}</span>
      </div>
    </div>`;
  }).join("");
}
function loadFromHistory(i) {
  const h = loadHistory();
  if (h[i]) {
    document.getElementById("inputText").value = h[i].text;
    document.getElementById("mode").value = h[i].mode;
  }
}
function clearHistory() {
  if (confirm("Saari history delete karein?")) {
    localStorage.removeItem("aiHumanHistory");
    renderHistory();
  }
}

// ── Update doHumanize to save history ────────────────────────────
const _origDoHumanize = doHumanize;
async function doHumanize() {
  const text = document.getElementById("inputText").value.trim();
  const mode = document.getElementById("mode").value;
  const intensity = document.getElementById("intensity").value;
  if (!text) { alert("Pehle text darj karein!"); return; }
  const btn = document.getElementById("mainBtn");
  const loader = document.getElementById("loader");
  btn.disabled = true; loader.style.display = "inline-block";
  document.getElementById("outputBody").innerHTML = "<div class=\'empty\'><div>Processing...</div></div>";
  try {
    const res = await fetch("/humanize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, mode, intensity})
    });
    const data = await res.json();
    if (data.error) {
      document.getElementById("outputBody").innerHTML = `<div class='err'>${data.error}</div>`;
    } else {
      document.getElementById("outputBody").innerHTML = data.html;
      const pta = document.getElementById("plainOutput");
      if (pta && data.plain_output) pta.value = data.plain_output;
      const sb = document.getElementById("statsBar");
      sb.textContent = data.stats; sb.style.display = "block";
      addToHistory(text, data.hpct || 0, mode, intensity);
    }
  } catch(e) {
    document.getElementById("outputBody").innerHTML = `<div class='err'>Error: ${e.message}</div>`;
  }
  btn.disabled = false; loader.style.display = "none";
}

renderHistory();

// ── Synonym popup ────────────────────────────────────────────────

let activeSpan=null;
const popup=document.createElement('div');
popup.id='synPopup';popup.className='syn-popup';
document.body.appendChild(popup);

// Free Dictionary API - real synonyms for ANY word
async function fetchSynonyms(word) {
  try {
    const res = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/en/${word}`);
    if (!res.ok) return null;
    const data = await res.json();
    const syns = [];
    for (const entry of data) {
      for (const meaning of entry.meanings || []) {
        for (const def of meaning.definitions || []) {
          for (const s of def.synonyms || []) {
            if (!syns.includes(s) && s !== word) syns.push(s);
            if (syns.length >= 4) return syns;
          }
        }
        for (const s of meaning.synonyms || []) {
          if (!syns.includes(s) && s !== word) syns.push(s);
          if (syns.length >= 4) return syns;
        }
      }
    }
    return syns.length > 0 ? syns.slice(0,4) : null;
  } catch { return null; }
}

// Fallback for very common words
const FALLBACK = {
  // Business & Organization
  company:["firm","organization","enterprise","corporation"],
  business:["venture","enterprise","firm","operation"],
  firm:["company","organization","agency","establishment"],
  organization:["institution","body","entity","association"],
  corporation:["company","conglomerate","enterprise","group"],
  industry:["sector","field","domain","market"],
  market:["sector","arena","space","landscape"],
  team:["group","crew","unit","squad"],
  staff:["workforce","personnel","employees","crew"],
  manager:["director","supervisor","leader","head"],
  leader:["head","chief","director","executive"],
  strategy:["approach","plan","method","framework"],
  plan:["strategy","approach","blueprint","roadmap"],
  goal:["objective","target","aim","purpose"],
  project:["initiative","endeavor","task","assignment"],
  // Results & Progress
  result:["outcome","achievement","output","impact"],
  growth:["expansion","development","progress","advancement"],
  success:["achievement","accomplishment","triumph","win"],
  failure:["setback","shortcoming","breakdown","collapse"],
  progress:["advancement","development","improvement","gain"],
  improvement:["enhancement","upgrade","advancement","boost"],
  achievement:["accomplishment","attainment","success","feat"],
  performance:["execution","output","results","delivery"],
  impact:["effect","influence","consequence","outcome"],
  value:["worth","benefit","importance","merit"],
  // Actions
  make:["create","build","produce","generate"],
  get:["obtain","acquire","gain","retrieve"],
  show:["display","reveal","present","demonstrate"],
  use:["apply","employ","leverage","utilize"],
  keep:["maintain","retain","preserve","sustain"],
  give:["provide","offer","supply","deliver"],
  help:["assist","support","aid","facilitate"],
  change:["alter","modify","adjust","transform"],
  work:["function","operate","perform","execute"],
  think:["believe","consider","assume","reckon"],
  know:["understand","recognize","realize","grasp"],
  say:["state","mention","express","note"],
  need:["require","demand","necessitate","seek"],
  find:["discover","identify","locate","uncover"],
  take:["adopt","assume","accept","embrace"],
  put:["place","position","set","insert"],
  move:["shift","transfer","relocate","transition"],
  start:["begin","initiate","launch","commence"],
  stop:["halt","cease","end","discontinue"],
  build:["construct","develop","create","establish"],
  create:["develop","produce","generate","form"],
  develop:["build","establish","advance","cultivate"],
  improve:["enhance","boost","strengthen","upgrade"],
  increase:["rise","grow","expand","escalate"],
  reduce:["decrease","lower","cut","minimize"],
  achieve:["accomplish","attain","reach","realize"],
  support:["back","assist","aid","reinforce"],
  provide:["offer","deliver","supply","furnish"],
  ensure:["guarantee","confirm","secure","verify"],
  allow:["permit","enable","authorize","facilitate"],
  require:["demand","necessitate","mandate","call for"],
  consider:["examine","evaluate","assess","reflect on"],
  implement:["apply","execute","deploy","carry out"],
  maintain:["preserve","sustain","uphold","continue"],
  // Descriptive
  good:["great","excellent","solid","fine"],
  bad:["poor","weak","flawed","lacking"],
  big:["large","substantial","vast","sizable"],
  small:["tiny","minor","compact","limited"],
  important:["crucial","key","significant","vital"],
  new:["fresh","recent","novel","updated"],
  old:["prior","previous","former","earlier"],
  high:["elevated","increased","greater","superior"],
  low:["reduced","minimal","limited","decreased"],
  fast:["quick","rapid","swift","efficient"],
  slow:["gradual","steady","measured","deliberate"],
  clear:["evident","obvious","plain","apparent"],
  hard:["difficult","challenging","complex","tough"],
  easy:["simple","straightforward","effortless","basic"],
  long:["extended","lengthy","prolonged","substantial"],
  short:["brief","concise","compact","limited"],
  strong:["powerful","robust","solid","effective"],
  weak:["feeble","fragile","limited","poor"],
  real:["genuine","actual","authentic","true"],
  different:["distinct","varied","diverse","unique"],
  similar:["alike","comparable","equivalent","matching"],
  common:["typical","standard","widespread","general"],
  special:["unique","distinctive","particular","exceptional"],
  major:["significant","primary","chief","principal"],
  minor:["small","slight","limited","secondary"],
  // People & Society
  people:["individuals","persons","folks","members"],
  person:["individual","someone","one","party"],
  problem:["issue","challenge","obstacle","difficulty"],
  solution:["answer","resolution","fix","remedy"],
  idea:["concept","notion","thought","proposal"],
  question:["inquiry","query","issue","matter"],
  answer:["response","reply","solution","explanation"],
  reason:["cause","basis","rationale","explanation"],
  way:["method","approach","means","manner"],
  time:["period","moment","phase","duration"],
  place:["location","area","spot","site"],
  part:["section","component","element","portion"],
  point:["aspect","detail","matter","issue"],
  fact:["reality","truth","detail","information"],
  // Technology & Academic
  data:["information","insights","metrics","figures"],
  technology:["tech","innovation","tools","systems"],
  system:["framework","structure","platform","mechanism"],
  process:["procedure","method","approach","workflow"],
  platform:["system","tool","framework","solution"],
  feature:["function","capability","option","element"],
  model:["framework","structure","approach","method"],
  information:["data","details","knowledge","insight"],
  research:["study","investigation","analysis","inquiry"],
  analysis:["examination","assessment","evaluation","study"],
  approach:["method","strategy","technique","way"],
  method:["approach","technique","procedure","means"],
};

document.addEventListener('click', async function(e){
  if(e.target.classList.contains('cw')){
    activeSpan = e.target;
    const word = e.target.getAttribute('data-word') || '';
    
    // Show loading state
    const r = e.target.getBoundingClientRect();
    popup.style.left = r.left + 'px';
    popup.style.top = (r.bottom + 6) + 'px';
    popup.innerHTML = '<div class="syn-item" style="color:#8892a4;cursor:default">Loading...</div>';
    popup.classList.add('show');
    e.stopPropagation();

    // Try API first, then fallback
    let syns = await fetchSynonyms(word);
    if (!syns || syns.length === 0) {
      syns = FALLBACK[word] || FALLBACK[word.replace(/s$/,'')] || ['alternative','substitute','replacement','variant'];
    }

    popup.innerHTML = syns.slice(0,4).map(s => `<div class="syn-item">${s}</div>`).join('');
    popup.querySelectorAll('.syn-item').forEach(item => {
      item.onclick = function(){
        if(activeSpan){
          activeSpan.textContent = item.textContent;
          const ta = document.querySelector('.plain-ta');
          if(ta){const ot=document.querySelector('.out-text');if(ot)ta.value=ot.innerText;}
        }
        popup.classList.remove('show');
      };
    });
  } else {
    popup.classList.remove('show');
  }
});

// ── Copy to clipboard ────────────────────────────────────────────
function copyOutput(){
  const ta=document.querySelector('.plain-ta');
  if(!ta)return;
  navigator.clipboard.writeText(ta.value).then(()=>{
    const btn=document.querySelector('.copy-btn');
    const orig=btn.innerHTML;
    btn.innerHTML='✓ Copied!';btn.classList.add('copied');
    setTimeout(()=>{btn.innerHTML=orig;btn.classList.remove('copied');},2000);
  }).catch(()=>{ta.select();document.execCommand('copy');});
}
</script>
</body>
</html>'''

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

@app.route("/extract-text", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"})
    file = request.files["file"]
    filename = file.filename.lower()
    try:
        if filename.endswith(".txt"):
            text = file.read().decode("utf-8", errors="ignore")
            return jsonify({"text": text.strip()})
        elif filename.endswith(".pdf"):
            # Use Groq vision or simple byte extraction
            content = file.read()
            # Simple PDF text extraction - find text between stream markers
            import re as re2
            text_parts = re2.findall(rb'BT(.*?)ET', content, re2.DOTALL)
            extracted = []
            for part in text_parts:
                chars = re2.findall(rb'\(([^)]+)\)', part)
                for ch in chars:
                    try:
                        extracted.append(ch.decode('latin-1'))
                    except:
                        pass
            text = ' '.join(extracted).strip()
            if len(text) < 50:
                return jsonify({"error": "PDF text extract nahi hua. Text copy karke paste karein."})
            return jsonify({"text": text})
        elif filename.endswith(".docx"):
            content = file.read()
            import zipfile, io
            import re as re2
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                with z.open("word/document.xml") as xml:
                    xml_content = xml.read().decode("utf-8")
            text = re2.sub(r'<[^>]+>', ' ', xml_content)
            text = re2.sub(r'\s+', ' ', text).strip()
            return jsonify({"text": text})
        else:
            return jsonify({"error": "Sirf PDF, DOCX, ya TXT files support hain."})
    except Exception as e:
        return jsonify({"error": f"File read error: {str(e)}"})

@app.route("/humanize", methods=["POST"])
def humanize_api():
    data      = request.json
    text      = (data.get("text") or "").strip()
    mode      = data.get("mode", "Standard")
    intensity = data.get("intensity", "Medium")

    if not GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY set nahi. HuggingFace Settings > Secrets mein add karein."})
    if not text:
        return jsonify({"error": "Koi text nahi diya."})
    iw = len(text.split())
    if iw < 3:
        return jsonify({"error": "Kam az kam 3 words chahiye."})

    int_note = {
        "Mild":   "MINIMAL changes. Preserve most original phrasing. Nearly identical length.",
        "Medium": "MODERATE changes. Restructure sentences. Match word count within 10%.",
        "Strong": "AGGRESSIVE rewrite. Change most vocabulary. Stay within 15% of input length."
    }.get(intensity, "")

    lo, hi = max(1, int(iw*0.88)), int(iw*1.12)
    user_prompt = (SYSTEM_BASE
        + f"\n\nWORD COUNT: Input={iw}. Output MUST be {lo}-{hi} words."
        + f"\nINTENSITY: {int_note}"
        + f"\nMODE: {MODE_PROMPTS.get(mode, MODE_PROMPTS['Standard'])}"
        + f"\n\nRewrite:\n\n{text}")

    try:
        resp = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0.7,
                "max_tokens": 2048
            },
            timeout=30
        )
        resp.raise_for_status()
        output = resp.json()["choices"][0]["message"]["content"].strip()
        for pfx in ["Here is","Here's","Sure,","Rewritten:","Below is"]:
            if output.lower().startswith(pfx.lower()):
                lines = output.split("\n", 1)
                if len(lines) > 1: output = lines[1].strip()
                break
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"})

    ow   = len(output.split())
    chg  = count_changed(text, output)
    cpct = round(chg / max(ow,1) * 100)
    hpct = human_pct(text, output)
    hl      = highlight_html(text, output)

    color = "#10b981" if hpct>=75 else "#00d4ff" if hpct>=50 else "#fbbf24" if hpct>=30 else "#ef4444"
    label = "Excellent" if hpct>=75 else "Good" if hpct>=50 else "Moderate" if hpct>=30 else "Low"
    emoji = "🟢" if hpct>=75 else "🔵" if hpct>=50 else "🟡" if hpct>=30 else "🔴"

    diff = ow-iw; dpct = round(abs(diff)/max(iw,1)*100)
    if dpct<=10:
        wc=f'<div class="wc-ok">Word count balanced — Input: <b>{iw}</b> · Output: <b>{ow}</b> words (diff: {diff:+d})</div>'
    elif diff>0:
        wc=f'<div class="wc-warn">Output <b>{diff} words longer</b> ({iw}→{ow}, +{dpct}%). Try Mild intensity.</div>'
    else:
        wc=f'<div class="wc-short">Output <b>{abs(diff)} words shorter</b> ({iw}→{ow}, -{dpct}%).</div>'

    html = f"""
<div class="prog-box">
  <div class="prog-hdr">
    <span class="prog-label">Humanization Score</span>
    <span class="prog-val" style="color:{color}">{emoji} {hpct}% — {label}</span>
  </div>
  <div class="prog-track"><div class="prog-fill" style="width:{hpct}%;background:linear-gradient(90deg,{color}55,{color})"></div></div>
  <div class="prog-scale"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
</div>
{wc}
<div class="prog-scale"><span>Safe</span><span>25%</span><span>50%</span><span>75%</span><span>Detected</span></div>
</div>
<div class="chips">
  <span class="chip ci">Input: <b>{iw}</b> words</span>
  <span class="chip co">Output: <b>{ow}</b> words</span>
  <span class="chip cc">Changed: <b>{chg}</b> ({cpct}%)</span>
  <span class="chip cm">{mode} · {intensity}</span>
</div>
<div class="legend"><span class="lgnd-sw"></span> Golden highlighted = changed words</div>
<div class="out-box"><div class="out-text">{hl}</div></div>
<div class="copy-row">
  <span class="plain-label" style="font-family:'Syne',sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#8892a4">Plain Text</span>
  <button class="copy-btn" onclick="copyOutput()">⎘ Copy to Clipboard</button>
</div>
<textarea class="plain-ta" id="plainOutput" onclick="this.select()"></textarea>"""

    stats = f"Input: {iw}w → Output: {ow}w  |  Changed: {chg} ({cpct}%)  |  Humanized: {hpct}%  |  {mode} | {intensity}"
    return jsonify({"html": html, "stats": stats, "plain_output": output})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
