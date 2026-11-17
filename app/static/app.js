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

const multiLocalityCheckbox = document.getElementById("multiLocalityCampaign");
const campaignPanel = document.getElementById("campaignProgressPanel");
const campaignTitle = document.getElementById("campaignTitle");
const campaignShardBadge = document.getElementById("campaignShardBadge");
const campaignProgressBar = document.getElementById("campaignProgressBar");
const campaignCurrentShard = document.getElementById("campaignCurrentShard");
const campaignLeadsCount = document.getElementById("campaignLeadsCount");
const campaignPercentText = document.getElementById("campaignPercentText");
let campaignPollInterval = null;

async function stopRunningCampaign() {
  try {
    await fetch("/api/campaign/stop", { method: "POST" });
    if (statusBox) statusBox.innerHTML = "⚠️ Cancellation signal sent to autonomous campaign worker...";
    const tickerText = document.getElementById("campaignTickerText");
    if (tickerText) tickerText.textContent = "Halting campaign worker...";
  } catch (err) {
    console.error("Stop campaign error", err);
  }
}
window.stopRunningCampaign = stopRunningCampaign;

function startCampaignPolling(city) {
  if (campaignPollInterval) clearInterval(campaignPollInterval);
  let pollCounter = 0;
  campaignPollInterval = setInterval(async () => {
    try {
      const pollRes = await fetch("/api/campaign/status");
      if (pollRes.ok) {
        const st = await pollRes.json();
        const pct = Math.max(2, Math.min(100, st.percent_complete || 2));
        if (campaignProgressBar) campaignProgressBar.style.width = `${pct}%`;
        if (campaignPercentText) campaignPercentText.textContent = `${st.percent_complete || 0}%`;
        if (campaignShardBadge) campaignShardBadge.textContent = `Shard ${st.shard_index || 1}/${st.total_shards || 1}`;
        if (campaignCurrentShard) campaignCurrentShard.textContent = st.current_shard || "Sweeping district...";
        if (campaignLeadsCount) campaignLeadsCount.textContent = (st.leads_accumulated || 0).toLocaleString();

        const tickerText = document.getElementById("campaignTickerText");
        if (tickerText && st.active_message) {
          tickerText.textContent = st.active_message;
        }

        // Progressive database sync every 3 polls
        pollCounter++;
        if (pollCounter % 3 === 0) {
          await loadLocationData();
        }

        if (!st.is_active || st.status === "completed" || st.status === "error" || st.status === "stopped") {
          clearInterval(campaignPollInterval);
          campaignPollInterval = null;
          if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = `⚡ Start Geographical Scrape for <span id="submitCityName">${escapeHtml(activeCity)}</span>`;
          }
          if (statusBox) {
            statusBox.className = "status-banner success";
            statusBox.innerHTML = `✅ <strong>Autonomous Campaign Completed for ${escapeHtml(city || activeCity)}!</strong> Extracted ${st.leads_accumulated} verified leads across ${st.total_shards} commercial hubs.`;
          }
          if (campaignProgressBar) campaignProgressBar.style.width = "100%";
          if (campaignPercentText) campaignPercentText.textContent = "100%";
          if (tickerText) {
            tickerText.textContent = st.active_message || `Campaign finished: ${st.leads_accumulated} leads collected.`;
          }
          await loadLocationData();
          await fetchTabDataset(currentActiveTab);
        }
      }
    } catch (pollErr) {
      console.warn("Campaign poll error", pollErr);
    }
  }, 1000);
}

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
  const crmCitySpan = document.getElementById("crmSyncCityName");
  if (crmCitySpan) crmCitySpan.textContent = activeCity || "Desired Location";

  if (scopeMode === "location") {
    if (currentScopeTitle) currentScopeTitle.textContent = `${activeCity || 'Desired Location'}${activeState ? ', ' + activeState : ''}`;
    if (currentScopeSubtitle) currentScopeSubtitle.textContent = `Displaying full business intelligence, verified phone leads & discovery data for ${activeCity}.`;

    if (card1Label) card1Label.innerHTML = `${escapeHtml(activeCity)} Phone Leads <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;
    if (card2Label) card2Label.innerHTML = `${escapeHtml(activeCity)} Qualified <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;
    if (card3Label) card3Label.innerHTML = `${escapeHtml(activeCity)} Discovered URLs <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;

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

    if (card1Label) card1Label.innerHTML = `Total Phone Leads <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;
    if (card2Label) card2Label.innerHTML = `Total Qualified Leads <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;
    if (card3Label) card3Label.innerHTML = `Total Discovered URLs <span style="font-size:10px; font-weight:700; opacity:0.65;">[DB]</span>`;

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

      let servicesList = [];
      if (Array.isArray(lead.services)) {
        servicesList = lead.services;
      } else if (typeof lead.services === "string" && lead.services.trim()) {
        try {
          const parsed = JSON.parse(lead.services);
          if (Array.isArray(parsed)) servicesList = parsed;
          else servicesList = [lead.services];
        } catch {
          servicesList = lead.services.split(",").map(s => s.trim()).filter(Boolean);
        }
      }

      let servicesHtml = '';
      if (lead.industry_subcategory) {
        servicesHtml += `<span class="services-tag">${escapeHtml(lead.industry_subcategory)}</span>`;
      }
      servicesList.slice(0, 3).forEach(s => {
        servicesHtml += `<span class="services-tag">${escapeHtml(s)}</span>`;
      });

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
        <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap;">
          <span class="badge badge-qualified">Qualified</span>
          ${lead.lead_quality_score ? `<span style="font-weight: 800; font-size: 11px; padding: 2px 6px; border-radius: 4px; background: var(--violet-bg); color: #6d28d9; border: 1px solid var(--violet-border);" title="${escapeHtml(lead.score_reason || '')}">⭐ ${lead.lead_quality_score}/100</span>` : ''}
        </div>
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

    const isMultiCampaign = Boolean(multiLocalityCheckbox && multiLocalityCheckbox.checked && limit >= 50);

    if (isMultiCampaign) {
      if (campaignPanel) campaignPanel.style.display = "block";
      if (campaignTitle) campaignTitle.textContent = `🚀 Autonomous Multi-Locality Campaign: ${city}`;
      if (campaignProgressBar) campaignProgressBar.style.width = "2%";
      if (campaignShardBadge) campaignShardBadge.textContent = "Starting Shards...";
      if (campaignCurrentShard) campaignCurrentShard.textContent = "Partitioning commercial clusters...";
      if (campaignLeadsCount) campaignLeadsCount.textContent = "0";
      if (campaignPercentText) campaignPercentText.textContent = "1%";
      const tickerText = document.getElementById("campaignTickerText");
      if (tickerText) tickerText.textContent = `Partitioning ${city} into high-density commercial hubs...`;

      try {
        const campRes = await fetch("/api/campaign/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            city,
            state: state || "",
            category,
            target_limit: limit,
            phone_required: phoneOnly,
          }),
        });

        if (!campRes.ok) {
          const errData = await campRes.json().catch(() => ({}));
          throw new Error(errData.detail || "Failed to start campaign");
        }

        if (statusBox) {
          statusBox.className = "status-banner success";
          statusBox.innerHTML = `🚀 <strong>Autonomous Multi-Locality Campaign active for ${escapeHtml(city)}!</strong> Sweeping across commercial districts in the background...`;
        }

        startCampaignPolling(city);
        return;
      } catch (campErr) {
        if (campaignPanel) campaignPanel.style.display = "none";
        if (statusBox) {
          statusBox.className = "status-banner error";
          statusBox.textContent = "Campaign error: " + campErr.message;
        }
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.innerHTML = `⚡ Start Geographical Scrape for <span id="submitCityName">${escapeHtml(activeCity)}</span>`;
        }
        return;
      }
    }

    const payload = {
      city,
      state: state || null,
      category,
      limit,
      phone_required: phoneOnly,
      phone_only: phoneOnly,
      multi_locality: Boolean(multiLocalityCheckbox && multiLocalityCheckbox.checked),
      concurrency: 8,
    };

    const scrapeStartTime = performance.now();

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
      const clientElapsedSec = Math.max(0.1, (performance.now() - scrapeStartTime) / 1000);
      const displayDuration = (typeof data.duration_seconds === "number" && data.duration_seconds > 0)
        ? `${data.duration_seconds.toFixed(1)}s`
        : `${clientElapsedSec.toFixed(1)}s`;

      const totalQual = data.total_qualified || data.qualified;
      const phoneOnlyActive = phoneOnly && totalQual > data.qualified;
      const filterExplanation = phoneOnlyActive
        ? ` (${data.qualified} phone-verified exported under strict filter; ${totalQual} total qualified saved to database)`
        : ` (${cityPhoneCount} with verified phone numbers)`;

      if (statusBox) {
        statusBox.className = "status-banner success";
        statusBox.innerHTML = `
          ✅ <strong>Scrape Run Completed for ${escapeHtml(city)}!</strong> Discovered ${data.discovered} candidates in this run, extracted ${totalQual} qualified companies${filterExplanation} in ${displayDuration}. Database pool updated.
        `;
      }

      if (statsBox) {
        statsBox.style.display = "grid";
        const phoneCardLabel = phoneOnly ? "Phone Filtered Leads" : "With Verified Phone";
        const qualSubtext = phoneOnlyActive
          ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">(${totalQual} total before phone filter)</div>`
          : '';
        statsBox.innerHTML = `
          <div class="stat-pill-card">
            <div class="label">Discovered (This Run)</div>
            <div class="val">${data.discovered}</div>
          </div>
          <div class="stat-pill-card">
            <div class="label">${phoneOnlyActive ? 'Phone Leads (Exported)' : 'Qualified (This Run)'}</div>
            <div class="val">${data.qualified}</div>
            ${qualSubtext}
          </div>
          <div class="stat-pill-card">
            <div class="label">${phoneCardLabel}</div>
            <div class="val">${cityPhoneCount}</div>
          </div>
          <div class="stat-pill-card">
            <div class="label">Scrape Time</div>
            <div class="val">${displayDuration}</div>
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

      // Refresh database master pool counters and sync view
      await loadLocationData();
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

async function checkAndResumeCampaign() {
  try {
    const res = await fetch("/api/campaign/status");
    if (!res.ok) return;
    const st = await res.json();
    if (st && st.is_active) {
      if (campaignPanel) campaignPanel.style.display = "block";
      if (campaignTitle) campaignTitle.textContent = `🚀 Autonomous Multi-Locality Campaign: ${st.city}`;
      const pct = Math.max(2, Math.min(100, st.percent_complete || 2));
      if (campaignProgressBar) campaignProgressBar.style.width = `${pct}%`;
      if (campaignPercentText) campaignPercentText.textContent = `${st.percent_complete || 0}%`;
      if (campaignShardBadge) campaignShardBadge.textContent = `Shard ${st.shard_index || 1}/${st.total_shards || 1}`;
      if (campaignCurrentShard) campaignCurrentShard.textContent = st.current_shard || "Sweeping district...";
      if (campaignLeadsCount) campaignLeadsCount.textContent = (st.leads_accumulated || 0).toLocaleString();
      const tickerText = document.getElementById("campaignTickerText");
      if (tickerText && st.active_message) {
        tickerText.textContent = st.active_message;
      }
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerHTML = `🚀 Campaign running for ${escapeHtml(st.city)}...`;
      }
      if (!campaignPollInterval) {
        startCampaignPolling(st.city);
      }
    }
  } catch (e) {
    // Ignore initial poll errors
  }
}

// Initialize application on page load
updateLocationScopeHeaders();
loadLocationData();
loadCRMData();
checkHealth();
checkAndResumeCampaign();

// Background interval updates
setInterval(checkHealth, 15000);


// =========================================================================
// CRM & WEBHOOK DISPATCH CONTROLLER
// =========================================================================

const btnToggleCRMForm = document.getElementById("btnToggleCRMForm");
const btnToggleCRMLogs = document.getElementById("btnToggleCRMLogs");
const crmFormContainer = document.getElementById("crmFormContainer");
const crmLogsContainer = document.getElementById("crmLogsContainer");
const crmDestinationForm = document.getElementById("crmDestinationForm");
const btnTestCRMPing = document.getElementById("btnTestCRMPing");
const btnSyncCurrentCityCRM = document.getElementById("btnSyncCurrentCityCRM");
const crmFormStatus = document.getElementById("crmFormStatus");
const crmDestinationsList = document.getElementById("crmDestinationsList");
const crmLogsTableBody = document.getElementById("crmLogsTableBody");
const crmLogsCount = document.getElementById("crmLogsCount");

if (btnToggleCRMForm && crmFormContainer) {
  btnToggleCRMForm.addEventListener("click", () => {
    const isHidden = crmFormContainer.style.display === "none";
    crmFormContainer.style.display = isHidden ? "block" : "none";
    btnToggleCRMForm.textContent = isHidden ? "✖ Close Form" : "➕ Add Destination";
  });
}

if (btnToggleCRMLogs && crmLogsContainer) {
  btnToggleCRMLogs.addEventListener("click", () => {
    const isHidden = crmLogsContainer.style.display === "none";
    crmLogsContainer.style.display = isHidden ? "block" : "none";
    btnToggleCRMLogs.textContent = isHidden ? "✖ Hide Logs" : `📜 Audit Logs (${crmLogsCount ? crmLogsCount.textContent : '0'})`;
  });
}

if (crmDestinationForm) {
  crmDestinationForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (crmFormStatus) {
      crmFormStatus.style.display = "block";
      crmFormStatus.style.color = "var(--text-subtle)";
      crmFormStatus.textContent = "Saving destination...";
    }

    const payload = {
      customer_name: (document.getElementById("crmCustomerName")?.value || "").trim(),
      crm_type: (document.getElementById("crmTypeSelect")?.value || "webhook").trim(),
      target_url: (document.getElementById("crmTargetUrl")?.value || "").trim(),
      api_key: (document.getElementById("crmApiKey")?.value || "").trim(),
      city_filter: (document.getElementById("crmCityFilter")?.value || "*").trim(),
      auto_sync: Boolean(document.getElementById("crmAutoSync")?.checked),
      is_active: Boolean(document.getElementById("crmIsActive")?.checked),
    };

    try {
      const resp = await fetch("/api/crm/destinations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Failed to save CRM destination.");
      }

      const saved = await resp.json();
      if (crmFormStatus) {
        crmFormStatus.style.color = "#16a34a";
        crmFormStatus.textContent = `Destination "${saved.customer_name}" successfully registered!`;
      }
      crmDestinationForm.reset();
      loadCRMData();
    } catch (err) {
      if (crmFormStatus) {
        crmFormStatus.style.color = "#dc2626";
        crmFormStatus.textContent = `Error: ${err.message}`;
      }
    }
  });
}

if (btnTestCRMPing) {
  btnTestCRMPing.addEventListener("click", async () => {
    const targetUrl = (document.getElementById("crmTargetUrl")?.value || "").trim();
    if (!targetUrl) {
      alert("Please enter a Webhook / API Endpoint URL to test.");
      return;
    }

    if (crmFormStatus) {
      crmFormStatus.style.display = "block";
      crmFormStatus.style.color = "var(--text-subtle)";
      crmFormStatus.textContent = "Pinging endpoint...";
    }

    const payload = {
      target_url: targetUrl,
      crm_type: (document.getElementById("crmTypeSelect")?.value || "webhook").trim(),
      api_key: (document.getElementById("crmApiKey")?.value || "").trim(),
    };

    try {
      const resp = await fetch("/api/crm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const res = await resp.json();
      if (res.connected) {
        if (crmFormStatus) {
          crmFormStatus.style.color = "#16a34a";
          crmFormStatus.textContent = `Ping Successful! (HTTP ${res.status_code}): ${res.response || 'OK'}`;
        }
      } else {
        if (crmFormStatus) {
          crmFormStatus.style.color = "#dc2626";
          crmFormStatus.textContent = `Connection Test Failed: ${res.error || res.message}`;
        }
      }
    } catch (err) {
      if (crmFormStatus) {
        crmFormStatus.style.color = "#dc2626";
        crmFormStatus.textContent = `Network Error: ${err.message}`;
      }
    }
  });
}

if (btnSyncCurrentCityCRM) {
  btnSyncCurrentCityCRM.addEventListener("click", async () => {
    const targetCity = activeCity || "Bhubaneswar";
    if (statusBox) {
      statusBox.className = "status-banner running";
      statusBox.textContent = `Broadcasting ${targetCity} verified leads to active CRM destinations...`;
    }

    try {
      const resp = await fetch("/api/crm/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city: targetCity, limit: 200 }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "CRM Export request failed.");
      }

      const results = await resp.json();
      const count = Array.isArray(results) ? results.length : 1;
      const successes = Array.isArray(results) ? results.filter(r => r.success).length : (results.success ? 1 : 0);

      if (statusBox) {
        statusBox.className = "status-banner success";
        statusBox.textContent = `Dispatched leads to ${count} destination(s) (${successes} succeeded). Check CRM Audit Logs for details.`;
      }
      loadCRMData();
    } catch (err) {
      if (statusBox) {
        statusBox.className = "status-banner error";
        statusBox.textContent = `CRM Dispatch Error: ${err.message}`;
      }
    }
  });
}

async function loadCRMData() {
  try {
    const [destResp, logsResp] = await Promise.all([
      fetch("/api/crm/destinations"),
      fetch("/api/crm/logs?limit=25"),
    ]);

    if (destResp.ok) {
      const dests = await destResp.json();
      renderCRMDestinations(dests);
    }

    if (logsResp.ok) {
      const logs = await logsResp.json();
      renderCRMLogs(logs);
    }
  } catch (err) {
    console.error("Failed to load CRM data:", err);
  }
}

function renderCRMDestinations(destinations) {
  if (!crmDestinationsList) return;

  if (!destinations || destinations.length === 0) {
    crmDestinationsList.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 14px; background: var(--surface-subtle); border-radius: var(--radius-sm); border: 1px dashed var(--border-light); font-size: 13px; color: var(--text-subtle); text-align: center;">
        No customer CRM destinations registered yet. Click "➕ Add Destination" above to connect HubSpot, Zoho, Generic REST, or a Webhook endpoint.
      </div>
    `;
    return;
  }

  crmDestinationsList.innerHTML = destinations.map(dest => {
    const crmBadge = (dest.crm_type || "webhook").toUpperCase();
    const isAuto = dest.auto_sync ? "⚡ Auto-Sync ON" : "Manual Only";
    const isActive = dest.is_active ? "Active" : "Disabled";
    const cityScope = dest.city_filter === "*" ? "All Cities (*)" : dest.city_filter;

    return `
      <div style="background: var(--surface-subtle); border: 1px solid var(--border-light); border-radius: var(--radius-sm); padding: 12px; display: flex; flex-direction: column; justify-content: space-between; gap: 8px;">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <div style="font-weight: 700; font-size: 14px; color: var(--text-black);">${escapeHtml(dest.customer_name)}</div>
            <span style="font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--violet-bg); color: #6d28d9; border: 1px solid var(--violet-border);">
              ${crmBadge}
            </span>
          </div>
          <div style="font-size: 12px; color: var(--text-subtle); word-break: break-all; font-family: var(--font-mono); margin-bottom: 4px;">
            ${escapeHtml(dest.target_url)}
          </div>
          <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 8px; flex-wrap: wrap;">
            <span>📍 ${escapeHtml(cityScope)}</span>
            <span>${isAuto}</span>
          </div>
        </div>

        <div style="display: flex; gap: 6px; margin-top: 6px; justify-content: flex-end;">
          <button class="btn-action-sm btn-violet-outline" style="font-size: 11px; padding: 4px 8px;" onclick="testDestinationPing('${dest.destination_id}')">
            Ping
          </button>
          <button class="btn-action-sm btn-violet-solid" style="font-size: 11px; padding: 4px 8px;" onclick="exportToSingleDestination('${dest.destination_id}')">
            Export ${escapeHtml(activeCity || 'Leads')}
          </button>
          <button class="btn-action-sm btn-violet-outline" style="font-size: 11px; padding: 4px 8px; color: #dc2626;" onclick="deleteCRMDestination('${dest.destination_id}')">
            ✕
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function renderCRMLogs(logs) {
  if (!crmLogsTableBody) return;
  if (crmLogsCount) crmLogsCount.textContent = (logs || []).length;

  if (!logs || logs.length === 0) {
    crmLogsTableBody.innerHTML = `
      <tr>
        <td colspan="6" style="padding: 12px; text-align: center; color: var(--text-subtle);">
          No CRM sync events logged yet.
        </td>
      </tr>
    `;
    return;
  }

  crmLogsTableBody.innerHTML = logs.map(l => {
    const isSuccess = l.status === "success";
    const statusPill = isSuccess
      ? `<span style="color: #16a34a; font-weight: 700;">● OK (${l.status_code || 200})</span>`
      : `<span style="color: #dc2626; font-weight: 700;">✕ FAILED (${l.status_code || 'err'})</span>`;

    const timeFormatted = l.created_at ? l.created_at.substring(11, 19) : "";

    return `
      <tr style="border-bottom: 1px solid var(--border-light);">
        <td style="padding: 6px 12px; font-family: var(--font-mono);">${timeFormatted}</td>
        <td style="padding: 6px 12px; font-weight: 600;">${escapeHtml(l.customer_name || 'Destination')}</td>
        <td style="padding: 6px 12px;">${escapeHtml(l.crm_type || 'webhook')}</td>
        <td style="padding: 6px 12px;">${escapeHtml(l.city || '—')}</td>
        <td style="padding: 6px 12px;">${l.leads_count || 0}</td>
        <td style="padding: 6px 12px;">${statusPill}</td>
      </tr>
    `;
  }).join("");
}

window.testDestinationPing = async function (destId) {
  try {
    const destResp = await fetch(`/api/crm/destinations/${destId}`);
    if (!destResp.ok) throw new Error("Destination not found.");
    const dest = await destResp.json();

    const resp = await fetch("/api/crm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_url: dest.target_url,
        crm_type: dest.crm_type,
        api_key: dest.api_key || "",
      }),
    });
    const res = await resp.json();
    if (res.connected) {
      alert(`Ping to ${dest.customer_name} successful! (HTTP ${res.status_code})`);
    } else {
      alert(`Ping to ${dest.customer_name} failed: ${res.error || res.message}`);
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
};

window.exportToSingleDestination = async function (destId) {
  const targetCity = activeCity || "Bhubaneswar";
  try {
    const resp = await fetch("/api/crm/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destination_id: destId,
        city: targetCity,
        limit: 200,
      }),
    });
    const res = await resp.json();
    if (res.success) {
      alert(`Successfully pushed ${res.leads_count} leads for ${targetCity} (HTTP ${res.status_code})`);
    } else {
      alert(`CRM Push Failed: ${res.error || 'Server error'}`);
    }
    loadCRMData();
  } catch (err) {
    alert(`Export Error: ${err.message}`);
  }
};

window.deleteCRMDestination = async function (destId) {
  if (!confirm("Are you sure you want to remove this CRM destination?")) return;
  try {
    const resp = await fetch(`/api/crm/destinations/${destId}`, { method: "DELETE" });
    if (resp.ok) {
      loadCRMData();
    } else {
      alert("Failed to delete destination.");
    }
  } catch (err) {
    alert(`Delete Error: ${err.message}`);
  }
};

