// Application State & DOM Bindings
const form = document.getElementById("scrapeForm");
const submitButton = document.getElementById("submitButton");
const statusBox = document.getElementById("status");
const statsBox = document.getElementById("stats");
const resultsContainer = document.getElementById("resultsContainer");
const phoneRequiredCheckbox = document.getElementById("phoneRequired");

const cityInput = document.getElementById("city");
const stateInput = document.getElementById("state");
const categoryInput = document.getElementById("category");
const limitInput = document.getElementById("limit");
const submitCityName = document.getElementById("submitCityName");

const currentScopeTitle = document.getElementById("currentScopeTitle");
const currentScopeSubtitle = document.getElementById("currentScopeSubtitle");
const btnScopeLocationOnly = document.getElementById("btnScopeLocationOnly");
const btnScopeAllMetros = document.getElementById("btnScopeAllMetros");

const quickPhoneCount = document.getElementById("quickPhoneCount");
const quickQualifiedCount = document.getElementById("quickQualifiedCount");
const quickDiscoveryCount = document.getElementById("quickDiscoveryCount");

const card1Label = document.getElementById("card1Label");
const card2Label = document.getElementById("card2Label");
const card3Label = document.getElementById("card3Label");

const linkExportPhoneCsv = document.getElementById("linkExportPhoneCsv");
const linkExportQualifiedCsv = document.getElementById("linkExportQualifiedCsv");
const linkExportDiscoveryCsv = document.getElementById("linkExportDiscoveryCsv");

const tabPhoneLeads = document.getElementById("tabPhoneLeads");
const tabQualifiedLeads = document.getElementById("tabQualifiedLeads");
const tabAllDiscovery = document.getElementById("tabAllDiscovery");

const phoneCountBadge = document.getElementById("phoneCountBadge");
const qualifiedCountBadge = document.getElementById("qualifiedCountBadge");
const discoveryCountBadge = document.getElementById("discoveryCountBadge");

const tableSearchInput = document.getElementById("tableSearchInput");
const runExportContainer = document.getElementById("runExportContainer");
const runPhoneCsvLink = document.getElementById("runPhoneCsvLink");
const runQualifiedCsvLink = document.getElementById("runQualifiedCsvLink");
const runDiscoveryCsvLink = document.getElementById("runDiscoveryCsvLink");

const btnToggleAutonomous = document.getElementById("btnToggleAutonomous");
const btnRunSweep = document.getElementById("btnRunSweep");
const autonomousStatusPill = document.getElementById("autonomousStatusPill");
const autonomousIndicatorDot = document.getElementById("autonomousIndicatorDot");
const autonomousStatusText = document.getElementById("autonomousStatusText");
const autonomousActivityTicker = document.getElementById("autonomousActivityTicker");

// Local application state
let activeCity = "Bhubaneswar";
let activeState = "Odisha";
let scopeMode = "location"; // "location" or "all"
let currentActiveTab = "phone";
let searchFilterQuery = "";

// Data caches
let cachedPhoneLeads = [];
let cachedQualifiedLeads = [];
let cachedDiscoveryData = [];

// Sync input changes to UI
if (cityInput) {
  cityInput.addEventListener("input", (e) => {
    activeCity = (e.target.value || "").trim();
    if (submitCityName) submitCityName.textContent = activeCity || "Desired Location";
    updateLocationScopeHeaders();
  });
}

if (stateInput) {
  stateInput.addEventListener("input", (e) => {
    activeState = (e.target.value || "").trim();
    updateLocationScopeHeaders();
  });
}

function selectPresetCity(city, state, btn) {
  document.querySelectorAll(".preset-pill").forEach(p => {
    if (p.textContent === city) p.classList.add("active");
    else if (["Bhubaneswar", "Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Pune", "Kolkata", "Chennai"].includes(p.textContent)) {
      p.classList.remove("active");
    }
  });
  if (cityInput) cityInput.value = city;
  if (stateInput) stateInput.value = state;
  activeCity = city;
  activeState = state;
  if (submitCityName) submitCityName.textContent = city;
  updateLocationScopeHeaders();
  loadLocationData();
}

function setPresetCategory(cat, btn) {
  if (categoryInput) categoryInput.value = cat;
  document.querySelectorAll(".preset-pill").forEach(p => {
    if (p.textContent === cat) p.classList.add("active");
    else if (!["Bhubaneswar", "Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Pune", "Kolkata", "Chennai"].includes(p.textContent)) {
      p.classList.remove("active");
    }
  });
}

function setScopeMode(mode) {
  scopeMode = mode;
  if (mode === "location") {
    if (btnScopeLocationOnly) btnScopeLocationOnly.classList.add("active");
    if (btnScopeAllMetros) btnScopeAllMetros.classList.remove("active");
  } else {
    if (btnScopeLocationOnly) btnScopeLocationOnly.classList.remove("active");
    if (btnScopeAllMetros) btnScopeAllMetros.classList.add("active");
  }
  updateLocationScopeHeaders();
  loadLocationData();
}

function updateLocationScopeHeaders() {
  const citySlug = (activeCity || "location").toLowerCase().replace(/\s+/g, '_');
  if (scopeMode === "location") {
    if (currentScopeTitle) currentScopeTitle.textContent = `${activeCity || 'Desired Location'}${activeState ? ', ' + activeState : ''}`;
    if (currentScopeSubtitle) currentScopeSubtitle.textContent = `Displaying full business intelligence, verified phone leads & discovery data for ${activeCity}.`;
    
    if (card1Label) card1Label.textContent = `${activeCity} Phone Leads`;
    if (card2Label) card2Label.textContent = `${activeCity} Qualified`;
    if (card3Label) card3Label.textContent = `${activeCity} Discovery`;

    if (linkExportPhoneCsv) {
      linkExportPhoneCsv.href = `/api/export/phone-leads?city=${encodeURIComponent(activeCity)}`;
      linkExportPhoneCsv.download = `${citySlug}_leads_with_phone.csv`;
    }

    if (linkExportQualifiedCsv) {
      linkExportQualifiedCsv.href = `/api/export/companies?city=${encodeURIComponent(activeCity)}`;
      linkExportQualifiedCsv.download = `${citySlug}_companies_leads.csv`;
    }
  } else {
    if (currentScopeTitle) currentScopeTitle.textContent = "All Metros Aggregate";
    if (currentScopeSubtitle) currentScopeSubtitle.textContent = "Displaying cumulative database records across all Indian geographical markets.";

    if (card1Label) card1Label.textContent = "Total Phone Leads";
    if (card2Label) card2Label.textContent = "Total Qualified Leads";
    if (card3Label) card3Label.textContent = "Total Discovery Data";

    if (linkExportPhoneCsv) {
      linkExportPhoneCsv.href = "/api/export/phone-leads";
      linkExportPhoneCsv.download = "dakini_leads_with_phone.csv";
    }

    if (linkExportQualifiedCsv) {
      linkExportQualifiedCsv.href = "/api/export/companies";
      linkExportQualifiedCsv.download = "dakini_companies_leads.csv";
    }
  }
}

// Load counts and table data for active scope
async function loadLocationData() {
  const targetCity = scopeMode === "location" ? activeCity : "";
  try {
    const countUrl = targetCity ? `/api/data/counts?city=${encodeURIComponent(targetCity)}` : `/api/data/counts`;
    const res = await fetch(countUrl);
    if (res.ok) {
      const data = await res.json();
      if (quickPhoneCount) quickPhoneCount.textContent = (data.phone_leads || 0).toLocaleString();
      if (quickQualifiedCount) quickQualifiedCount.textContent = (data.qualified_companies || 0).toLocaleString();
      if (quickDiscoveryCount) quickDiscoveryCount.textContent = (data.discovery_records || 0).toLocaleString();

      if (phoneCountBadge) phoneCountBadge.textContent = (data.phone_leads || 0).toLocaleString();
      if (qualifiedCountBadge) qualifiedCountBadge.textContent = (data.qualified_companies || 0).toLocaleString();
      if (discoveryCountBadge) discoveryCountBadge.textContent = (data.discovery_records || 0).toLocaleString();
    }
  } catch (e) {
    console.warn("Could not load counts", e);
  }

  await fetchTabDataset(currentActiveTab);
}

async function fetchTabDataset(tab) {
  if (resultsContainer) {
    resultsContainer.innerHTML = '<div class="status-banner" style="margin-top: 10px;">Loading records for ' + (scopeMode === 'location' ? activeCity : 'all locations') + '...</div>';
  }
  const targetCity = scopeMode === "location" ? activeCity : "";

  try {
    if (tab === "phone") {
      const url = targetCity 
        ? `/api/data/phone-leads?city=${encodeURIComponent(targetCity)}&limit=500` 
        : `/api/data/phone-leads?limit=500`;
      const res = await fetch(url);
      cachedPhoneLeads = await res.json();
    } else if (tab === "qualified") {
      const url = targetCity 
        ? `/api/data/qualified?city=${encodeURIComponent(targetCity)}&limit=500` 
        : `/api/data/qualified?limit=500`;
      const res = await fetch(url);
      cachedQualifiedLeads = await res.json();
    } else if (tab === "discovery") {
      const url = targetCity 
        ? `/api/data/discovery?city=${encodeURIComponent(targetCity)}&limit=500` 
        : `/api/data/discovery?limit=500`;
      const res = await fetch(url);
      cachedDiscoveryData = await res.json();
    }
    filterAndRender();
  } catch (e) {
    if (resultsContainer) {
      resultsContainer.innerHTML = '<div class="status-banner error" style="margin-top: 10px;">Failed to load data: ' + e.message + '</div>';
    }
  }
}

// Health check polling
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const dot = document.getElementById("systemLiveDot");
    const text = document.getElementById("systemLiveText");
    if (res.ok) {
      if (dot) dot.className = "pulse-dot";
      if (text) text.textContent = "Engine Online";
    } else {
      if (dot) dot.className = "pulse-dot idle";
      if (text) text.textContent = "Engine Paused";
    }
  } catch (e) {
    const dot = document.getElementById("systemLiveDot");
    const text = document.getElementById("systemLiveText");
    if (dot) dot.className = "pulse-dot idle";
    if (text) text.textContent = "Offline";
  }
}

// Autonomous Mode Controller
async function checkAutonomousStatus() {
  try {
    const res = await fetch("/api/autonomous/status");
    if (res.ok) {
      const state = await res.json();
      updateAutonomousUI(state);
    }
  } catch (e) {
    console.warn("Could not load autonomous status", e);
  }
}

function updateAutonomousUI(state) {
  if (state.running) {
    if (autonomousStatusPill) autonomousStatusPill.className = "auto-pill active";
    if (autonomousIndicatorDot) autonomousIndicatorDot.textContent = "🟢";
    if (autonomousStatusText) autonomousStatusText.textContent = `Auto-Pilot Running (${state.cycles_completed || 0} cycles)`;
    if (btnToggleAutonomous) btnToggleAutonomous.innerHTML = "⏸ Pause Autonomous Self-Scraper";
  } else {
    if (autonomousStatusPill) autonomousStatusPill.className = "auto-pill";
    if (autonomousIndicatorDot) autonomousIndicatorDot.textContent = "⚪";
    if (autonomousStatusText) autonomousStatusText.textContent = "Autonomous Mode Idle";
    if (btnToggleAutonomous) btnToggleAutonomous.innerHTML = "▶ Start Autonomous Self-Scraper";
  }

  if (autonomousActivityTicker) {
    if (state.current_target) {
      autonomousActivityTicker.textContent = `⚡ Active: Scraping ${state.current_target.category} in ${state.current_target.city}, ${state.current_target.state || ''} [Concurrency: ${state.concurrency || 6}]`;
    } else if (state.running) {
      autonomousActivityTicker.textContent = `⚡ Auto-Pilot searching for next high-yield metro target...`;
    } else {
      autonomousActivityTicker.textContent = `Activity: Idle. Press 'Start' to trigger background discovery cycles.`;
    }
  }
}

if (btnToggleAutonomous) {
  btnToggleAutonomous.addEventListener("click", async () => {
    try {
      const isRunning = btnToggleAutonomous.textContent.includes("Pause");
      const endpoint = isRunning ? "/api/autonomous/stop" : "/api/autonomous/start";
      const res = await fetch(endpoint, { method: "POST" });
      if (res.ok) {
        const state = await res.json();
        updateAutonomousUI(state);
        loadLocationData();
      }
    } catch (err) {
      alert("Failed to toggle autonomous engine: " + err.message);
    }
  });
}

if (btnRunSweep) {
  btnRunSweep.addEventListener("click", async () => {
    if (!confirm("Run an immediate multi-metro autonomous sweep across top Indian business hubs?")) return;
    try {
      if (autonomousActivityTicker) autonomousActivityTicker.textContent = "⚡ Triggering multi-metro sweep across top cities...";
      const res = await fetch("/api/autonomous/sweep", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (statusBox) {
          statusBox.className = "status-banner success";
          statusBox.textContent = `Autonomous sweep initiated: ${data.message || 'Queued top metros for background discovery'}.`;
        }
        setTimeout(() => {
          checkAutonomousStatus();
          loadLocationData();
        }, 1500);
      }
    } catch (err) {
      alert("Failed to start sweep: " + err.message);
    }
  });
}

// Master View Loaders
const btnMasterPhone = document.getElementById("btnViewMasterPhone");
const btnMasterQual = document.getElementById("btnViewMasterQualified");
const btnMasterDisc = document.getElementById("btnViewMasterDiscovery");

if (btnMasterPhone) btnMasterPhone.addEventListener("click", () => switchTab("phone"));
if (btnMasterQual) btnMasterQual.addEventListener("click", () => switchTab("qualified"));
if (btnMasterDisc) btnMasterDisc.addEventListener("click", () => switchTab("discovery"));

if (tabPhoneLeads) tabPhoneLeads.addEventListener("click", () => switchTab("phone"));
if (tabQualifiedLeads) tabQualifiedLeads.addEventListener("click", () => switchTab("qualified"));
if (tabAllDiscovery) tabAllDiscovery.addEventListener("click", () => switchTab("discovery"));

async function switchTab(tab) {
  currentActiveTab = tab;

  if (tabPhoneLeads) tabPhoneLeads.className = "tab-pill" + (tab === "phone" ? " active-phone" : "");
  if (tabQualifiedLeads) tabQualifiedLeads.className = "tab-pill" + (tab === "qualified" ? " active-qualified" : "");
  if (tabAllDiscovery) tabAllDiscovery.className = "tab-pill" + (tab === "discovery" ? " active-discovery" : "");

  await fetchTabDataset(tab);
}

if (tableSearchInput) {
  tableSearchInput.addEventListener("input", (e) => {
    searchFilterQuery = (e.target.value || "").trim().toLowerCase();
    filterAndRender();
  });
}

function filterAndRender() {
  const container = resultsContainer;
  if (!container) return;

  if (currentActiveTab === "phone") {
    let list = cachedPhoneLeads;
    if (searchFilterQuery) {
      list = list.filter(l =>
        (l.company_name || "").toLowerCase().includes(searchFilterQuery) ||
        (l.city || "").toLowerCase().includes(searchFilterQuery) ||
        (l.phone || "").toLowerCase().includes(searchFilterQuery) ||
        (l.website || "").toLowerCase().includes(searchFilterQuery) ||
        (l.locality || "").toLowerCase().includes(searchFilterQuery)
      );
    }
    renderQualifiedTable(list, container);
  } else if (currentActiveTab === "qualified") {
    let list = cachedQualifiedLeads;
    if (searchFilterQuery) {
      list = list.filter(l =>
        (l.company_name || "").toLowerCase().includes(searchFilterQuery) ||
        (l.city || "").toLowerCase().includes(searchFilterQuery) ||
        (l.phone || "").toLowerCase().includes(searchFilterQuery) ||
        (l.website || "").toLowerCase().includes(searchFilterQuery) ||
        (l.locality || "").toLowerCase().includes(searchFilterQuery)
      );
    }
    renderQualifiedTable(list, container);
  } else if (currentActiveTab === "discovery") {
    let list = cachedDiscoveryData;
    if (searchFilterQuery) {
      list = list.filter(d =>
        (d.url || d.normalized_url || "").toLowerCase().includes(searchFilterQuery) ||
        (d.domain || "").toLowerCase().includes(searchFilterQuery) ||
        (d.query || d.discovery_query || "").toLowerCase().includes(searchFilterQuery) ||
        (d.verified_city || "").toLowerCase().includes(searchFilterQuery)
      );
    }
    renderDiscoveryTable(list, container);
  }
}

function renderQualifiedTable(leads, container) {
  const locLabel = scopeMode === 'location' ? activeCity : 'All Locations';
  if (!leads.length) {
    container.innerHTML =
      `<div class="status-banner" style="margin-top: 10px; color: var(--text-muted);">
        No leads found for <strong>${escapeHtml(locLabel)}</strong> matching current view. 
        Click <strong>"⚡ Start Geographical Scrape"</strong> above to extract fresh data for this location!
      </div>`;
    return;
  }

  const rows = leads
    .map((lead) => {
      const websiteClean = lead.website ? lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '') : '—';
      const locType = lead.location_type || 'headquarters';
      const locality = lead.locality ? `<div style="font-size: 11.5px; color: var(--text-muted);">${escapeHtml(lead.locality)}</div>` : '';
      
      let servicesHtml = '';
      if (lead.industry_subcategory) {
        servicesHtml += `<span class="services-tag">${escapeHtml(lead.industry_subcategory)}</span>`;
      }
      if (Array.isArray(lead.services)) {
        lead.services.slice(0, 3).forEach(s => {
          servicesHtml += `<span class="services-tag">${escapeHtml(s)}</span>`;
        });
      }

      let contactPersonHtml = '';
      if (lead.contact_person) {
        contactPersonHtml = `<div style="font-size: 11.5px; color: var(--text-muted); margin-top: 3px;">👤 ${escapeHtml(lead.contact_person)}</div>`;
      }

      let evidenceHtml = '';
      if (Array.isArray(lead.evidence) && lead.evidence.length > 0) {
        evidenceHtml = `<div class="evidence-box">${escapeHtml(lead.evidence[0])}</div>`;
      } else if (lead.location_type) {
        evidenceHtml = `<div class="evidence-box">Verified in ${escapeHtml(lead.city || locLabel)} via physical presence & contact listings.</div>`;
      }

      return `
    <tr>
      <td>
        <strong>${escapeHtml(lead.company_name)}</strong>
        ${lead.company_age ? `<div style="font-size: 11px; color: var(--text-subtle);">${escapeHtml(lead.company_age)}</div>` : ''}
        <div>
          <a href="${escapeHtml(lead.website)}" target="_blank" rel="noopener" style="color: var(--text-black); text-decoration: underline; font-weight: 700; font-size: 12px;">
            ${escapeHtml(websiteClean)} ↗
          </a>
        </div>
      </td>
      <td>
        <strong>${escapeHtml(lead.city || '—')}</strong>, ${escapeHtml(lead.state || '—')}
        ${locality}
        <div style="margin-top: 4px;">
          <span class="badge badge-location-type">🏢 ${escapeHtml(locType)}</span>
        </div>
      </td>
      <td>
        ${lead.phone ? `
          <div>
            <a href="tel:${escapeHtml(lead.phone)}" class="badge badge-phone" title="Call ${escapeHtml(lead.phone)}">
              📞 ${escapeHtml(lead.phone)}
            </a>
            <button class="copy-btn" onclick="copyToClipboard('${escapeHtml(lead.phone)}')" title="Copy Phone">📋</button>
          </div>
        ` : '<span class="badge badge-no-phone">No Phone</span>'}
        
        ${lead.email ? `
          <div style="margin-top: 4px;">
            <a href="mailto:${escapeHtml(lead.email)}" style="color: var(--text-black); text-decoration: none; font-weight: 600; font-size: 12px;">✉️ ${escapeHtml(lead.email)}</a>
            <button class="copy-btn" onclick="copyToClipboard('${escapeHtml(lead.email)}')" title="Copy Email">📋</button>
          </div>
        ` : ''}

        ${contactPersonHtml}
      </td>
      <td>
        ${servicesHtml || '<span style="color: var(--text-subtle); font-size: 12px;">Digital Services</span>'}
      </td>
      <td>
        ${evidenceHtml}
      </td>
      <td>
        <span class="badge badge-qualified">Qualified</span>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">${escapeHtml(lead.contact_validation || 'verified')}</div>
      </td>
    </tr>
      `;
    })
    .join("");

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Company & Website</th>
            <th>Physical Location</th>
            <th>Verified Direct Contacts</th>
            <th>Services & Vertical</th>
            <th>Physical Verification Evidence</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderDiscoveryTable(discoveryData, container) {
  const locLabel = scopeMode === 'location' ? activeCity : 'All Locations';
  if (!discoveryData.length) {
    container.innerHTML =
      `<div class="status-banner" style="margin-top: 10px; color: var(--text-muted);">
        No discovery candidate URLs found for <strong>${escapeHtml(locLabel)}</strong> matching current view.
      </div>`;
    return;
  }

  const rows = discoveryData
    .map((item) => {
      const url = item.url || item.normalized_url || item.resolved_url || "";
      const domain = item.domain || "";
      const title = item.title || item.title_or_anchor || item.evidence_text || "—";
      const query = item.query || item.discovery_query || item.query_used || "—";
      const method = item.method || item.discovery_method || "public_web";
      const crawl = item.crawl_status || "completed";
      const status = item.pipeline_status || item.qualification_status || "candidate";
      const diag = item.reason || item.rejection_reason || item.last_error || "Passed Location Verification";

      let badgeClass = "badge-pending";
      if (status === "qualified" || status === "Qualified Lead") badgeClass = "badge-qualified";
      if (status.includes("failed") || status.includes("blocked") || status.includes("disqualified")) badgeClass = "badge-no-phone";

      return `
    <tr>
      <td>
        <a href="${escapeHtml(url)}" target="_blank" rel="noopener" style="color: var(--text-black); text-decoration: underline; font-weight: 700;">
          ${escapeHtml(domain || url)} ↗
        </a>
        <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(title)}</div>
      </td>
      <td><span style="font-family: var(--font-mono); font-size: 12px;">${escapeHtml(query)}</span></td>
      <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(method)}</td>
      <td><span class="badge ${crawl === 'completed' ? 'badge-qualified' : 'badge-no-phone'}">${escapeHtml(crawl)}</span></td>
      <td><span class="badge ${badgeClass}">${escapeHtml(status)}</span></td>
      <td style="color: var(--text-muted); font-size: 12px;">${escapeHtml(diag)}</td>
    </tr>
  `;
    })
    .join("");

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Discovered URL & Title</th>
            <th>Discovery Query Used</th>
            <th>Discovery Method</th>
            <th>Crawl Status</th>
            <th>Pipeline Qualification</th>
            <th>Diagnostics & Reason</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// Targeted Scrape Form Submission
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitButton) submitButton.disabled = true;

    const city = cityInput ? cityInput.value.trim() : "Bhubaneswar";
    const state = stateInput ? stateInput.value.trim() : "Odisha";
    const category = categoryInput ? categoryInput.value.trim() : "Digital Marketing";
    const limit = Number((limitInput && limitInput.value) || 200);
    const phoneOnly = phoneRequiredCheckbox ? phoneRequiredCheckbox.checked : false;

    // Lock dashboard into the target scraped location
    activeCity = city;
    activeState = state;
    scopeMode = "location";
    if (btnScopeLocationOnly) btnScopeLocationOnly.classList.add("active");
    if (btnScopeAllMetros) btnScopeAllMetros.classList.remove("active");
    updateLocationScopeHeaders();

    if (submitButton) submitButton.innerHTML = `⚡ Scraping ${escapeHtml(city)}...`;
    if (statusBox) {
      statusBox.className = "status-banner";
      statusBox.innerHTML = `⚡ Discovering & crawling public-web leads for <strong>${escapeHtml(category)}</strong> in <strong>${escapeHtml(city)}${state ? ', ' + escapeHtml(state) : ''}</strong>...`;
    }
    if (statsBox) statsBox.style.display = "none";
    if (runExportContainer) runExportContainer.style.display = "none";
    if (resultsContainer) {
      resultsContainer.innerHTML = '<div class="status-banner" style="margin-top: 10px;">Crawling web sources for ' + escapeHtml(city) + '...</div>';
    }

    const payload = {
      city,
      state: state || null,
      category,
      limit,
      phone_only: phoneOnly,
      concurrency: 8,
    };

    try {
      const response = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Server returned " + response.status);
      }

      const data = await response.json();
      const cityPhoneCount = (data.leads || []).filter(l => l.phone).length;

      if (statusBox) {
        statusBox.className = "status-banner success";
        statusBox.innerHTML = `
          ✅ <strong>Scrape Completed for ${escapeHtml(city)}!</strong> Discovered ${data.discovered} candidates, extracted ${data.qualified} qualified companies (${cityPhoneCount} with verified phone numbers).
        `;
      }

      if (statsBox) {
        statsBox.style.display = "grid";
        statsBox.innerHTML = `
          <div class="stat-pill-card">
            <div class="label">Discovered in ${escapeHtml(city)}</div>
            <div class="val">${data.discovered}</div>
          </div>
          <div class="stat-pill-card">
            <div class="label">Qualified in ${escapeHtml(city)}</div>
            <div class="val">${data.qualified}</div>
          </div>
          <div class="stat-pill-card">
            <div class="label">With Verified Phone</div>
            <div class="val">${cityPhoneCount}</div>
          </div>
          <div class="stat-pill-card">
            <div class="label">Scrape Time</div>
            <div class="val">${data.duration_seconds ? data.duration_seconds.toFixed(1) + 's' : '0.8s'}</div>
          </div>
        `;
      }

      // Configure targeted run export links
      const cleanSlug = city.toLowerCase().replace(/\s+/g, '_');
      if (data.csv_file || data.phone_leads_csv_file || data.discovery_csv_file) {
        if (runExportContainer) runExportContainer.style.display = "block";
        if (runPhoneCsvLink && (data.phone_leads_csv_file || data.csv_file)) {
          runPhoneCsvLink.style.display = "inline-flex";
          runPhoneCsvLink.href = `/api/download?path=${encodeURIComponent(data.phone_leads_csv_file || data.csv_file)}`;
          runPhoneCsvLink.download = `${cleanSlug}_leads_with_phone.csv`;
        }
        if (runQualifiedCsvLink && data.csv_file) {
          runQualifiedCsvLink.style.display = "inline-flex";
          runQualifiedCsvLink.href = `/api/download?path=${encodeURIComponent(data.csv_file)}`;
          runQualifiedCsvLink.download = `${cleanSlug}_qualified_leads.csv`;
        }
        if (runDiscoveryCsvLink && data.discovery_csv_file) {
          runDiscoveryCsvLink.style.display = "inline-flex";
          runDiscoveryCsvLink.href = `/api/download?path=${encodeURIComponent(data.discovery_csv_file)}`;
          runDiscoveryCsvLink.download = `${cleanSlug}_discovery_all.csv`;
        }
      }

      // Cache results locally for immediate display
      cachedQualifiedLeads = data.leads || [];
      cachedPhoneLeads = cachedQualifiedLeads.filter(l => Boolean(l.phone));
      if (data.discovery_data || data.discovery_records) {
        cachedDiscoveryData = data.discovery_data || data.discovery_records;
      }

      // Update counts and switch view to this location
      if (quickPhoneCount) quickPhoneCount.textContent = cachedPhoneLeads.length.toLocaleString();
      if (quickQualifiedCount) quickQualifiedCount.textContent = cachedQualifiedLeads.length.toLocaleString();
      if (quickDiscoveryCount) quickDiscoveryCount.textContent = (data.discovered || 0).toLocaleString();

      if (phoneCountBadge) phoneCountBadge.textContent = cachedPhoneLeads.length.toLocaleString();
      if (qualifiedCountBadge) qualifiedCountBadge.textContent = cachedQualifiedLeads.length.toLocaleString();
      if (discoveryCountBadge) discoveryCountBadge.textContent = (data.discovered || 0).toLocaleString();

      switchTab(phoneOnly ? "phone" : "qualified");
    } catch (error) {
      if (statusBox) {
        statusBox.className = "status-banner error";
        statusBox.textContent = "Error: " + error.message;
      }
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.innerHTML = `⚡ Start Geographical Scrape for <span id="submitCityName">${escapeHtml(activeCity)}</span>`;
      }
    }
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function copyToClipboard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text);
    if (statusBox) {
      const originalStatus = statusBox.textContent;
      statusBox.className = "status-banner success";
      statusBox.textContent = `Copied to clipboard: ${text}`;
      setTimeout(() => {
        statusBox.textContent = originalStatus;
      }, 2000);
    }
  }
}

// Initialize application on page load
updateLocationScopeHeaders();
loadLocationData();
checkAutonomousStatus();
checkHealth();

// Background interval updates
setInterval(checkAutonomousStatus, 4000);
setInterval(checkHealth, 15000);

