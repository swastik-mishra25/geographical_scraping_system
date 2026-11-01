"""
Generates a simplified, high-fidelity High-Level Architectural Diagram for the Dakini AI Autonomous System.
Outputs:
  - architecture_diagram.svg (clean vector)
  - docs/architecture_diagram.svg
  - docs/architecture_diagram.html (interactive viewer with one-click export)
"""

import os

SVG_CONTENT = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1150" width="1200" height="1150" style="background:#0b0f19; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <defs>
    <!-- Gradients -->
    <linearGradient id="headerGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="50%" stop-color="#818cf8" />
      <stop offset="100%" stop-color="#34d399" />
    </linearGradient>
    
    <linearGradient id="cardBg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#1e293b" />
      <stop offset="100%" stop-color="#0f172a" />
    </linearGradient>

    <linearGradient id="layerBg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#172033" />
      <stop offset="100%" stop-color="#0d1424" />
    </linearGradient>

    <!-- Shadow -->
    <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%" filterUnits="userSpaceOnUse">
      <feGaussianBlur in="SourceAlpha" stdDeviation="5" />
      <feOffset dx="0" dy="3" />
      <feComponentTransfer><feFuncA type="linear" slope="0.3" /></feComponentTransfer>
      <feMerge>
        <feMergeNode />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    <!-- Arrows -->
    <marker id="arrowBlue" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8" />
    </marker>
    <marker id="arrowPurple" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#818cf8" />
    </marker>
    <marker id="arrowGreen" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#34d399" />
    </marker>
  </defs>

  <!-- ==================== HEADER ==================== -->
  <g transform="translate(50, 35)">
    <rect width="1100" height="100" rx="14" fill="url(#cardBg)" stroke="#1e293b" stroke-width="1.5" filter="url(#shadow)" />
    
    <rect x="25" y="20" width="160" height="22" rx="11" fill="#0284c7" fill-opacity="0.2" stroke="#38bdf8" stroke-width="1" />
    <text x="105" y="35" fill="#38bdf8" font-size="11" font-weight="700" letter-spacing="1" text-anchor="middle">DAKINI AI SYSTEM</text>

    <text x="25" y="68" fill="#f8fafc" font-size="22" font-weight="800">Simplified 3-Layer System Architecture</text>
    <text x="25" y="88" fill="#94a3b8" font-size="13">High-Level Overview: Interfaces, Autonomous Processing Pipeline, and Storage &amp; Exports</text>

    <rect x="940" y="32" width="130" height="32" rx="8" fill="#334155" />
    <text x="1005" y="53" fill="#e2e8f0" font-size="12" font-weight="700" text-anchor="middle">v2.0 Clean Architecture</text>
  </g>

  <!-- ==================== LAYER 1: INTERFACES ==================== -->
  <g transform="translate(50, 160)">
    <rect width="1100" height="180" rx="14" fill="url(#layerBg)" stroke="#334155" stroke-width="1.5" filter="url(#shadow)" />
    
    <!-- Title Pill -->
    <rect x="25" y="18" width="280" height="26" rx="8" fill="#0369a1" fill-opacity="0.3" stroke="#38bdf8" stroke-width="1" />
    <text x="35" y="35" fill="#38bdf8" font-size="12" font-weight="700" letter-spacing="1">LAYER 1: INTERFACES (HOW YOU RUN IT)</text>

    <!-- 3 Cards -->
    <g transform="translate(25, 55)">
      <!-- Web UI -->
      <rect width="330" height="105" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
      <circle cx="28" cy="28" r="12" fill="#0284c7" fill-opacity="0.2" stroke="#38bdf8" stroke-width="1.5" />
      <text x="28" y="33" fill="#38bdf8" font-size="12" font-weight="bold" text-anchor="middle">UI</text>
      <text x="50" y="32" fill="#f8fafc" font-size="15" font-weight="700">Interactive Web UI</text>
      <text x="18" y="60" fill="#94a3b8" font-size="12">• Preserved form (City, State, Category)</text>
      <text x="18" y="78" fill="#94a3b8" font-size="12">• Real-time leads table &amp; live CSV download</text>
      <text x="18" y="96" fill="#38bdf8" font-size="11" font-weight="600">POST /api/scrape • app/static/index.html</text>

      <!-- Worker CLI -->
      <g transform="translate(360, 0)">
        <rect width="330" height="105" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
        <circle cx="28" cy="28" r="12" fill="#6366f1" fill-opacity="0.2" stroke="#818cf8" stroke-width="1.5" />
        <text x="28" y="33" fill="#818cf8" font-size="12" font-weight="bold" text-anchor="middle">CLI</text>
        <text x="50" y="32" fill="#f8fafc" font-size="15" font-weight="700">Autonomous Worker</text>
        <text x="18" y="60" fill="#94a3b8" font-size="12">• Independent background daemon process</text>
        <text x="18" y="78" fill="#94a3b8" font-size="12">• Auto-resumes runs via SQLite checkpoints</text>
        <text x="18" y="96" fill="#818cf8" font-size="11" font-weight="600">python -m app.worker • worker.lock</text>
      </g>

      <!-- REST API -->
      <g transform="translate(720, 0)">
        <rect width="330" height="105" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
        <circle cx="28" cy="28" r="12" fill="#059669" fill-opacity="0.2" stroke="#34d399" stroke-width="1.5" />
        <text x="28" y="33" fill="#34d399" font-size="12" font-weight="bold" text-anchor="middle">API</text>
        <text x="50" y="32" fill="#f8fafc" font-size="15" font-weight="700">REST API &amp; Telemetry</text>
        <text x="18" y="60" fill="#94a3b8" font-size="12">• 13-Industry catalog endpoint</text>
        <text x="18" y="78" fill="#94a3b8" font-size="12">• Job queueing &amp; execution status</text>
        <text x="18" y="96" fill="#34d399" font-size="11" font-weight="600">GET /api/industries • GET /api/runs</text>
      </g>
    </g>
  </g>

  <!-- Big Connector L1 -> L2 -->
  <line x1="600" y1="340" x2="600" y2="375" stroke="#818cf8" stroke-width="3" marker-end="url(#arrowPurple)" />

  <!-- ==================== LAYER 2: AUTONOMOUS PIPELINE ==================== -->
  <g transform="translate(50, 385)">
    <rect width="1100" height="390" rx="14" fill="url(#layerBg)" stroke="#4338ca" stroke-width="1.5" filter="url(#shadow)" />
    
    <!-- Title Pill -->
    <rect x="25" y="18" width="370" height="26" rx="8" fill="#4338ca" fill-opacity="0.3" stroke="#818cf8" stroke-width="1" />
    <text x="35" y="35" fill="#a5b4fc" font-size="12" font-weight="700" letter-spacing="1">LAYER 2: AUTONOMOUS PIPELINE (WHAT HAPPENS)</text>

    <!-- 4 Clear Pipeline Stages (Grid 2x2) -->
    <g transform="translate(25, 55)">
      <!-- Step 1: Discover -->
      <rect width="510" height="135" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
      <rect x="18" y="16" width="28" height="28" rx="6" fill="#0284c7" />
      <text x="32" y="35" fill="#ffffff" font-size="14" font-weight="bold" text-anchor="middle">1</text>
      <text x="56" y="35" fill="#f8fafc" font-size="16" font-weight="700">Smart Web Discovery</text>
      <text x="18" y="65" fill="#94a3b8" font-size="12">• Generates targeted queries (e.g. "SEO agency in Andheri")</text>
      <text x="18" y="85" fill="#94a3b8" font-size="12">• Queries open web search gateways &amp; encyclopedic link indexes</text>
      <text x="18" y="105" fill="#ef4444" font-size="12">• Aggregator Filter: Blocks Justdial, Sulekha, Indiamart, FB, etc.</text>
      <text x="18" y="123" fill="#38bdf8" font-size="11">app/services/query_generator.py &amp; public_web_discovery.py</text>

      <!-- Step 2: Crawl Safely -->
      <g transform="translate(540, 0)">
        <rect width="510" height="135" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
        <rect x="18" y="16" width="28" height="28" rx="6" fill="#d97706" />
        <text x="32" y="35" fill="#ffffff" font-size="14" font-weight="bold" text-anchor="middle">2</text>
        <text x="56" y="35" fill="#f8fafc" font-size="16" font-weight="700">Safe Multi-Page Crawl</text>
        <text x="18" y="65" fill="#38bdf8" font-size="12">• SSRF Protection: Pre-resolves IP; blocks private networks &amp; metadata</text>
        <text x="18" y="85" fill="#94a3b8" font-size="12">• robots.txt compliance &amp; zero-bypass halt on 401/403/429/CAPTCHA</text>
        <text x="18" y="105" fill="#94a3b8" font-size="12">• Priority crawl: Homepage (100) &gt; Contact (95) &gt; About (85) &gt; Services (80)</text>
        <text x="18" y="123" fill="#fbbf24" font-size="11">app/services/crawl_policy.py, url_frontier.py &amp; crawler.py</text>
      </g>

      <!-- Step 3: Verify -->
      <g transform="translate(0, 150)">
        <rect width="510" height="135" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
        <rect x="18" y="16" width="28" height="28" rx="6" fill="#6366f1" />
        <text x="32" y="35" fill="#ffffff" font-size="14" font-weight="bold" text-anchor="middle">3</text>
        <text x="56" y="35" fill="#f8fafc" font-size="16" font-weight="700">Industry &amp; Location Verification</text>
        <text x="18" y="65" fill="#94a3b8" font-size="12">• Industry: Matches 12 Digital Marketing subcategories</text>
        <text x="18" y="85" fill="#ef4444" font-size="12">• Negative Filter: Strictly excludes student courses &amp; coaching institutes</text>
        <text x="18" y="105" fill="#94a3b8" font-size="12">• Location: Classifies Headquarters | Branch | Service-Area with PIN code</text>
        <text x="18" y="123" fill="#818cf8" font-size="11">app/services/industry_classifier.py &amp; location_verifier.py</text>
      </g>

      <!-- Step 4: Extract -->
      <g transform="translate(540, 150)">
        <rect width="510" height="135" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1.2" />
        <rect x="18" y="16" width="28" height="28" rx="6" fill="#059669" />
        <text x="32" y="35" fill="#ffffff" font-size="14" font-weight="bold" text-anchor="middle">4</text>
        <text x="56" y="35" fill="#f8fafc" font-size="16" font-weight="700">Zero-Fabrication Data Extraction</text>
        <text x="18" y="65" fill="#34d399" font-size="12">• ZERO FABRICATION: Only extracts published evidence (no fake data)</text>
        <text x="18" y="85" fill="#94a3b8" font-size="12">• Standardized +91 phone numbers, official emails, leadership &amp; age</text>
        <text x="18" y="105" fill="#94a3b8" font-size="12">• Every fact links to exact text excerpt &amp; source URL in evidence log</text>
        <text x="18" y="123" fill="#34d399" font-size="11">app/services/extraction.py &amp; validation.py</text>
      </g>
    </g>

    <!-- Pipeline Footer Note -->
    <rect x="25" y="350" width="1050" height="26" rx="6" fill="#1e1b4b" stroke="#312e81" stroke-width="1" />
    <text x="550" y="367" fill="#a5b4fc" font-size="11" font-weight="600" text-anchor="middle">⚡ Checkpoint Engine: Saves atomic snapshots to SQLite at every step. Interrupted runs cleanly resume without repeat work.</text>
  </g>

  <!-- Big Connector L2 -> L3 -->
  <line x1="600" y1="775" x2="600" y2="810" stroke="#34d399" stroke-width="3" marker-end="url(#arrowGreen)" />

  <!-- ==================== LAYER 3: STORAGE & EXPORT ==================== -->
  <g transform="translate(50, 820)">
    <rect width="1100" height="210" rx="14" fill="url(#layerBg)" stroke="#059669" stroke-width="1.5" filter="url(#shadow)" />
    
    <!-- Title Pill -->
    <rect x="25" y="18" width="370" height="26" rx="8" fill="#064e3b" fill-opacity="0.3" stroke="#10b981" stroke-width="1" />
    <text x="35" y="35" fill="#34d399" font-size="12" font-weight="700" letter-spacing="1">LAYER 3: STORAGE &amp; EXPORT (WHERE RESULTS GO)</text>

    <!-- 2 Main Blocks: Master SQLite DB & File Exports -->
    <g transform="translate(25, 55)">
      <!-- Master SQLite DB -->
      <rect width="680" height="135" rx="10" fill="#022c22" fill-opacity="0.4" stroke="#047857" stroke-width="1.2" />
      <text x="20" y="30" fill="#6ee7b7" font-size="15" font-weight="700">💾 Master Database (data/dakini_discovery.db)</text>
      <text x="20" y="52" fill="#a7f3d0" font-size="12">• Built with Python standard library sqlite3 with WAL (Write-Ahead Logging) mode</text>
      <text x="20" y="72" fill="#a7f3d0" font-size="12">• 7 relational tables: companies, company_evidence, discovered_urls,</text>
      <text x="28" y="90" fill="#a7f3d0" font-size="12">crawl_frontier, domain_policy, research_runs, research_checkpoints</text>
      <text x="20" y="112" fill="#34d399" font-size="11" font-weight="600">O(N) Deduplication on canonical domain, CIN &amp; company name</text>

      <!-- File Exports -->
      <g transform="translate(700, 0)">
        <rect width="350" height="135" rx="10" fill="#022c22" fill-opacity="0.4" stroke="#047857" stroke-width="1.2" />
        <text x="20" y="30" fill="#6ee7b7" font-size="15" font-weight="700">📊 Structured File Exports</text>
        <text x="20" y="55" fill="#a7f3d0" font-size="12">• UTF-8 CSV with BOM for Excel</text>
        <text x="20" y="75" fill="#a7f3d0" font-size="12">• Preserves exact original column headers</text>
        <text x="20" y="95" fill="#a7f3d0" font-size="12">• Optional Excel (.xlsx) output</text>
        <text x="20" y="115" fill="#34d399" font-size="11" font-weight="600">data/&lt;city&gt;_&lt;category&gt;_leads.csv</text>
      </g>
    </g>
  </g>

  <!-- ==================== FOOTER ==================== -->
  <g transform="translate(50, 1050)">
    <rect width="1100" height="60" rx="10" fill="#0f172a" stroke="#1e293b" stroke-width="1" />
    <text x="30" y="35" fill="#94a3b8" font-size="12">🔒 <tspan fill="#f8fafc" font-weight="600">Key Guarantees:</tspan> Zero Data Fabrication • SSRF &amp; robots.txt Safe • Existing UI &amp; API Contract 100% Preserved</text>
  </g>
</svg>'''

HTML_VIEWER = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dakini AI Autonomous System - Simplified Architecture</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: #0b0f19;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: #131b2e;
      border-bottom: 1px solid #1f2c47;
      padding: 16px 32px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .title-group h1 {
      font-size: 18px;
      font-weight: 700;
      color: #f8fafc;
    }
    .title-group p {
      font-size: 13px;
      color: #94a3b8;
    }
    .actions {
      display: flex;
      gap: 12px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.2s ease;
      border: 1px solid transparent;
    }
    .btn-svg {
      background: #0284c7;
      color: #ffffff;
    }
    .btn-svg:hover {
      background: #0369a1;
    }
    .btn-png {
      background: #059669;
      color: #ffffff;
    }
    .btn-png:hover {
      background: #047857;
    }
    .btn-outline {
      background: #1e293b;
      color: #cbd5e1;
      border-color: #334155;
    }
    .btn-outline:hover {
      background: #334155;
      color: #ffffff;
    }
    .container {
      flex: 1;
      display: flex;
      justify-content: center;
      padding: 24px;
      overflow-x: auto;
    }
    .svg-wrapper {
      max-width: 1200px;
      width: 100%;
      background: #0b0f19;
      border-radius: 16px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
      border: 1px solid #1e293b;
      padding: 16px;
    }
    .svg-wrapper svg {
      width: 100%;
      height: auto;
      display: block;
    }
  </style>
</head>
<body>
  <header>
    <div class="title-group">
      <h1>Dakini AI Autonomous System Architecture</h1>
      <p>Simplified 3-Layer System Architecture</p>
    </div>
    <div class="actions">
      <button class="btn btn-svg" id="downloadSvgBtn" title="Download vector SVG file">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        Download SVG (Vector)
      </button>
      <button class="btn btn-png" id="downloadPngBtn" title="Download high-resolution PNG image">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
        Download PNG (High-Res)
      </button>
      <a href="architecture_diagram.svg" target="_blank" class="btn btn-outline" title="Open raw SVG in new tab">
        Open Raw SVG
      </a>
    </div>
  </header>

  <main class="container">
    <div class="svg-wrapper" id="diagramWrapper">
''' + SVG_CONTENT + '''
    </div>
  </main>

  <script>
    // Download SVG
    document.getElementById('downloadSvgBtn').addEventListener('click', () => {
      const svg = document.querySelector('svg');
      const svgData = new XMLSerializer().serializeToString(svg);
      const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'dakini_system_architecture.svg';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    });

    // Download High-Res PNG via Canvas
    document.getElementById('downloadPngBtn').addEventListener('click', () => {
      const svg = document.querySelector('svg');
      const svgData = new XMLSerializer().serializeToString(svg);
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      const img = new Image();

      // High-res retina scale (2x)
      const scale = 2;
      const width = 1200 * scale;
      const height = 1150 * scale;
      canvas.width = width;
      canvas.height = height;

      img.onload = () => {
        ctx.fillStyle = '#0b0f19';
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        const pngUrl = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.href = pngUrl;
        link.download = 'dakini_system_architecture.png';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      };

      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      img.src = URL.createObjectURL(svgBlob);
    });
  </script>
</body>
</html>'''

def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    svg_root_path = os.path.join(root, "architecture_diagram.svg")
    svg_docs_path = os.path.join(root, "docs", "architecture_diagram.svg")
    html_docs_path = os.path.join(root, "docs", "architecture_diagram.html")

    with open(svg_root_path, "w", encoding="utf-8") as f:
        f.write(SVG_CONTENT)
    print(f"Wrote {svg_root_path}")

    with open(svg_docs_path, "w", encoding="utf-8") as f:
        f.write(SVG_CONTENT)
    print(f"Wrote {svg_docs_path}")

    with open(html_docs_path, "w", encoding="utf-8") as f:
        f.write(HTML_VIEWER)
    print(f"Wrote {html_docs_path}")

if __name__ == "__main__":
    main()

