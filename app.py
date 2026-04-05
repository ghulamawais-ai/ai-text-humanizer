from flask import Flask, request, jsonify, render_template_string
import os, re, requests as req, json

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
9. HUMAN LANGUAGE RULES:
   - NEVER use "I wish you are doing well" — use "Hope you are doing well"
   - NEVER use "promptly" — use "whenever you have a moment"
   - NEVER use overly formal words like "aforementioned", "henceforth", "utilize"
   - Write like a confident educated human, not a corporate robot
   - Use contractions naturally (it's, you'll, we've, don't)"""

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

def get_readability(text):
    words = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences: return "N/A", "#8892a4"
    avg_words = len(words) / len(sentences)
    long_words = sum(1 for w in words if len(re.sub(r'[^a-zA-Z]','',w)) > 6)
    long_ratio = long_words / max(len(words), 1)
    score = avg_words * 0.5 + long_ratio * 20
    if score < 8:   return "Basic", "#10b981"
    elif score < 12: return "Intermediate", "#00d4ff"
    elif score < 16: return "Advanced", "#fbbf24"
    else:            return "Expert", "#7c3aed"

def get_tone(text):
    t = text.lower()
    formal_w   = ["therefore","however","furthermore","consequently","regarding","pursuant","hereby","henceforth"]
    friendly_w = ["thanks","great","awesome","sure","happy","glad","appreciate","wonderful","excited"]
    urgent_w   = ["immediately","urgent","asap","critical","important","deadline","must","required"]
    f = sum(1 for w in formal_w if w in t)
    fr= sum(1 for w in friendly_w if w in t)
    u = sum(1 for w in urgent_w if w in t)
    if u >= 2:        return "Urgent", "#ef4444"
    elif f > fr:      return "Professional", "#00d4ff"
    elif fr > f:      return "Friendly", "#10b981"
    else:             return "Neutral", "#8892a4"

def get_ai_prob(orig, rew):
    os_ = {cw(w) for w in orig.split() if cw(w) and cw(w) not in STOP}
    om  = [cw(w) for w in rew.split() if cw(w) and cw(w) not in STOP]
    if not om: return 50
    changed_ratio = sum(1 for w in om if w not in os_) / len(om)
    sentences = re.split(r'[.!?]+', rew)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) > 1:
        lengths = [len(s.split()) for s in sentences]
        avg = sum(lengths)/len(lengths)
        variance = sum((l-avg)**2 for l in lengths)/len(lengths)
    else:
        variance = 0
    ai_prob = max(5, min(95, int(100 - (changed_ratio * 60) - min(variance * 0.5, 20))))
    return ai_prob

def highlight_html(orig, rew):
    os_ = {cw(w) for w in orig.split()}
    parts = []
    for t in re.split(r'(\s+|\n+)', rew):
        if re.match(r'^[\s\n]+$', t):
            parts.append(t.replace('\n', '<br>'))
            continue
        c = cw(t)
        if c and c not in STOP and c not in os_:
            parts.append(f'<span class="cw" data-word="{c}">{t}</span>')
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
.wrap{max-width:1400px;margin:0 auto;position:relative;z-index:1;}
.hdr{background:linear-gradient(135deg,rgba(0,212,255,0.08),rgba(124,58,237,0.08));border:1px solid var(--br2);border-radius:18px;padding:22px 28px;margin-bottom:16px;position:relative;overflow:hidden;}
.hdr::before{content:"";position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--ac),var(--ac2),transparent);}
.hdr h1{font-family:"Syne",sans-serif;font-size:26px;font-weight:800;background:linear-gradient(135deg,var(--ac),var(--ac2) 50%,var(--ac3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:5px;}
.hdr p{color:var(--dm);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:12px;}
.pills{display:flex;gap:8px;flex-wrap:wrap;}
.pill{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.05);border:1px solid var(--br2);border-radius:100px;padding:4px 12px;font-size:12px;color:var(--dm);}
.pill b{color:var(--tx);}
.pill a{color:var(--tx);text-decoration:none;}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
.dot-a{background:var(--ac);box-shadow:0 0 6px var(--ac);}
.dot-b{background:var(--ac2);box-shadow:0 0 6px var(--ac2);}
.main-layout{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:14px;}
@media(max-width:900px){.main-layout{grid-template-columns:1fr;}}
.panel{background:var(--sf);border:1px solid var(--br);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;}
.panel-hdr{padding:12px 16px;border-bottom:1px solid var(--br);background:rgba(255,255,255,0.02);font-family:"Syne",sans-serif;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);font-weight:700;display:flex;align-items:center;justify-content:space-between;}
textarea{flex:1;min-height:280px;padding:16px;background:transparent;border:none;outline:none;color:var(--tx);font-family:"DM Sans",sans-serif;font-size:15px;line-height:1.75;resize:none;font-weight:300;}
textarea::placeholder{color:var(--dmr);}
.upload-bar{padding:10px 16px;border-top:1px solid var(--br);display:flex;gap:8px;align-items:center;}
.upload-btn{padding:6px 14px;border-radius:8px;border:1px dashed var(--br2);background:transparent;color:var(--dm);font-size:12px;cursor:pointer;transition:all 0.2s;font-family:"DM Sans",sans-serif;}
.upload-btn:hover{border-color:var(--ac);color:var(--ac);}
.upload-hint{font-size:11px;color:var(--dmr);}
.controls{padding:12px 16px;border-top:1px solid var(--br);display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
select{background:rgba(255,255,255,0.05);border:1px solid var(--br2);border-radius:8px;color:var(--tx);padding:8px 12px;font-family:"DM Sans",sans-serif;font-size:13px;cursor:pointer;}
.btn-main{padding:10px 24px;border-radius:10px;border:none;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;font-family:"Syne",sans-serif;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 16px rgba(0,212,255,0.25);transition:all 0.2s;display:flex;align-items:center;gap:8px;}
.btn-main:hover{transform:translateY(-1px);}
.btn-main:disabled{opacity:0.5;cursor:not-allowed;transform:none;}
.btn-sec{padding:10px 18px;border-radius:10px;border:1px solid var(--br2);background:var(--sf);color:var(--tx);font-family:"DM Sans",sans-serif;font-size:13px;cursor:pointer;}
.output-body{flex:1;min-height:280px;padding:16px;overflow-y:auto;}
.empty{color:var(--dmr);font-style:italic;display:flex;align-items:center;justify-content:center;height:250px;flex-direction:column;gap:10px;text-align:center;font-size:14px;}
/* Metrics Grid */
.metrics-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;}
.metric-card{background:rgba(255,255,255,0.03);border:1px solid var(--br2);border-radius:10px;padding:12px 14px;}
.metric-title{font-family:"Syne",sans-serif;font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:var(--dm);margin-bottom:8px;}
.metric-val{font-weight:700;font-size:15px;margin-bottom:2px;}
.metric-sub{font-size:11px;color:var(--dm);}
/* Progress bars */
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
.out-box{background:rgba(255,255,255,0.02);border:1px solid var(--br);border-radius:11px;padding:15px 17px;margin-bottom:10px;}
.out-text{font-size:15px;line-height:1.8;font-weight:300;color:var(--tx);}
.cw{background:rgba(251,191,36,0.15);color:#fbbf24;border-bottom:1.5px solid rgba(251,191,36,0.5);border-radius:4px;padding:1px 4px;font-weight:500;cursor:pointer;position:relative;}
.cw:hover{background:rgba(251,191,36,0.28);}
/* Synonym dropdown */
.syn-popup{position:absolute;top:100%;left:0;background:#1a1f35;border:1px solid var(--br2);border-radius:8px;padding:4px;z-index:100;min-width:120px;box-shadow:0 8px 24px rgba(0,0,0,0.4);display:none;}
.syn-popup.show{display:block;}
.syn-item{padding:6px 10px;border-radius:6px;font-size:13px;color:var(--tx);cursor:pointer;white-space:nowrap;}
.syn-item:hover{background:rgba(0,212,255,0.1);color:var(--ac);}
/* Copy button */
.copy-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
.plain-label{font-family:"Syne",sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);}
.copy-btn{padding:5px 12px;border-radius:7px;border:1px solid var(--br2);background:var(--sf);color:var(--ac3);font-size:12px;cursor:pointer;display:flex;align-items:center;gap:5px;font-family:"DM Sans",sans-serif;transition:all 0.2s;}
.copy-btn:hover{background:rgba(16,185,129,0.1);border-color:rgba(16,185,129,0.3);}
.copy-btn.copied{color:#10b981;border-color:rgba(16,185,129,0.4);}
.plain-ta{min-height:80px;background:rgba(255,255,255,0.02);border:1px solid var(--br);border-radius:10px;padding:12px;font-size:14px;color:var(--tx);width:100%;resize:vertical;font-family:"DM Sans",sans-serif;outline:none;}
/* History sidebar */
.history-panel{background:var(--sf);border:1px solid var(--br);border-radius:16px;padding:0;overflow:hidden;}
.history-hdr{padding:12px 16px;border-bottom:1px solid var(--br);font-family:"Syne",sans-serif;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dm);font-weight:700;display:flex;justify-content:space-between;align-items:center;}
.history-list{max-height:400px;overflow-y:auto;}
.history-item{padding:10px 14px;border-bottom:1px solid var(--br);cursor:pointer;transition:background 0.2s;}
.history-item:hover{background:rgba(255,255,255,0.04);}
.history-item:last-child{border-bottom:none;}
.hi-text{font-size:12px;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px;}
.hi-meta{font-size:11px;color:var(--dmr);}
.history-empty{padding:20px;text-align:center;color:var(--dmr);font-size:12px;font-style:italic;}
.clear-hist{font-size:11px;color:#ef4444;cursor:pointer;background:none;border:none;font-family:"DM Sans",sans-serif;}
.legend{font-size:12px;color:var(--dm);margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.lgnd-sw{width:12px;height:12px;background:rgba(251,191,36,0.2);border:1px solid rgba(251,191,36,0.4);border-radius:3px;display:inline-block;flex-shrink:0;}
.stats{background:rgba(0,212,255,0.04);border:1px solid rgba(0,212,255,0.1);border-radius:9px;padding:8px 14px;font-size:12px;color:var(--dm);margin-bottom:14px;}
.ftr{text-align:center;padding:12px 0 0;color:var(--dmr);font-size:12px;border-top:1px solid var(--br);line-height:1.8;}
.ftr b{color:var(--dm);}
.ftr a{color:var(--ac);text-decoration:none;}
.loader{display:none;width:14px;height:14px;border:2px solid rgba(255,255,255,0.2);border-top-color:#fff;border-radius:50%;animation:spin 0.7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#ef4444;padding:12px;font-size:14px;}
#fileInput{display:none;}
</style>
</head>
<body>
<div class="wrap">

  <!-- HEADER -->
  <div class="hdr">
    <h1>AI Text Humanizer</h1>
    <p>Paraphrase and Refine</p>
    <div class="pills">
      <span class="pill"><span class="dot dot-a"></span>Developed by: <b><a href="https://github.com/ghulamawais-ai" target="_blank">Ghulam Awais</a></b></span>
      <span class="pill"><span class="dot dot-b"></span>Supervised by: <b>Sir Mohsin Abbas</b></span>
    </div>
  </div>

  <!-- MAIN LAYOUT -->
  <div class="main-layout">

    <!-- LEFT: INPUT -->
    <div class="panel">
      <div class="panel-hdr">Original Text</div>
      <textarea id="inputText" placeholder="Yahan apna text paste karein..."></textarea>
      <div class="upload-bar">
        <button class="upload-btn" onclick="document.getElementById('fileInput').click()">📎 Upload PDF / DOCX</button>
        <span class="upload-hint" id="uploadHint">ya file drag karein</span>
        <input type="file" id="fileInput" accept=".txt,.pdf,.docx" onchange="handleFile(this)">
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

    <!-- RIGHT: OUTPUT -->
    <div class="panel">
      <div class="panel-hdr">
        Humanized Output
        <span style="font-size:11px;color:var(--dmr);font-weight:400;letter-spacing:0">Click highlighted word for synonyms</span>
      </div>
      <div class="output-body" id="outputBody">
        <div class="empty">
          <div style="font-size:32px;opacity:0.25">✦</div>
          <div>Humanized text yahan appear hoga<br>
          <small style="font-size:11px">Golden = changed · Bar = humanization % · Click word = synonyms</small></div>
        </div>
      </div>
    </div>

  </div>

  <!-- STATS BAR -->
  <div class="stats" id="statsBar" style="display:none"></div>

  <!-- HISTORY -->
  <div class="history-panel" style="margin-bottom:14px">
    <div class="history-hdr">
      Recent History (Last 10)
      <button class="clear-hist" onclick="clearHistory()">Clear All</button>
    </div>
    <div class="history-list" id="historyList">
      <div class="history-empty">Koi history nahi — pehle text humanize karein</div>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="ftr">
    <b>AI Text Humanizer</b> &nbsp;·&nbsp;
    Developed by <b><a href="https://github.com/ghulamawais-ai" target="_blank">Ghulam Awais</a></b> &nbsp;·&nbsp;
    Supervised by <b>Sir Mohsin Abbas</b> &nbsp;·&nbsp;
    <a href="https://github.com/ghulamawais-ai/ai-text-humanizer" target="_blank">GitHub</a>
  </div>

</div>

<!-- SYNONYM POPUP -->
<div id="synPopup" class="syn-popup">
  <div class="syn-item" id="syn1"></div>
  <div class="syn-item" id="syn2"></div>
  <div class="syn-item" id="syn3"></div>
  <div class="syn-item" id="syn4"></div>
</div>

<script>
// ── History ──────────────────────────────────────────────────────
function loadHistory() {
  try { return JSON.parse(localStorage.getItem('hh') || '[]'); } catch { return []; }
}
function saveHistory(h) {
  localStorage.setItem('hh', JSON.stringify(h.slice(0, 10)));
}
function addHistory(orig, out, hpct, mode) {
  const h = loadHistory();
  h.unshift({ orig: orig.slice(0,80), out: out.slice(0,80), hpct, mode, time: new Date().toLocaleTimeString() });
  saveHistory(h);
  renderHistory();
}
function renderHistory() {
  const h = loadHistory();
  const el = document.getElementById('historyList');
  if (!h.length) { el.innerHTML = '<div class="history-empty">Koi history nahi — pehle text humanize karein</div>'; return; }
  el.innerHTML = h.map((item,i) => `
    <div class="history-item" onclick="loadHistoryItem(${i})">
      <div class="hi-text">${item.orig}...</div>
      <div class="hi-meta">${item.time} &nbsp;·&nbsp; ${item.mode} &nbsp;·&nbsp; ${item.hpct}% humanized</div>
    </div>`).join('');
}
function loadHistoryItem(i) {
  const h = loadHistory();
  if (h[i]) document.getElementById('inputText').value = h[i].orig;
}
function clearHistory() {
  localStorage.removeItem('hh');
  renderHistory();
}
renderHistory();

// ── File Upload ───────────────────────────────────────────────────
function handleFile(input) {
  const file = input.files[0];
  if (!file) return;
  document.getElementById('uploadHint').textContent = file.name;
  const reader = new FileReader();
  reader.onload = function(e) {
    const text = e.target.result;
    document.getElementById('inputText').value = text.replace(/[^\x20-\x7E\n]/g, ' ').trim();
  };
  reader.readAsText(file);
}

// ── Synonym Click ─────────────────────────────────────────────────
const SYNONYMS = {
  good:["excellent","great","fine","solid"],
  bad:["poor","weak","flawed","inferior"],
  big:["large","vast","substantial","sizable"],
  small:["tiny","minor","compact","limited"],
  important:["crucial","key","significant","vital"],
  show:["display","reveal","present","demonstrate"],
  use:["utilize","apply","employ","leverage"],
  make:["create","produce","build","generate"],
  get:["obtain","acquire","gain","retrieve"],
  help:["assist","support","aid","facilitate"],
  need:["require","demand","necessitate","seek"],
  think:["believe","consider","assume","reckon"],
  know:["understand","recognize","realize","grasp"],
  say:["state","mention","express","indicate"],
  work:["function","operate","perform","execute"],
  change:["alter","modify","adjust","transform"],
  keep:["maintain","retain","preserve","sustain"],
  give:["provide","offer","supply","deliver"],
  take:["obtain","acquire","seize","adopt"],
  see:["observe","notice","detect","identify"]
};

document.addEventListener('click', function(e) {
  const popup = document.getElementById('synPopup');
  if (!e.target.classList.contains('cw')) { popup.classList.remove('show'); return; }
  const word = e.target.getAttribute('data-word');
  const syns = SYNONYMS[word] || generateSynonyms(word);
  ['syn1','syn2','syn3','syn4'].forEach((id,i) => {
    const el = document.getElementById(id);
    if (syns[i]) {
      el.textContent = syns[i];
      el.style.display = 'block';
      el.onclick = function() {
        e.target.textContent = syns[i];
        popup.classList.remove('show');
        updatePlainText();
      };
    } else { el.style.display = 'none'; }
  });
  const rect = e.target.getBoundingClientRect();
  popup.style.left = (rect.left + window.scrollX) + 'px';
  popup.style.top  = (rect.bottom + window.scrollY + 4) + 'px';
  popup.classList.add('show');
});

function generateSynonyms(word) {
  const suffixes = ['ly','ed','ing','tion','ment','ness','er','est'];
  for (const sfx of suffixes) {
    if (word.endsWith(sfx)) {
      const base = word.slice(0, -sfx.length);
      if (SYNONYMS[base]) return SYNONYMS[base].map(s => s + sfx);
    }
  }
  return ['alternative','substitute','replacement','variant'];
}

function updatePlainText() {
  const outBox = document.getElementById('outputBody');
  const plainTa = outBox.querySelector('.plain-ta');
  if (plainTa) {
    const outText = outBox.querySelector('.out-text');
    if (outText) plainTa.value = outText.innerText;
  }
}

// ── Copy to Clipboard ─────────────────────────────────────────────
function copyOutput() {
  const ta = document.querySelector('.plain-ta');
  if (!ta) return;
  navigator.clipboard.writeText(ta.value).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.classList.add('copied');
    btn.innerHTML = '✓ Copied!';
    setTimeout(() => { btn.classList.remove('copied'); btn.innerHTML = '⎘ Copy'; }, 2000);
  }).catch(() => { ta.select(); document.execCommand('copy'); });
}

// ── Main Humanize ─────────────────────────────────────────────────
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
      const sb = document.getElementById("statsBar");
      sb.textContent = data.stats; sb.style.display = "block";
      addHistory(text, data.plain_output || '', data.hpct || 0, mode);
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
  document.getElementById("uploadHint").textContent = "ya file drag karein";
}

document.getElementById("inputText").addEventListener("keydown", function(e) {
  if (e.ctrlKey && e.key === "Enter") doHumanize();
});
</script>
</body>
</html>'''

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

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
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":user_prompt}],"temperature":0.7,"max_tokens":2048},
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
    hl   = highlight_html(text, output)

    # Metrics
    read_level, read_color = get_readability(output)
    tone_label, tone_color = get_tone(output)
    ai_prob = get_ai_prob(text, output)
    ai_safe = 100 - ai_prob
    ai_color = "#10b981" if ai_safe >= 70 else "#fbbf24" if ai_safe >= 40 else "#ef4444"
    ai_label = "Low Risk" if ai_safe >= 70 else "Medium Risk" if ai_safe >= 40 else "High Risk"

    # Humanization bar
    h_color = "#10b981" if hpct>=75 else "#00d4ff" if hpct>=50 else "#fbbf24" if hpct>=30 else "#ef4444"
    h_label = "Excellent" if hpct>=75 else "Good" if hpct>=50 else "Moderate" if hpct>=30 else "Low"
    h_emoji = "🟢" if hpct>=75 else "🔵" if hpct>=50 else "🟡" if hpct>=30 else "🔴"

    diff = ow-iw; dpct = round(abs(diff)/max(iw,1)*100)
    if dpct<=10:
        wc=f'<div class="wc-ok">✅ Word count balanced — Input: <b>{iw}</b> · Output: <b>{ow}</b> words (diff: {diff:+d})</div>'
    elif diff>0:
        wc=f'<div class="wc-warn">⚠️ Output <b>{diff} words longer</b> ({iw}→{ow}, +{dpct}%). Try Mild.</div>'
    else:
        wc=f'<div class="wc-short">⚠️ Output <b>{abs(diff)} words shorter</b> ({iw}→{ow}, -{dpct}%).</div>'

    html = f"""
<div class="metrics-grid">
  <div class="metric-card">
    <div class="metric-title">Readability</div>
    <div class="metric-val" style="color:{read_color}">{read_level}</div>
    <div class="metric-sub">Text complexity level</div>
  </div>
  <div class="metric-card">
    <div class="metric-title">Tone</div>
    <div class="metric-val" style="color:{tone_color}">{tone_label}</div>
    <div class="metric-sub">Detected writing tone</div>
  </div>
  <div class="metric-card">
    <div class="metric-title">AI Detection Risk</div>
    <div class="metric-val" style="color:{ai_color}">{ai_label}</div>
    <div class="metric-sub">{ai_safe}% human probability</div>
  </div>
</div>
<div class="prog-box">
  <div class="prog-hdr">
    <span class="prog-label">Humanization Score</span>
    <span class="prog-val" style="color:{h_color}">{h_emoji} {hpct}% — {h_label}</span>
  </div>
  <div class="prog-track"><div class="prog-fill" style="width:{hpct}%;background:linear-gradient(90deg,{h_color}55,{h_color})"></div></div>
  <div class="prog-scale"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
</div>
<div class="prog-box">
  <div class="prog-hdr">
    <span class="prog-label">AI Detection Probability</span>
    <span class="prog-val" style="color:{ai_color}">{ai_prob}% AI detected</span>
  </div>
  <div class="prog-track"><div class="prog-fill" style="width:{ai_prob}%;background:linear-gradient(90deg,{ai_color}55,{ai_color})"></div></div>
  <div class="prog-scale"><span>Safe</span><span>25%</span><span>50%</span><span>75%</span><span>Detected</span></div>
</div>
{wc}
<div class="chips">
  <span class="chip ci">Input: <b>{iw}</b> words</span>
  <span class="chip co">Output: <b>{ow}</b> words</span>
  <span class="chip cc">Changed: <b>{chg}</b> ({cpct}%)</span>
  <span class="chip cm">{mode} · {intensity}</span>
</div>
<div class="legend"><span class="lgnd-sw"></span> Golden = changed words (click for synonyms)</div>
<div class="out-box"><div class="out-text">{hl}</div></div>
<div class="copy-row">
  <span class="plain-label">Plain Text — Copy Karein</span>
  <button class="copy-btn" onclick="copyOutput()">⎘ Copy</button>
</div>
<textarea class="plain-ta" onclick="this.select()">{output}</textarea>"""

    stats = f"Input: {iw}w → Output: {ow}w  |  Changed: {chg} ({cpct}%)  |  Humanized: {hpct}%  |  Readability: {read_level}  |  Tone: {tone_label}  |  AI Risk: {ai_label}"
    return jsonify({"html": html, "stats": stats, "plain_output": output, "hpct": hpct})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
