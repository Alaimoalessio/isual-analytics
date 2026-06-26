document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const kpiGrid = document.getElementById('kpi-grid');
    const dateRangeEl = document.getElementById('kpi-date-range');
    const generateBtn = document.getElementById('generate-btn');
    const exportCsvBtn = document.getElementById('export-csv-btn');
    const reportsBody = document.getElementById('reports-body');
    const alertContainer = document.getElementById('alert-container');
    const spinner = generateBtn.querySelector('.spinner');
    const dbStatusEl = document.getElementById('db-status');
    const themeToggleBtn = document.getElementById('theme-toggle');
    const brandSelect = document.getElementById('brand-select');
    const periodToggle = document.getElementById('period-toggle');
    const periodBtns = periodToggle.querySelectorAll('.period-btn');
    let currentDays = localStorage.getItem('isual_days') || '30';
    const lastUpdateText = document.getElementById('last-update-text');
    const refreshBtn = document.getElementById('refresh-btn');
    const trendChartContainer = document.getElementById('trend-chart-container');
    const metricSwitcher = document.getElementById('metric-switcher');
    const metricBtns = metricSwitcher ? metricSwitcher.querySelectorAll('.metric-btn') : [];
    let currentMetric = 'reach';
    let trendChart = null;
    const partnersGrid = document.getElementById('partners-grid');

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
    exportCsvBtn.addEventListener('click', exportCSV);
    refreshBtn.addEventListener('click', reloadData);
    brandSelect.addEventListener('change', () => {
        localStorage.setItem('isual_brand', brandSelect.value);
        reloadData();
    });
    
    periodBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            periodBtns.forEach(b => b.classList.remove('active'));
            const targetBtn = e.currentTarget;
            targetBtn.classList.add('active');
            currentDays = targetBtn.dataset.days;
            localStorage.setItem('isual_days', currentDays);
            reloadData();
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
        await loadBrands();
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

    async function loadBrands() {
        try {
            const response = await fetch('/api/brands');
            const result = await response.json();
            
            if (result.success && result.data) {
                const savedBrand = localStorage.getItem('isual_brand') || 'all';
                const options = result.data.map(b => `<option value="${b.id}" ${b.id == savedBrand ? 'selected' : ''}>${b.name}</option>`).join('');
                brandSelect.innerHTML = `<option value="all" ${savedBrand === 'all' ? 'selected' : ''}>Tutti i brand</option>${options}`;
            }
        } catch (error) {
            console.error('Error loading brands', error);
        }
    }

    function reloadData() {
        // Initialize active state for period buttons based on currentDays
        periodBtns.forEach(btn => {
            if (btn.dataset.days === currentDays) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
        
        updateTimestamp();
        loadKPIs();
        loadTrendChart();
        loadPartners();
    }

    function updateTimestamp() {
        const now = new Date();
        const dateStr = now.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = now.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
        lastUpdateText.textContent = `Aggiornato il ${dateStr} alle ${timeStr}`;
    }

    function getQueryParams() {
        const brand = brandSelect.value;
        const days = currentDays;
        return `?brand_id=${brand}&days=${days}`;
    }

    async function loadKPIs() {
        kpiGrid.innerHTML = `
            <div class="kpi-card loading"><div class="kpi-label">Network Reach</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Impressions Totali</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Engagement Rate</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Post Pubblicati</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Amplification Factor</div><div class="kpi-value">-</div></div>
            <div class="kpi-card loading"><div class="kpi-label">Network Adoption</div><div class="kpi-value">-</div></div>
        `;

        try {
            const response = await fetch(`/api/kpi${getQueryParams()}`);
            const result = await response.json();

            if (result.success) {
                renderKPIs(result.data);
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

    function renderKPIs(data) {
        dateRangeEl.textContent = `${data.period_label} (${data.date_range})`;
        
        let erClass = data.er_raw >= 3 ? 'positive' : (data.er_raw >= 1 ? 'warning' : 'alert');
        let ampClass = data.amp_raw >= 5 ? 'positive' : (data.amp_raw >= 2 ? 'warning' : 'alert');
        let adpClass = data.adoption_raw >= 70 ? 'positive' : (data.adoption_raw >= 40 ? 'warning' : 'alert');

        kpiGrid.innerHTML = `
            <div class="kpi-card">
                <div class="kpi-label">Network Reach</div>
                <div class="kpi-value-row">
                    <div class="kpi-value">${data.total_reach.value}</div>
                    ${renderTrendIndicator(data.total_reach)}
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Impressions Totali</div>
                <div class="kpi-value-row">
                    <div class="kpi-value">${data.total_impressions.value}</div>
                    ${renderTrendIndicator(data.total_impressions)}
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Engagement Rate</div>
                <div class="kpi-value-row">
                    <div class="kpi-value ${erClass}">${data.engagement_rate.value}</div>
                    ${renderTrendIndicator(data.engagement_rate)}
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Post Pubblicati</div>
                <div class="kpi-value-row">
                    <div class="kpi-value">${data.total_posts.value}</div>
                    ${renderTrendIndicator(data.total_posts)}
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Amplification Factor</div>
                <div class="kpi-value-row">
                    <div class="kpi-value ${ampClass}">${data.amplification.value}</div>
                    ${renderTrendIndicator(data.amplification)}
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Network Adoption</div>
                <div class="kpi-value-row">
                    <div class="kpi-value ${adpClass}">${data.adoption_pct.value}</div>
                    ${renderTrendIndicator(data.adoption_pct)}
                </div>
            </div>
        `;
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
                                <div class="partner-name">${p.partner_name}</div>
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
        if (!reports || reports.length === 0) {
            reportsBody.innerHTML = `<tr><td colspan="4" class="text-center">Nessun report generato finora.</td></tr>`;
            return;
        }

        reportsBody.innerHTML = reports.map(r => `
            <tr>
                <td class="file-name">${r.filename}</td>
                <td>${r.date}</td>
                <td>${r.size_kb} KB</td>
                <td>
                    <a href="/outputs/${r.filename}" target="_blank" class="btn btn-outline btn-sm" download>Scarica PDF</a>
                </td>
            </tr>
        `).join('');
    }

    async function generateReport() {
        generateBtn.disabled = true;
        spinner.classList.remove('hidden');
        
        try {
            const payload = {
                brand_id: brandSelect.value,
                days: parseInt(currentDays)
            };
            
            const response = await fetch('/api/generate', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
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
});
