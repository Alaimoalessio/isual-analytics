document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const kpiGrid = document.getElementById('kpi-grid');
    const dateRangeEl = document.getElementById('kpi-date-range');
    const generateBtn = document.getElementById('generate-btn');
    const exportCsvBtn = document.getElementById('export-csv-btn');
    const reportsBody = document.getElementById('reports-body');
    const alertContainer = document.getElementById('alert-container');
    const syncHealthBanner = document.getElementById('sync-health-banner');
    const spinner = generateBtn.querySelector('.spinner');
    const dbStatusEl = document.getElementById('db-status');
    const themeToggleBtn = document.getElementById('theme-toggle');
    const brandSelect = document.getElementById('brand-select');
    const partnerSelect = document.getElementById('partner-select');
    const tagSelect = document.getElementById('tag-select');
    const targetSelect = document.getElementById('target-select');

    // I tre filtri (partner, tag, target) si popolano allo stesso modo: cambiano
    // solo endpoint, chiave di storage e testo dell'opzione "tutti".
    // Va dichiarato qui: i listener piu' sotto lo leggono in modo sincrono.
    const FILTERS = [
        { key: 'isual_partner', endpoint: '/api/filter/partners', allLabel: 'Tutti i partner', el: () => partnerSelect },
        { key: 'isual_tag',     endpoint: '/api/filter/tags',     allLabel: 'Tutti i tag',     el: () => tagSelect },
        { key: 'isual_target',  endpoint: '/api/filter/targets',  allLabel: 'Tutti i target',  el: () => targetSelect },
    ];

    const periodToggle = document.getElementById('period-toggle');
    const periodBtns = periodToggle.querySelectorAll('.period-btn');
    const selectAllCheckbox = document.getElementById('select-all-reports');
    const bulkDeleteBar = document.getElementById('bulk-delete-bar');
    
    // Variabili per il Drawer della configurazione delle KPI
    // Mi salvo i riferimenti a tutti gli elementi HTML così non devo fare document.getElementById ogni volta
    const btnKpiConfig = document.getElementById('btn-kpi-config');
    const kpiDrawer = document.getElementById('kpi-drawer');
    const kpiDrawerOverlay = document.getElementById('kpi-drawer-overlay');
    const btnCloseDrawer = document.getElementById('btn-close-drawer');
    const kpiSortableList = document.getElementById('kpi-sortable-list');
    const btnSaveKpiConfig = document.getElementById('btn-save-kpi-config');
    const kpiDrawerFeedback = document.getElementById('kpi-drawer-feedback');
    let sortableInstance = null;
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    const selectedCountSpan = document.getElementById('selected-count');
    let currentDays = localStorage.getItem('isual_days') || '30';
    let customDateFrom = null;
    let customDateTo   = null;
    const lastUpdateText = document.getElementById('last-update-text');
    const refreshBtn = document.getElementById('refresh-btn');
    const trendChartContainer = document.getElementById('trend-chart-container');
    const metricSwitcher = document.getElementById('metric-switcher');
    const metricBtns = metricSwitcher ? metricSwitcher.querySelectorAll('.metric-btn') : [];
    let currentMetric = 'reach';
    let trendChart = null;
    const partnersGrid = document.getElementById('partners-grid');
    const topContentBody = document.getElementById('top-content-body');
    const worstContentBody = document.getElementById('worst-content-body');
    const worstContentNote = document.getElementById('worst-content-note');

    // Nomi di brand/partner/tag/target e testi dei post arrivano da fonti esterne
    // (app di terzi, social): vanno escapati prima di finire in innerHTML, altrimenti
    // un valore con markup lo inietta nella pagina.
    // Dichiarata QUI, sopra initDashboard(): loadBrands() la usa, e con la const piu' in
    // basso funzionava solo perche' quella si sospende sul fetch il tempo che la
    // dichiarazione venga eseguita. Dipendere da quel timing e' fragile.
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

    // Theme Initialization
    const savedTheme = localStorage.getItem('isual_theme') || 'light';
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        themeToggleBtn.textContent = '☀️';
    }

    // Initial Load
    initDashboard();

    // Event Listeners
    themeToggleBtn.addEventListener('click', toggleTheme);
    generateBtn.addEventListener('click', generateReport);
    
    // Aggiungo gli Event Listeners per il Drawer delle KPI
    // Controllo se gli elementi esistono con "if", per evitare errori in pagina se non li trovo
    if (btnKpiConfig) {
        btnKpiConfig.addEventListener('click', openKpiDrawer);
    }
    if (btnCloseDrawer) {
        btnCloseDrawer.addEventListener('click', closeKpiDrawer);
    }
    if (kpiDrawerOverlay) {
        kpiDrawerOverlay.addEventListener('click', closeKpiDrawer);
    }
    if (btnSaveKpiConfig) {
        btnSaveKpiConfig.addEventListener('click', saveKpiConfig);
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && kpiDrawer && kpiDrawer.classList.contains('active')) {
            closeKpiDrawer();
        }
    });

    // Riferimento al container per il date picker personalizzato
    const customDateRange = document.getElementById('custom-date-range');

    // bottone Applica — salva le date e ricarica i KPI
    document.getElementById('apply-custom-date').addEventListener('click', () => {
        const from = document.getElementById('date-from').value;
        const to   = document.getElementById('date-to').value;
        if (!from || !to) return;
        if (from > to) {
            alert('La data iniziale deve essere precedente alla finale');
            return;
        }
        customDateFrom = from;
        customDateTo   = to;
        currentDays    = 'custom';
        localStorage.setItem('isual_days', 'custom');
        loadKPIs();
        loadPartners();
        loadTrendChart();
        loadTopContent();
    });

    exportCsvBtn.addEventListener('click', exportCSV);
    refreshBtn.addEventListener('click', reloadData);

    // Bulk Delete Handlers
    selectAllCheckbox.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('.report-checkbox');
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            updateRowStyle(cb);
        });
        updateBulkDeleteButton();
    });

    bulkDeleteBtn.addEventListener('click', async () => {
        const selected = Array.from(document.querySelectorAll('.report-checkbox:checked')).map(cb => cb.value);
        if (selected.length === 0) return;
        
        if (confirm(`Eliminare ${selected.length} file? Azione irreversibile`)) {
            bulkDeleteBtn.disabled = true;
            try {
                const response = await fetch('/api/reports/bulk-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filenames: selected })
                });
                const result = await response.json();
                
                if (result.success) {
                    showAlert(result.message, 'success');
                    loadReports();
                } else {
                    showAlert('Errore: ' + result.error, 'error');
                }
            } catch (error) {
                showAlert('Errore durante l\'eliminazione dei report.', 'error');
                console.error(error);
            } finally {
                bulkDeleteBtn.disabled = false;
            }
        }
    });
    brandSelect.addEventListener('change', async () => {
        localStorage.setItem('isual_brand', brandSelect.value);
        // partner, tag e target appartengono al brand: cambiando brand non hanno piu' senso
        localStorage.setItem('isual_partner', 'all');
        localStorage.setItem('isual_tag', 'all');
        localStorage.setItem('isual_target', 'all');
        await loadFilters();
        reloadData();
    });

    [partnerSelect, tagSelect, targetSelect].forEach(select => {
        if (!select) return;
        const { key } = FILTERS.find(f => f.el() === select);
        select.addEventListener('change', () => {
            localStorage.setItem(key, select.value);
            if (select.value !== 'all') clearOtherFilters(select);
            reloadData();
        });
    });
    
    periodBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            periodBtns.forEach(b => b.classList.remove('active'));
            const targetBtn = e.currentTarget;
            targetBtn.classList.add('active');
            currentDays = targetBtn.dataset.days;
            localStorage.setItem('isual_days', currentDays);
            
            if (currentDays === 'custom') {
                customDateRange.style.display = 'flex';
            } else {
                customDateRange.style.display = 'none';
                reloadData();
            }
        });
    });
    
    metricBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            metricBtns.forEach(b => b.classList.remove('active'));
            const targetBtn = e.currentTarget;
            targetBtn.classList.add('active');
            currentMetric = targetBtn.dataset.metric;
            loadTrendChart();
        });
    });

    // Periodic Health Check (every 30s)
    setInterval(checkDBHealth, 30000);

    // --- Functions ---

    async function initDashboard() {
        checkDBHealth();
        loadSyncHealth();
        await loadBrands();
        await loadFilters();
        reloadData();
        loadReports();
    }

    function toggleTheme() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        if (isDark) {
            document.documentElement.removeAttribute('data-theme');
            localStorage.setItem('isual_theme', 'light');
            themeToggleBtn.textContent = '🌙';
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('isual_theme', 'dark');
            themeToggleBtn.textContent = '☀️';
        }
        if (trendChart) {
            loadTrendChart();
        }
    }

    async function checkDBHealth() {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2000);
            
            const response = await fetch('/api/db-status', { signal: controller.signal });
            clearTimeout(timeoutId);
            const result = await response.json();
            const statusText = dbStatusEl.querySelector('.status-text');

            dbStatusEl.className = 'db-status';
            if (result.success && result.status === 'ok') {
                dbStatusEl.classList.add('ok');
                statusText.textContent = `🟢 DB Online (${result.latency_ms}ms)`;
            } else {
                dbStatusEl.classList.add('error');
                statusText.textContent = '🔴 DB Offline';
            }
        } catch (error) {
            dbStatusEl.className = 'db-status error';
            dbStatusEl.querySelector('.status-text').textContent = '🔴 DB Offline';
        }
    }

    // Banner "il sync metriche di un canale e' fermo".
    // Non e' await-ata in initDashboard: se l'endpoint fallisce o e' lento la
    // dashboard carica comunque, il banner semplicemente non compare. Il caso
    // "tutto ok" non produce nulla — nessun rumore visivo quando va tutto bene.
    async function loadSyncHealth() {
        try {
            const response = await fetch('/api/sync-health');
            const result = await response.json();
            syncHealthBanner.replaceChildren();
            if (!result.success || !result.degraded || result.degraded.length === 0) return;

            const banner = document.createElement('div');
            // 'worst' arriva dal server: la soglia vive in un posto solo
            banner.className = `alert alert-${result.worst === 'alert' ? 'error' : 'warning'}`;

            const icon = document.createElement('span');
            icon.textContent = result.worst === 'alert' ? '⚠️' : '⏳';
            banner.appendChild(icon);

            const list = document.createElement('span');
            result.degraded.forEach(ch => {
                const item = document.createElement('span');
                item.className = 'sync-health-item';

                const name = document.createElement('span');
                name.className = 'sync-health-channel';
                // textContent, non innerHTML: label puo' ricadere sul valore
                // grezzo di publications.social per un canale non mappato
                name.textContent = ch.label;
                item.appendChild(name);

                const detail = document.createElement('span');
                detail.textContent = ch.days_since === null
                    ? ': nessun aggiornamento metriche mai registrato'
                    : `: nessun aggiornamento metriche da ${ch.days_since} ${ch.days_since === 1 ? 'giorno' : 'giorni'}`;
                item.appendChild(detail);

                list.appendChild(item);
            });
            banner.appendChild(list);
            syncHealthBanner.appendChild(banner);
        } catch (error) {
            syncHealthBanner.replaceChildren();
        }
    }

    async function loadBrands() {
        try {
            const response = await fetch('/api/brands');
            const result = await response.json();
            
            if (result.success && result.data) {
                const savedBrand = localStorage.getItem('isual_brand') || 'all';
                const options = result.data.map(b => `<option value="${esc(b.id)}" ${b.id == savedBrand ? 'selected' : ''}>${esc(b.name)}</option>`).join('');
                brandSelect.innerHTML = `<option value="all" ${savedBrand === 'all' ? 'selected' : ''}>Tutti i brand</option>${options}`;
            }
        } catch (error) {
            console.error('Error loading brands', error);
        }
    }

    async function loadFilterOptions({ key, endpoint, allLabel, el }) {
        const select = el();
        if (!select) return;
        try {
            const brand = brandSelect.value;
            let url = endpoint;
            if (brand !== 'all') {
                url += `?brand_id=${brand}`;
            }
            const response = await fetch(url);
            const result = await response.json();

            if (result.success && result.data) {
                const saved = localStorage.getItem(key) || 'all';
                const hasSaved = result.data.some(o => o.id == saved);
                const finalValue = hasSaved ? saved : 'all';
                if (!hasSaved) localStorage.setItem(key, 'all');

                const options = result.data.map(o =>
                    `<option value="${esc(o.id)}" ${o.id == finalValue ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
                select.innerHTML = `<option value="all" ${finalValue === 'all' ? 'selected' : ''}>${allLabel}</option>${options}`;
            }
        } catch (error) {
            console.error(`Error loading filter ${endpoint}`, error);
        }
    }

    async function loadFilters() {
        await Promise.all(FILTERS.map(loadFilterOptions));
    }

    // I tre filtri sono alternativi: il backend applica partner > tag > target,
    // quindi lasciarne due attivi mostrerebbe una selezione che non e' quella usata.
    function clearOtherFilters(activeSelect) {
        FILTERS.forEach(({ key, el }) => {
            const select = el();
            if (select && select !== activeSelect) {
                select.value = 'all';
                localStorage.setItem(key, 'all');
            }
        });
    }

    let lastUpdateDate = new Date();

    async function reloadData() {
        // Initialize active state for period buttons based on currentDays
        periodBtns.forEach(btn => {
            if (btn.dataset.days === currentDays) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
        
        if (currentDays === 'custom') {
            customDateRange.style.display = 'flex';
        } else {
            customDateRange.style.display = 'none';
        }
        
        const refreshIcon = refreshBtn.querySelector('.refresh-icon');
        if (refreshIcon) refreshIcon.classList.add('spinning');

        try {
            await Promise.all([
                loadKPIs(),
                loadTrendChart(),
                loadPartners(),
                loadTopContent()
            ]);
            updateTimestamp();
        } finally {
            if (refreshIcon) refreshIcon.classList.remove('spinning');
        }
    }

    function updateTimestamp() {
        lastUpdateDate = new Date();
        const dateStr = lastUpdateDate.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = lastUpdateDate.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
        lastUpdateText.setAttribute('title', `Aggiornato il ${dateStr} alle ${timeStr}`);
        renderRelativeTime();
    }

    function renderRelativeTime() {
        const now = new Date();
        const diffMs = now - lastUpdateDate;
        const diffMins = Math.floor(diffMs / 60000);
        
        if (diffMins < 1) {
            lastUpdateText.textContent = `Aggiornato pochi secondi fa`;
        } else if (diffMins === 1) {
            lastUpdateText.textContent = `Aggiornato 1 minuto fa`;
        } else {
            lastUpdateText.textContent = `Aggiornato ${diffMins} minuti fa`;
        }
    }

    // Aggiorna il testo relativo ogni minuto
    setInterval(renderRelativeTime, 60000);

    function getQueryParams() {
        const brand = brandSelect.value;
        const partner = partnerSelect ? partnerSelect.value : 'all';
        const tag = tagSelect ? tagSelect.value : 'all';
        const target = targetSelect ? targetSelect.value : 'all';
        let query = `?brand_id=${brand}&partner_id=${partner}&tag_id=${tag}&target_id=${target}`;
        if (currentDays === 'custom' && customDateFrom && customDateTo) {
            query += `&date_from=${customDateFrom}&date_to=${customDateTo}`;
        } else {
            query += `&days=${currentDays}`;
        }
        return query;
    }

    async function loadKPIs() {
        kpiGrid.innerHTML = `
            <div class="kpi-card loading"><div class="kpi-label">Network Reach</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Impressions Totali</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Engagement Totale</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Post Pubblicati</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Engagement Rate</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Amplification Factor</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Network Adoption</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Frequency</div><div class="kpi-value">-</div></div>
        `;

        try {
            const [kpiResponse, configResponse] = await Promise.all([
                fetch(`/api/kpi${getQueryParams()}`),
                fetch('/api/kpi-config/all')
            ]);
            
            const result = await kpiResponse.json();
            const configResult = await configResponse.json().catch(() => ({}));

            if (result.success) {
                let hiddenCount = 0;
                if (configResult && configResult.success && configResult.kpi_config) {
                    hiddenCount = configResult.kpi_config.filter(k => !k.visibile).length;
                }
                renderKPIs(result.data, result.kpi_config, hiddenCount);
            } else {
                showError('Errore nel caricamento KPI: ' + result.error);
                kpiGrid.innerHTML = '<div class="kpi-card"><div class="kpi-label">Errore</div><div class="kpi-value alert">ND</div></div>';
            }
        } catch (error) {
            showError('Impossibile connettersi al server per i KPI.');
            console.error(error);
        }
    }

    function renderTrendIndicator(metricObj) {
        if (!metricObj || metricObj.trend === null || metricObj.trend === undefined) {
            return `<span class="kpi-trend neutral" title="vs periodo precedente">N/D</span>`;
        }
        
        const value = parseFloat(metricObj.trend).toFixed(1);
        const direction = metricObj.direction;
        if (direction === 'up') {
            return `<span class="kpi-trend positive" title="vs periodo precedente">↑ +${value}%</span>`;
        } else if (direction === 'down') {
            return `<span class="kpi-trend negative" title="vs periodo precedente">↓ ${value}%</span>`;
        } else {
            return `<span class="kpi-trend neutral" title="vs periodo precedente">→ 0.0%</span>`;
        }
    }

    function renderKPIs(data, kpiConfig, hiddenCount = 0) {
        dateRangeEl.textContent = `${data.period_label} (${data.date_range})`;

        const badge = document.getElementById('kpi-hidden-badge');
        if (badge) {
            if (hiddenCount > 0) {
                badge.textContent = `(${hiddenCount} nascoste)`;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }

        // classi colore-soglia (soglie invariate rispetto a prima)
        // Amplification non ne ha piu' una: e' una metrica di composizione e va neutra,
        // come Frequency (vedi report.py). Le vecchie soglie erano tarate sul
        // moltiplicatore (>=5x, >=2x) e sulla scala 0-100% avrebbero colorato di verde
        // qualsiasi valore sopra il 5%.
        const erClass  = data.er_raw >= 3 ? 'positive' : (data.er_raw >= 1 ? 'warning' : 'alert');
        const adpClass = data.adoption_raw >= 70 ? 'positive' : (data.adoption_raw >= 40 ? 'warning' : 'alert');

        // Network Adoption è una metrica di rete: con un singolo partner filtrato è "N/A".
        // In quel caso la mostro neutra, senza colore-soglia né indicatore trend.
        const adpNeutral = data.network_scope_na;

        // Amplification: "N/A" con filtro attivo, oppure quando non c'è alcun reach
        // misurato nel periodo (né partner né brand). La card è sempre senza colore;
        // questo flag serve solo a sopprimere anche l'indicatore di trend, che su un
        // "N/A" non ha niente da confrontare.
        const ampNeutral = data.amp_scope_na;

        // descrittore per kpi_key: valore, classe colore, html del trend.
        // Tutti i casi speciali stanno qui, così il loop sotto resta uniforme.
        const cards = {
            reach:                { value: data.total_reach.value,       cls: '',       trend: renderTrendIndicator(data.total_reach) },
            impressions:          { value: data.total_impressions.value, cls: '',       trend: renderTrendIndicator(data.total_impressions) },
            engagement_total:     { value: data.total_engagement.value,  cls: '',       trend: renderTrendIndicator(data.total_engagement) },
            post_pubblicati:      { value: data.total_posts.value,       cls: '',       trend: renderTrendIndicator(data.total_posts) },
            engagement_rate:      { value: data.engagement_rate.value,   cls: erClass,  trend: renderTrendIndicator(data.engagement_rate) },
            amplification_factor: { value: data.amplification.value,     cls: '',
                                    trend: ampNeutral ? '' : renderTrendIndicator(data.amplification) },
            network_adoption:     { value: data.adoption_pct.value,      cls: adpNeutral ? '' : adpClass,
                                    trend: adpNeutral ? '' : renderTrendIndicator(data.adoption_pct) },
            frequency:            { value: data.frequency.value,         cls: '',       trend: renderTrendIndicator(data.frequency) },
        };

        // loop sulla config dal backend: una card per kpi_key visibile, nell'ordine dato.
        // etichetta dalla config, valore/stile dal descrittore (accoppiati per kpi_key).
        kpiGrid.innerHTML = kpiConfig.map(item => {
            const c = cards[item.kpi_key];
            if (!c) return '';  // kpi_key non riconosciuta: salto (difensivo)
            return `
            <div class="kpi-card">
                <div class="kpi-label">${item.etichetta}</div>
                <div class="kpi-value-row">
                    <div class="kpi-value ${c.cls}">${c.value}</div>
                    ${c.trend}
                </div>
            </div>`;
        }).join('');
    }

    async function loadTrendChart() {
        if (!document.getElementById('trend-canvas')) {
            trendChartContainer.innerHTML = '<canvas id="trend-canvas"></canvas>';
        }
        
        try {
            const response = await fetch(`/api/trend-chart${getQueryParams()}&metric=${currentMetric}`);
            const result = await response.json();
            
            if (result.success && result.data && result.data.length > 0) {
                renderChart(result.data);
            } else {
                if (trendChart) {
                    trendChart.destroy();
                    trendChart = null;
                }
                trendChartContainer.innerHTML = '<div class="loading-text">Dati insufficienti per il trend</div>';
            }
        } catch (error) {
            trendChartContainer.innerHTML = '<div class="loading-text alert">Errore caricamento grafico</div>';
        }
    }

    function renderChart(data) {
        const ctx = document.getElementById('trend-canvas');
        if (!ctx) return;
        
        const labels = data.map(d => {
            const dateObj = new Date(d.date);
            return dateObj.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
        });
        const values = data.map(d => d.value);
        
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#E6EDF3' : '#6C757D';
        const gridColor = isDark ? '#30363D' : '#DEE2E6';

        if (trendChart) {
            trendChart.data.labels = labels;
            trendChart.data.datasets[0].data = values;
            trendChart.data.datasets[0].label = currentMetric.charAt(0).toUpperCase() + currentMetric.slice(1);
            trendChart.options.scales.x.ticks.color = textColor;
            trendChart.options.scales.y.ticks.color = textColor;
            trendChart.options.scales.x.grid.color = gridColor;
            trendChart.options.scales.y.grid.color = gridColor;
            trendChart.update();
        } else {
            trendChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: currentMetric.charAt(0).toUpperCase() + currentMetric.slice(1),
                        data: values,
                        borderColor: '#3B5BDB',
                        backgroundColor: 'rgba(59, 91, 219, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        pointHoverRadius: 5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            ticks: { color: textColor },
                            grid: { color: gridColor, drawBorder: false }
                        },
                        y: {
                            ticks: { 
                                color: textColor,
                                callback: function(value) {
                                    if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
                                    if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
                                    return value;
                                }
                            },
                            grid: { color: gridColor, drawBorder: false }
                        }
                    }
                }
            });
        }
    }

    async function loadPartners() {
        partnersGrid.innerHTML = '<div class="loading-text">Caricamento partner...</div>';
        try {
            const response = await fetch(`/api/top-partners${getQueryParams()}`);
            const result = await response.json();
            
            if (result.success) {
                if (result.data.length === 0) {
                    partnersGrid.innerHTML = '<div class="loading-text">Nessun dato partner per il periodo selezionato</div>';
                    return;
                }
                
                partnersGrid.innerHTML = result.data.map(p => {
                    let healthClass = '';
                    if (p.classification === 'Top Performer') healthClass = 'good';
                    else if (p.classification === 'Amplifier') healthClass = 'avg';
                    else if (p.classification === 'Quality Niche') healthClass = 'warning-orange';
                    else healthClass = 'bad';
                    
                    let erClass = parseFloat(p.er) >= 3 ? 'positive' : (parseFloat(p.er) >= 1 ? 'warning' : 'alert');
                    
                    return `
                        <div class="partner-card">
                            <div class="partner-header">
                                <div class="partner-name">${esc(p.partner_name)}</div>
                                <div class="partner-badge ${healthClass}">${p.classification}</div>
                            </div>
                            <div class="partner-stats">
                                <div>
                                    <div class="p-stat-label">Reach</div>
                                    <div class="p-stat-value">${p.reach_fmt}</div>
                                </div>
                                <div>
                                    <div class="p-stat-label">ER</div>
                                    <div class="p-stat-value ${erClass}">${p.er_fmt}</div>
                                </div>
                            </div>
                            <div class="health-bar-container">
                                <div class="health-bar-labels">
                                    <span>Health Score</span>
                                    <span>${p.health_score}/100</span>
                                </div>
                                <div class="health-bar-bg">
                                    <div class="health-bar-fill ${healthClass}" style="width: ${p.health_score}%"></div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                partnersGrid.innerHTML = '<div class="loading-text alert">Errore caricamento partner</div>';
            }
        } catch (error) {
            partnersGrid.innerHTML = '<div class="loading-text alert">Errore connessione server</div>';
        }
    }

    // Una sola fetch popola Top e Worst. Non e' un'ottimizzazione: le due tabelle
    // devono essere mutuamente esclusive, e questo e' garantito solo se nascono
    // dalla stessa classifica calcolata sullo stesso snapshot di dati.
    // Conseguenza pratica: non c'e' un secondo loader da ricordarsi di aggiungere
    // ai due punti di refresh (apply-custom-date e il Promise.all di reloadData).
    async function loadTopContent() {
        const placeholder = (msg, cls = 'loading-text') =>
            `<tr><td colspan="8" class="text-center ${cls}">${msg}</td></tr>`;

        // stesse soglie del PDF (templates/report.html): parita' visiva tra
        // dashboard e report per lo stesso brand/filtro/periodo
        const renderRows = rows => rows.map(c => {
            let erColor;
            if (c.er_post >= 3.0)      erColor = 'var(--green-positive)';
            else if (c.er_post >= 1.5) erColor = 'var(--orange-warning)';
            else                       erColor = 'var(--red-alert)';

            return `
                <tr>
                    <td class="nowrap">${esc(c.date_fmt)}</td>
                    <td>
                        <span class="rank-badge">${c.rank}</span>
                        <span style="font-weight: 600;">${esc(c.title_short)}</span>
                    </td>
                    <td>${esc(c.channel_upper)}</td>
                    <td style="text-align: right;">${c.reach_fmt}</td>
                    <td style="text-align: right;">${c.impr_fmt}</td>
                    <td style="text-align: right; color: ${erColor}; font-weight: 600;">${c.er_fmt}</td>
                    <td style="text-align: right; font-weight: 600;">${c.score_fmt}</td>
                    <td class="partner-names">${(c.partner_names && c.partner_names.length)
                        ? c.partner_names.map(n => `<div>${esc(n)}</div>`).join('')
                        : '—'}</td>
                </tr>
            `;
        }).join('');

        topContentBody.innerHTML = placeholder('Caricamento contenuti...');
        worstContentBody.innerHTML = placeholder('Caricamento contenuti...');
        worstContentNote.style.display = 'none';
        try {
            const response = await fetch(`/api/top-content${getQueryParams()}`);
            const result = await response.json();

            if (result.success) {
                const worst = result.worst || [];
                const total = result.total_content || 0;

                topContentBody.innerHTML = result.data.length
                    ? renderRows(result.data)
                    : placeholder('Nessun contenuto per il periodo selezionato');

                if (worst.length) {
                    worstContentBody.innerHTML = renderRows(worst);
                    // pool residuo piu' corto di 3: senza nota sembrerebbe un troncamento
                    if (worst.length < 3) {
                        const n = worst.length;
                        worstContentNote.textContent =
                            `Solo ${n} ${n === 1 ? 'contenuto' : 'contenuti'} oltre i ` +
                            `${result.data.length} di Top Content nel periodo selezionato.`;
                        worstContentNote.style.display = 'block';
                    }
                } else if (total === 0) {
                    worstContentBody.innerHTML = placeholder('Nessun contenuto per il periodo selezionato');
                } else {
                    // contenuti presenti ma tutti gia' mostrati sopra: causa diversa,
                    // messaggio diverso (stesso criterio della Leaderboard nel PDF)
                    worstContentBody.innerHTML = placeholder(
                        `${total} ${total === 1 ? 'contenuto' : 'contenuti'} nel periodo, ` +
                        `${total === 1 ? 'già mostrato' : 'già mostrati'} per intero in Top Content`);
                }
            } else {
                topContentBody.innerHTML = placeholder('Errore caricamento contenuti', 'alert');
                worstContentBody.innerHTML = placeholder('Errore caricamento contenuti', 'alert');
            }
        } catch (error) {
            topContentBody.innerHTML = placeholder('Errore connessione server', 'alert');
            worstContentBody.innerHTML = placeholder('Errore connessione server', 'alert');
        }
    }

    async function loadReports() {
        try {
            const response = await fetch('/api/reports');
            const result = await response.json();

            if (result.success) {
                renderReports(result.data);
            } else {
                reportsBody.innerHTML = `<tr><td colspan="4" class="text-center">Errore nel caricamento: ${result.error}</td></tr>`;
            }
        } catch (error) {
            reportsBody.innerHTML = `<tr><td colspan="4" class="text-center">Impossibile connettersi al server per lo storico.</td></tr>`;
            console.error(error);
        }
    }

    function renderReports(reports) {
        // Reset master checkbox and hide bulk delete bar
        selectAllCheckbox.checked = false;
        if(bulkDeleteBar) bulkDeleteBar.style.display = 'none';
        selectedCountSpan.textContent = '0';

        if (!reports || reports.length === 0) {
            reportsBody.innerHTML = `<tr><td colspan="5" class="text-center">Nessun report generato finora.</td></tr>`;
            return;
        }

        reportsBody.innerHTML = reports.map(r => `
            <tr class="report-row">
                <td style="text-align: center;">
                    <input type="checkbox" class="report-checkbox" value="${r.filename}" style="cursor: pointer;">
                </td>
                <td class="file-name">${r.filename}</td>
                <td>${r.date}</td>
                <td>${r.size_kb} KB</td>
                <td style="display: flex; gap: 8px; align-items: center;">
                    <a href="/outputs/${r.filename}" target="_blank" class="btn btn-outline btn-sm" download>Scarica PDF</a>
                    <button class="btn btn-outline btn-sm btn-icon btn-delete row-action-delete" data-filename="${r.filename}" title="Elimina Report" style="padding: 0.25rem 0.5rem; font-size: 14px;">🗑️</button>
                </td>
            </tr>
        `).join('');

        // Attach event listeners for delete buttons
        document.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const filename = e.currentTarget.dataset.filename;
                if(confirm(`Eliminare 1 file? Azione irreversibile`)) {
                    await deleteReport(filename);
                }
            });
        });

        // Attach event listeners for individual checkboxes
        document.querySelectorAll('.report-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                updateRowStyle(e.target);
                updateBulkDeleteButton();
                
                // Update master checkbox state
                const allCheckboxes = document.querySelectorAll('.report-checkbox');
                const allChecked = Array.from(allCheckboxes).every(c => c.checked);
                const someChecked = Array.from(allCheckboxes).some(c => c.checked);
                
                selectAllCheckbox.checked = allChecked;
                selectAllCheckbox.indeterminate = someChecked && !allChecked;
            });
        });
    }

    function updateRowStyle(checkbox) {
        const row = checkbox.closest('tr');
        if (checkbox.checked) {
            row.style.backgroundColor = 'rgba(224, 49, 49, 0.05)';
        } else {
            row.style.backgroundColor = '';
        }
    }

    function updateBulkDeleteButton() {
        const selectedCount = document.querySelectorAll('.report-checkbox:checked').length;
        selectedCountSpan.textContent = selectedCount;
        
        if (selectedCount > 0) {
            if(bulkDeleteBar) bulkDeleteBar.style.display = 'flex';
        } else {
            if(bulkDeleteBar) bulkDeleteBar.style.display = 'none';
        }
    }

    async function deleteReport(filename) {
        try {
            const response = await fetch(`/api/reports/${filename}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                showAlert(result.message, 'success');
                loadReports();
            } else {
                showAlert('Errore: ' + result.error, 'error');
            }
        } catch (error) {
            showAlert('Errore durante l\'eliminazione del report.', 'error');
            console.error(error);
        }
    }

    async function generateReport() {
        generateBtn.disabled = true;
        spinner.classList.remove('hidden');
        
        try {
            // stessi filtri della vista a schermo: il PDF deve riprodurre esattamente
            // i numeri mostrati nella dashboard
            const body = {
                brand_id: brandSelect.value,
                partner_id: partnerSelect ? partnerSelect.value : 'all',
                tag_id: tagSelect ? tagSelect.value : 'all',
                target_id: targetSelect ? targetSelect.value : 'all',
            };
            // aggiunge periodo: custom date o days
            if (currentDays === 'custom') {
                if (!customDateFrom || !customDateTo) {
                    alert('Seleziona un intervallo di date e premi "Applica" prima di generare il report.');
                    generateBtn.disabled = false;
                    spinner.classList.add('hidden');
                    return;
                }
                body.date_from = customDateFrom;
                body.date_to   = customDateTo;
            } else {
                body.days = parseInt(currentDays);
            }
            
            const response = await fetch('/api/generate', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const result = await response.json();

            if (result.success) {
                showAlert(result.message, 'success');
                loadReports();
            } else {
                showAlert('Errore: ' + result.error, 'error');
            }
        } catch (error) {
            showAlert('Errore di connessione durante la generazione.', 'error');
            console.error(error);
        } finally {
            generateBtn.disabled = false;
            spinner.classList.add('hidden');
        }
    }

    async function exportCSV() {
        const btn = exportCsvBtn;
        const spinner = btn.querySelector('.spinner');
        
        btn.disabled = true;
        if(spinner) spinner.classList.remove('hidden');
        
        try {
            const url = `/api/export-csv${getQueryParams()}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                const result = await response.json().catch(() => ({}));
                throw new Error(result.error || 'Errore nel download del CSV');
            }
            
            const blob = await response.blob();
            
            let filename = `isual_export_${new Date().toISOString().slice(0,10)}.csv`;
            const disposition = response.headers.get('Content-Disposition');
            if (disposition && disposition.indexOf('filename=') !== -1) {
                filename = disposition.split('filename=')[1].replace(/"/g, '');
            }
            
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);
            
        } catch (error) {
            showError(error.message);
        } finally {
            btn.disabled = false;
            if(spinner) spinner.classList.add('hidden');
        }
    }

    function showAlert(message, type) {
        const alertEl = document.createElement('div');
        alertEl.className = `alert alert-${type}`;
        alertEl.innerHTML = `
            <span>${message}</span>
            <button class="alert-close">&times;</button>
        `;
        
        alertEl.querySelector('.alert-close').addEventListener('click', () => {
            alertEl.remove();
        });

        alertContainer.prepend(alertEl);
        
        setTimeout(() => {
            if (document.body.contains(alertEl)) {
                alertEl.remove();
            }
        }, 5000);
    }
    
    function showError(message) {
        showAlert(message, 'error');
    }

    // --- Funzioni per far funzionare il Drawer della configurazione delle KPI ---

    // Questa funzione serve per aprire il pannello laterale quando l'utente clicca sull'ingranaggio
    async function openKpiDrawer() {
        // Aggiungo la classe 'active' al drawer e all'overlay per farli apparire con l'animazione CSS
        kpiDrawer.classList.add('active');
        kpiDrawerOverlay.classList.add('active');
        kpiDrawerFeedback.textContent = 'Caricamento configurazione...';
        kpiDrawerFeedback.className = 'kpi-drawer-feedback';
        kpiSortableList.innerHTML = '';
        
        if (sortableInstance) {
            sortableInstance.destroy();
            sortableInstance = null;
        }

        try {
            // Faccio la chiamata GET all'endpoint che abbiamo creato sul backend per prenderci 
            // tutte e 8 le KPI (sia quelle visibili che quelle nascoste)
            const response = await fetch('/api/kpi-config/all');
            const result = await response.json(); // Trasformo la risposta da JSON a oggetto Javascript
            
            if (result.success && result.kpi_config) {
                kpiDrawerFeedback.textContent = ''; // Tolgo il messaggio di caricamento
                
                // Chiamo la funzione che disegna materialmente le righe in HTML
                renderSortableList(result.kpi_config);
                
                // Inizializzo la libreria esterna SortableJS passandogli la lista, 
                // così l'utente può trascinare le righe col mouse per riordinarle!
                sortableInstance = new Sortable(kpiSortableList, {
                    handle: '.drag-handle', // Questo serve per fare in modo che si trascini solo cliccando sull'icona della maniglia
                    animation: 150,
                    ghostClass: 'sortable-ghost'
                });
            } else {
                kpiDrawerFeedback.textContent = 'Errore nel caricamento della configurazione.';
                kpiDrawerFeedback.className = 'kpi-drawer-feedback error';
            }
        } catch (error) {
            kpiDrawerFeedback.textContent = 'Errore di connessione al server.';
            kpiDrawerFeedback.className = 'kpi-drawer-feedback error';
            console.error(error);
        }
    }

    // Questa funzione toglie le classi 'active' così il CSS fa scomparire il pannello
    function closeKpiDrawer() {
        kpiDrawer.classList.remove('active');
        kpiDrawerOverlay.classList.remove('active');
    }

    // Questa funzione prende l'array di configurazione dal backend e lo trasforma in HTML
    // Poi lo inserisce dentro la lista (l'elemento ul) con un ciclo map
    function renderSortableList(configItems) {
        kpiSortableList.innerHTML = configItems.map(item => `
            <li class="kpi-sortable-item" data-key="${item.kpi_key}">
                <div class="drag-handle" title="Trascina per riordinare">☰</div>
                <div class="kpi-item-label">${item.etichetta}</div>
                <label class="toggle-switch" title="Mostra/Nascondi">
                    <input type="checkbox" class="kpi-visibility-toggle" ${item.visibile ? 'checked' : ''}>
                    <span class="slider"></span>
                </label>
            </li>
        `).join('');
    }

    // Questa funzione viene chiamata quando l'utente clicca su "Salva configurazione"
    async function saveKpiConfig() {
        const btn = btnSaveKpiConfig;
        const spinner = btn.querySelector('.spinner');
        
        btn.disabled = true;
        if(spinner) spinner.classList.remove('hidden');
        kpiDrawerFeedback.textContent = '';
        kpiDrawerFeedback.className = 'kpi-drawer-feedback';

        // Qui prendo tutte le righe HTML nell'ordine ESATTO in cui si trovano adesso nello schermo (dopo che l'utente le ha trascinate)
        const items = Array.from(kpiSortableList.querySelectorAll('.kpi-sortable-item'));
        
        // Faccio un ciclo su ogni riga per estrarre la chiave e vedere se il checkbox è selezionato o no
        const kpi_order = items.map(item => {
            return {
                kpi_key: item.dataset.key, // Uso il data-key che avevo messo nell'HTML per ricordarmi il nome
                visibile: item.querySelector('.kpi-visibility-toggle').checked // Questo è true o false
            };
        });

        try {
            // Mando tutto l'array al server tramite POST così il backend lo salva nel database!
            const response = await fetch('/api/kpi-config/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ kpi_order })
            });
            const result = await response.json();

            if (result.success) {
                kpiDrawerFeedback.textContent = 'Configurazione salvata con successo ✓';
                kpiDrawerFeedback.className = 'kpi-drawer-feedback success';
                
                // Ricarica la dashboard per applicare le modifiche
                loadKPIs();
                
                setTimeout(() => {
                    closeKpiDrawer();
                }, 1000);
            } else {
                kpiDrawerFeedback.textContent = 'Errore: ' + (result.error || 'Salvataggio fallito');
                kpiDrawerFeedback.className = 'kpi-drawer-feedback error';
            }
        } catch (error) {
            kpiDrawerFeedback.textContent = 'Errore di connessione durante il salvataggio.';
            kpiDrawerFeedback.className = 'kpi-drawer-feedback error';
            console.error(error);
        } finally {
            btn.disabled = false;
            if(spinner) spinner.classList.add('hidden');
        }
    }
});
