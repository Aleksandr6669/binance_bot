function formatDateTimeToLocal(utcString) {
    if (!utcString) return '';
    let isoString = utcString;
    if (!utcString.includes('Z') && !utcString.includes('+') && String(utcString).match(/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}$/)) {
        isoString = utcString.replace(' ', 'T') + 'Z';
    }
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return utcString;
    const pad = (num) => String(num).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function renderRecommendation(recommendation) {
    const badgeEl = document.getElementById('signal-action-badge');
    const summaryEl = document.getElementById('signal-summary');
    const detailsEl = document.getElementById('signal-details');
    if (!badgeEl || !summaryEl || !detailsEl) return;

    if (!recommendation) {
        badgeEl.className = 'badge badge-secondary';
        badgeEl.textContent = 'WAITING';
        summaryEl.textContent = 'Waiting for AI signal...';
        detailsEl.textContent = 'The model will publish its next preferred entry here every second.';
        return;
    }

    if (recommendation.success === false) {
        badgeEl.className = 'badge badge-danger';
        badgeEl.textContent = 'ERROR';
        summaryEl.textContent = 'Ошибка инференса ИИ';
        detailsEl.innerHTML = `<span style="color: var(--accent-red); font-size: 0.8rem;">${recommendation.error || 'Неизвестная ошибка'}</span>`;
        return;
    }

    const action = recommendation.action || 'HOLD';
    let badgeClass = 'badge-secondary';
    if (action === 'BUY') badgeClass = 'badge-success';
    else if (action === 'SELL') badgeClass = 'badge-danger';
    else badgeClass = 'badge-warning';

    badgeEl.className = `badge ${badgeClass}`;
    badgeEl.textContent = action;
    summaryEl.textContent = recommendation.order_msg || recommendation.reason || 'No signal yet.';

    const probabilityText = recommendation.probability !== undefined ? `Prob: ${(recommendation.probability * 100).toFixed(1)}%` : 'Prob: N/A';
    const priceText = recommendation.price ? `Target: $${Number(recommendation.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : 'Target: N/A';
    const trendText = recommendation.trend_direction || 'UP';
    detailsEl.innerHTML = `<strong>${recommendation.pair || ''}</strong> • ${priceText} • ${probabilityText} • Trend: ${trendText}`;
}

// Initialize analysis logs data structure
window.analysisHistoryLogs = {};
window.isViewingHistoricalLog = false;
window.latestLiveLog = null;

function formatStage3Output(s3) {
    try {
        const obj = typeof s3 === 'string' ? JSON.parse(s3) : s3;
        const actionClass = obj.action === 'BUY' ? 'badge-success' : (obj.action === 'SELL' ? 'badge-danger' : 'badge-warning');
        
        let orderTypeBadge = '';
        if (obj.order_type === 'MARKET') {
            orderTypeBadge = `<span class="badge badge-primary" style="font-size: 0.7rem;">MARKET</span>`;
        } else if (obj.order_type === 'LIMIT') {
            orderTypeBadge = `<span class="badge" style="background: var(--accent-gold); color: #000; font-size: 0.7rem;">LIMIT</span>`;
        }
        
        const prob = obj.probability !== undefined ? (obj.probability * 100).toFixed(2) + '%' : 'N/A';
        const price = obj.price !== undefined ? '$' + Number(obj.price).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) : 'N/A';
        
        return `
            <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); font-family: 'Outfit', sans-serif;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
                    <span class="badge ${actionClass}" style="font-size: 0.85rem;">${obj.action || 'HOLD'}</span>
                    ${orderTypeBadge}
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 0.75rem;">
                    <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 6px;">
                        <div style="font-size: 0.65rem; color: var(--text-secondary); text-transform: uppercase;">Цель (Price)</div>
                        <div style="font-size: 0.9rem; font-weight: 700;">${price}</div>
                    </div>
                    <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 6px;">
                        <div style="font-size: 0.65rem; color: var(--text-secondary); text-transform: uppercase;">Уверенность</div>
                        <div style="font-size: 0.9rem; font-weight: 700; color: var(--accent-cyan);">${prob}</div>
                    </div>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-secondary); line-height: 1.4; padding: 0.5rem; background: rgba(255,255,255,0.01); border-left: 2px solid var(--surface-border); border-radius: 4px;">
                    ${obj.reason || 'Нет описания'}
                </div>
            </div>
        `;
    } catch (e) {
        // Fallback to pre if parsing fails
        return `<pre style="font-family: monospace; font-size: 0.8rem; background: rgba(0,0,0,0.2); padding: 0.5rem; border-radius: 6px; white-space: pre-wrap;">${s3}</pre>`;
    }
}

function updateStageLogs(latest_log) {
    if (!latest_log) return;
    
    // Store latest log in global variable to allow resetting to it
    window.latestLiveLog = latest_log;
    
    // If the user is currently viewing a historical log, do not auto-overwrite the cards
    if (window.isViewingHistoricalLog) return;
    
    const container = document.getElementById('stages-container');
    if (!container) return;

    const s1 = latest_log.stage1_output || '';
    const s2 = latest_log.stage2_output || '';
    const s3 = latest_log.stage3_output || '';
    const created = formatDateTimeToLocal(latest_log.created_at) || '';

    const trans = window.dashboardSettings ? window.dashboardSettings.translations : {
        stage1_title: 'Этап 1',
        stage2_title: 'Этап 2',
        stage3_title: 'Этап 3'
    };

    container.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 1rem; height: 100%;">
            <div class="stage-card" style="flex: 1;">
                <div class="stage-title" style="color: var(--accent-gold);">
                    <span>${trans.stage1_title}</span>
                    <i class="fa-solid fa-magnifying-glass-chart"></i>
                </div>
                <div class="stage-body" style="white-space: pre-wrap;">${s1}</div>
            </div>
            <div class="stage-card stage-2" style="flex: 1;">
                <div class="stage-title" style="color: var(--accent-cyan);">
                    <span>${trans.stage2_title}</span>
                    <i class="fa-solid fa-chess"></i>
                </div>
                <div class="stage-body" style="white-space: pre-wrap;">${s2}</div>
            </div>
        </div>
        <div class="stage-card stage-3" style="display: flex; flex-direction: column; height: 100%; justify-content: space-between;">
            <div class="stage-title" style="color: var(--accent-green);">
                <span>${trans.stage3_title}</span>
                <i class="fa-solid fa-list-check"></i>
            </div>
            <div class="stage-body" style="flex: 1; display: flex; flex-direction: column; justify-content: center;">
                ${formatStage3Output(s3)}
                <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:0.75rem; text-align: right;">${created}</div>
            </div>
        </div>
    `;
}

function viewAnalysisLogDetails(logId) {
    const log = window.analysisHistoryLogs[logId];
    if (!log) return;
    
    window.isViewingHistoricalLog = true;
    
    // Show the "Return to Live" button
    const resetBtn = document.getElementById('reset-to-live-log-btn');
    if (resetBtn) resetBtn.style.display = 'inline-flex';
    
    // Highlight the selected row
    document.querySelectorAll('#analysis-history-table-body tr').forEach(r => r.style.background = 'transparent');
    const selectedRow = document.getElementById(`analysis-log-row-${logId}`);
    if (selectedRow) selectedRow.style.background = 'rgba(255,255,255,0.06)';
    
    const container = document.getElementById('stages-container');
    if (container) {
        const trans = window.dashboardSettings ? window.dashboardSettings.translations : {
            stage1_title: 'Этап 1',
            stage2_title: 'Этап 2',
            stage3_title: 'Этап 3'
        };

        container.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 1rem; height: 100%;">
                <div class="stage-card" style="flex: 1;">
                    <div class="stage-title" style="color: var(--accent-gold);">
                        <span>${trans.stage1_title} (Historical)</span>
                        <i class="fa-solid fa-magnifying-glass-chart"></i>
                    </div>
                    <div class="stage-body" style="white-space: pre-wrap;">${log.stage1_output}</div>
                </div>
                <div class="stage-card stage-2" style="flex: 1;">
                    <div class="stage-title" style="color: var(--accent-cyan);">
                        <span>${trans.stage2_title} (Historical)</span>
                        <i class="fa-solid fa-chess"></i>
                    </div>
                    <div class="stage-body" style="white-space: pre-wrap;">${log.stage2_output}</div>
                </div>
            </div>
            <div class="stage-card stage-3" style="display: flex; flex-direction: column; height: 100%; justify-content: space-between;">
                <div class="stage-title" style="color: var(--accent-green);">
                    <span>${trans.stage3_title} (Historical)</span>
                    <i class="fa-solid fa-list-check"></i>
                </div>
                <div class="stage-body" style="flex: 1; display: flex; flex-direction: column; justify-content: center;">
                    ${formatStage3Output(log.stage3_output)}
                    <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:0.75rem; text-align: right;">${formatDateTimeToLocal(log.created_at)}</div>
                </div>
            </div>
        `;
    }
}

function resetToLiveLog() {
    window.isViewingHistoricalLog = false;
    
    // Hide the button
    const resetBtn = document.getElementById('reset-to-live-log-btn');
    if (resetBtn) resetBtn.style.display = 'none';
    
    // Remove table highlights
    document.querySelectorAll('#analysis-history-table-body tr').forEach(r => r.style.background = 'transparent');
    
    if (window.latestLiveLog) {
        updateStageLogs(window.latestLiveLog);
    } else {
        const container = document.getElementById('stages-container');
        if (container) {
            container.innerHTML = `
                <div style="text-align: center; color: var(--text-secondary); padding: 4rem 0; width: 100%; grid-column: 1 / -1;">
                    <i class="fa-solid fa-circle-notch fa-spin" style="font-size: 2.5rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                    <p>Waiting for live analysis logs...</p>
                </div>
            `;
        }
    }
}

function mergeHistoryData(oldList, newList) {
    const map = new Map();
    oldList.forEach(item => map.set(item.id, item));
    newList.forEach(item => map.set(item.id, item));
    const merged = Array.from(map.values());
    merged.sort((a, b) => b.id - a.id);
    return merged;
}

function updateTradeHistoryTable(history) {
    const tbody = document.getElementById('trade-history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (history.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 2rem;">No trade history.</td></tr>`;
        return;
    }
    
    history.forEach(trade => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
        const sideClass = trade.side === 'BUY' ? 'badge-success' : 'badge-danger';
        const pnlClass = trade.pnl >= 0 ? 'text-green' : 'text-red';
        const pnlSign = trade.pnl >= 0 ? '+' : '';
        
        tr.innerHTML = `
            <td><strong>${trade.pair}</strong></td>
            <td><span class="badge ${sideClass}">${trade.side}</span></td>
            <td>$${trade.entry_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
            <td><span class="badge badge-warning">${trade.status}</span></td>
            <td class="${pnlClass}" style="font-weight: 700;">${pnlSign}$${trade.pnl.toFixed(2)}</td>
            <td>${formatDateTimeToLocal(trade.created_at)}</td>
            <td>${formatDateTimeToLocal(trade.closed_at)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateAnalysisLogsHistoryTable(logs) {
    const tbody = document.getElementById('analysis-history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 2rem;">No decision logs yet.</td></tr>`;
        return;
    }
    
    logs.forEach(log => {
        window.analysisHistoryLogs[log.id] = log;
        
        const tr = document.createElement('tr');
        tr.id = `analysis-log-row-${log.id}`;
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
        
        let signalAction = 'HOLD';
        let signalClass = 'badge-secondary';
        let prob = 'N/A';
        let targetPrice = 'N/A';
        let reason = 'Calculating...';
        
        if (log.stage3_output) {
            try {
                const s3 = typeof log.stage3_output === 'string' ? JSON.parse(log.stage3_output) : log.stage3_output;
                signalAction = s3.action || 'HOLD';
                if (signalAction === 'BUY') signalClass = 'badge-success';
                else if (signalAction === 'SELL') signalClass = 'badge-danger';
                
                prob = s3.probability !== undefined ? (s3.probability * 100).toFixed(1) + '%' : 'N/A';
                targetPrice = s3.price ? '$' + Number(s3.price).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) : 'N/A';
                reason = s3.reason || '';
            } catch (e) {
                reason = log.stage3_output;
            }
        }
        
        tr.innerHTML = `
            <td>${formatDateTimeToLocal(log.created_at)}</td>
            <td><strong>${log.pair}</strong></td>
            <td><span class="badge ${signalClass}">${signalAction}</span></td>
            <td>${prob}</td>
            <td>${targetPrice}</td>
            <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${reason}">${reason}</td>
            <td style="text-align: center;">
                <button class="btn btn-secondary btn-sm" onclick="viewAnalysisLogDetails(${log.id})" style="padding: 0.15rem 0.4rem; font-size: 0.72rem; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08);">
                    <i class="fa-solid fa-eye"></i> View
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function updateLiveOrdersPnL(pair, currentPrice) {
    document.querySelectorAll('tr[id^="active-order-row-"]').forEach(row => {
        const rowPair = row.getAttribute('data-pair');
        if (rowPair && rowPair.toUpperCase() === pair.toUpperCase()) {
            const entry = parseFloat(row.getAttribute('data-entry-price'));
            const colateral = parseFloat(row.getAttribute('data-colateral'));
            const side = row.getAttribute('data-side');
            const amount = parseFloat(row.getAttribute('data-amount'));
            
            // Check if futures (has leverage class or data attribute)
            const margin = colateral; 
            
            const currPriceCell = row.querySelector('.order-curr-price');
            const pnlCell = row.querySelector('.order-pnl');
            
            if (currPriceCell) {
                currPriceCell.textContent = '$' + currentPrice.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
            }
            
            if (pnlCell && !isNaN(entry) && !isNaN(amount)) {
                let pnl = 0.0;
                if (side === 'BUY') {
                    pnl = (currentPrice - entry) * amount;
                } else {
                    pnl = (entry - currentPrice) * amount;
                }
                
                const pnlPct = margin > 0 ? (pnl / margin) * 100 : 0.0;
                
                const status = row.getAttribute('data-status');
                if (status === 'PENDING') {
                    pnlCell.innerHTML = '<span style="color: var(--accent-gold)">PENDING</span>';
                } else {
                    const pnlSign = pnl >= 0 ? '+' : '';
                    pnlCell.textContent = `${pnlSign}$${pnl.toFixed(2)} (${pnlSign}${pnlPct.toFixed(2)}%)`;
                    pnlCell.style.color = pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                }
            }
        }
    });
}

function showIndicatorsError(msg) {
    const errorEl = document.getElementById('indicators-error-msg');
    const containerEl = document.getElementById('indicators-list-container');
    
    // Ignore common network/connection errors visually so they don't clutter the UI
    if (msg && (msg.includes('HTTPSConnectionPool') || msg.includes('Max retries exceeded') || msg.includes('NameResolutionError') || msg.includes('Connection aborted'))) {
        return; 
    }
    
    if (errorEl) {
        errorEl.textContent = "Failed to update: " + msg;
        errorEl.style.display = 'block';
    }
    if (containerEl) {
        // Only hide grid if it was empty / never loaded
        const valEl = document.getElementById('live-price-val');
        if (valEl && valEl.textContent === 'N/A') {
            containerEl.style.display = 'none';
        }
    }
}

function showToast(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.position = 'fixed';
        container.style.bottom = '1.5rem';
        container.style.right = '1.5rem';
        container.style.zIndex = '9999';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '0.75rem';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'glass-panel';
    toast.style.padding = '0.9rem 1.4rem';
    toast.style.borderRadius = '12px';
    toast.style.color = '#fff';
    toast.style.fontSize = '0.92rem';
    toast.style.fontWeight = '600';
    toast.style.boxShadow = '0 18px 40px rgba(0,0,0,0.18)';
    toast.style.border = '1px solid rgba(255,255,255,0.08)';
    toast.style.display = 'flex';
    toast.style.alignItems = 'center';
    toast.style.gap = '0.65rem';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(1rem)';
    toast.style.transition = 'all 0.25s ease';

    if (type === 'success') {
        toast.style.background = 'rgba(0, 187, 255, 0.16)';
        toast.style.borderLeft = '4px solid #00d7ff';
        toast.innerHTML = `<i class="fa-solid fa-circle-check" style="color: #00d7ff;"></i> ${message}`;
    } else {
        toast.style.background = 'rgba(255, 65, 105, 0.16)';
        toast.style.borderLeft = '4px solid #ff3864';
        toast.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color: #ff3864;"></i> ${message}`;
    }

    container.appendChild(toast);
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
    });

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(1rem)';
        setTimeout(() => toast.remove(), 300);
    }, 2400);
}

// Initial load — wait for full page paint before initializing WebSocket
window.addEventListener('load', () => {
    connectToBackendSocket();
});

// Intercept settings / balance forms to submit via AJAX and update UI without reload
document.addEventListener('submit', async function(e) {
    const form = e.target;
    if (!form) return;

    const action = (typeof form.action === 'string') ? form.action : (form.getAttribute ? form.getAttribute('action') || '' : '');
    const ajaxActions = ['/save_trading_settings', '/save_api_settings', '/reset_balance', '/reset_demo_orders'];
    try {
        if (ajaxActions.some(a => action.includes(a))) {
            e.preventDefault();
            const submitBtn = form.querySelector('button[type="submit"]');
            const original = submitBtn ? submitBtn.innerHTML : null;
            if (submitBtn) { submitBtn.disabled = true; submitBtn.innerHTML = '<i class="fa-solid fa-spinner spinner"></i>'; }

            const fd = new FormData(form);
            const res = await fetch(action, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            let data = {};
            try { data = await res.json(); } catch(e) { }

            if (res.ok && data.success) {
                // Update balance display if present
                if (data.new_balance !== undefined) {
                    const balanceDisplay = document.getElementById('balance-amount-display');
                    if (balanceDisplay) balanceDisplay.textContent = '$' + Number(data.new_balance).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                }

                // Update settings badges
                if (data.settings) {
                    const badge = document.getElementById('chart-timeframe-badge');
                    if (badge) badge.textContent = `${data.settings.trading_pair} - ${data.settings.timeframe}`;
                    const indBadge = document.getElementById('indicators-timeframe-badge');
                    if (indBadge) indBadge.textContent = data.settings.timeframe;
                }

                // Show success briefly
                if (submitBtn) {
                    submitBtn.innerHTML = '<i class="fa-solid fa-check"></i> OK';
                    setTimeout(() => { if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = original; } }, 900);
                }
            } else {
                if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = original; }
                showToast((data && data.message) ? data.message : 'Request failed.', 'error');
            }
        }
    } catch (err) {
        if (form && e) e.preventDefault();
        showToast('Error processing request: ' + err.message, 'error');
    }
});

// Intercept Toggle Bot forms to update dynamically
document.addEventListener('submit', async function(e) {
    const form = e.target;
    const action = (form && typeof form.action === 'string') ? form.action : (form && form.getAttribute ? form.getAttribute('action') || '' : '');
    if (action.includes('/toggle_bot')) {
        e.preventDefault();
        
        const actionInput = form.querySelector('input[name="action"]');
        if (!actionInput) return;
        const actionVal = actionInput.value; // "start" or "stop"
        
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalContent = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa-solid fa-spinner spinner"></i>';
        
        const overlay = document.getElementById('engine-loader-overlay');
        const overlayText = document.getElementById('engine-loader-text');
        
        if (overlay) {
            overlay.style.display = 'flex';
            overlay.style.opacity = '0';
            setTimeout(() => { overlay.style.opacity = '1'; }, 50);
            
            if (actionVal === 'start') {
                overlayText.textContent = 'INITIALIZING AUTOMATED TRADING ENGINE...';
                overlayText.style.color = 'var(--accent-gold)';
                overlayText.style.textShadow = '0 0 10px rgba(255, 183, 3, 0.4)';
            } else {
                overlayText.textContent = 'TERMINATING COGNITIVE TRADING CYCLES...';
                overlayText.style.color = 'var(--accent-red)';
                overlayText.style.textShadow = '0 0 10px rgba(244, 63, 94, 0.4)';
            }
        }
        
        const startTime = Date.now();
        const formData = new FormData(form);
        
        try {
            const response = await fetch(action, {
                method: 'POST',
                body: formData
            });
            
            if (response.redirected || response.ok) {
                let data = {};
                try { data = await response.json(); } catch(e) {}
                
                const elapsed = Date.now() - startTime;
                const remaining = Math.max(0, 1200 - elapsed);
                
                setTimeout(() => {
                    if (overlay) {
                        overlay.style.opacity = '0';
                        setTimeout(() => { overlay.style.display = 'none'; }, 300);
                    }
                    
                    // Update UI elements dynamically
                    const statusDot = document.querySelector('.status-dot');
                    const statusText = document.querySelector('.status-text');
                    const botForm = document.querySelector('form[action="/toggle_bot"]');
                    const botToggleBtn = document.getElementById('bot-toggle-btn');
                    const chartTimeframeBadge = document.getElementById('chart-timeframe-badge');
                    const pairName = chartTimeframeBadge ? chartTimeframeBadge.textContent.split(' - ')[0] : 'Pair';
                    
                    const balanceDisplay = document.getElementById('balance-amount-display');
                    const demoEarningsAmount = document.getElementById('demo-earnings-amount');
                    const demoEarningsPercent = document.getElementById('demo-earnings-percent');

                    const trans = window.dashboardSettings ? window.dashboardSettings.translations : {
                        bot_active: 'Активен на PLACEHOLDER',
                        bot_stopped: 'Остановлен',
                        stop_bot: 'Остановить',
                        start_bot: 'Запустить'
                    };

                    if (actionVal === 'start') {
                        if (statusDot) {
                            statusDot.className = 'status-dot active';
                        }
                        if (statusText) {
                            statusText.textContent = trans.bot_active.replace('PLACEHOLDER', pairName);
                        }
                        if (botForm) {
                            const actionInput = botForm.querySelector('input[name="action"]');
                            if (actionInput) actionInput.value = 'stop';
                        }
                        if (botToggleBtn) {
                            botToggleBtn.className = 'btn btn-danger btn-block btn-sm';
                            botToggleBtn.innerHTML = '<i class="fa-solid fa-stop"></i> ' + trans.stop_bot;
                        }
                        showToast('Automated trading bot started.', 'success');
                    } else {
                        if (statusDot) {
                            statusDot.className = 'status-dot inactive';
                        }
                        if (statusText) {
                            statusText.textContent = trans.bot_stopped;
                        }
                        if (botForm) {
                            const actionInput = botForm.querySelector('input[name="action"]');
                            if (actionInput) actionInput.value = 'start';
                        }
                        if (botToggleBtn) {
                            botToggleBtn.className = 'btn btn-primary btn-block btn-sm';
                            botToggleBtn.innerHTML = '<i class="fa-solid fa-play"></i> ' + trans.start_bot;
                        }
                        showToast('Automated trading bot stopped.', 'success');
                    }

                    if (demoEarningsAmount && data.bot_earnings !== undefined) {
                        const earnings = Number(data.bot_earnings || 0);
                        const earningsSign = earnings >= 0 ? '+' : '';
                        demoEarningsAmount.textContent = `${earningsSign}$${earnings.toFixed(2)}`;
                        demoEarningsAmount.style.color = earnings >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                        
                        if (demoEarningsPercent && balanceDisplay) {
                            const balanceVal = parseFloat(balanceDisplay.textContent.replace(/[^0-9.-]/g, '')) || 0;
                            const startingBal = balanceVal - earnings;
                            const percent = startingBal > 0 ? (earnings / startingBal) * 100 : 0.0;
                            const percentSign = percent >= 0 ? '+' : '';
                            demoEarningsPercent.textContent = `${percentSign}${percent.toFixed(2)}%`;
                            demoEarningsPercent.style.color = percent >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                        }
                    }
                }, remaining);
            } else {
                if (overlay) {
                    overlay.style.opacity = '0';
                    setTimeout(() => { overlay.style.display = 'none'; }, 300);
                }
                showToast('Failed to toggle bot status.', 'error');
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalContent;
            }
        } catch (err) {
            if (overlay) {
                overlay.style.opacity = '0';
                setTimeout(() => { overlay.style.display = 'none'; }, 300);
            }
            showToast('Error toggling bot status: ' + err.message, 'error');
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalContent;
        }
    }
});

// Intercept Close Order forms to execute via AJAX and remove table rows smoothly
document.addEventListener('submit', async function(e) {
    const form = e.target;
    const action = (form && typeof form.action === 'string') ? form.action : (form && form.getAttribute ? form.getAttribute('action') || '' : '');
    if (action.includes('/close_order/')) {
        e.preventDefault();
        
        const row = form.closest('tr[id^="active-order-row-"]');
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fa-solid fa-spinner spinner"></i>';
        }
        
        try {
            const response = await fetch(action, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                if (row) {
                    row.style.transition = 'all 0.5s ease';
                    row.style.opacity = '0';
                    row.style.transform = 'scale(0.95)';
                    setTimeout(() => {
                        row.remove();
                        
                        // Check if active orders list is completely empty
                        const remainingRows = document.querySelectorAll('tr[id^="active-order-row-"]');
                        if (remainingRows.length === 0) {
                            const tableBody = document.getElementById('active-orders-table-body');
                            if (tableBody) {
                                tableBody.innerHTML = `
                                    <tr>
                                        <td colspan="11" style="text-align: center; color: var(--text-secondary); padding: 2rem;">No active orders.</td>
                                    </tr>
                                `;
                            }
                        }
                        
                        // Dynamically append to Trade History table
                        const historyBody = document.getElementById('trade-history-table-body');
                        if (historyBody && data.success) {
                            // Remove empty placeholder row if exists
                            const emptyRow = historyBody.querySelector('tr > td[colspan="7"]');
                            if (emptyRow) {
                                emptyRow.parentElement.remove();
                            }
                            
                            const newRow = document.createElement('tr');
                            const sideBadgeClass = data.side === 'BUY' ? 'badge-success' : 'badge-danger';
                            const pnlClass = data.pnl > 0 ? 'text-green' : 'text-red';
                            const pnlSign = data.pnl >= 0 ? '+' : '';
                            const closedAtStr = new Date().toISOString().replace('T', ' ').substring(0, 19);
                            
                            newRow.innerHTML = `
                                <td><strong>${data.pair}</strong></td>
                                <td><span class="badge ${sideBadgeClass}">${data.side}</span></td>
                                <td>$${data.entry_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                                <td><span class="badge badge-warning">${data.status}</span></td>
                                <td class="${pnlClass}" style="font-weight: 700;">${pnlSign}$${data.pnl.toFixed(2)}</td>
                                 <td>${formatDateTimeToLocal(data.created_at)}</td>
                                 <td>${formatDateTimeToLocal(closedAtStr)}</td>
                            `;
                            
                            // Prepend new row to top of history
                            historyBody.insertBefore(newRow, historyBody.firstChild);
                        }
                    }, 500);
                }
            } else {
                showToast('Failed to close order.', 'error');
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="fa-solid fa-rectangle-xmark"></i> Close';
                }
            }
        } catch (err) {
            showToast('Error closing order: ' + err.message, 'error');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa-solid fa-rectangle-xmark"></i> Close';
            }
        }
    }
});

function toggleAnalysisHistory() {
    const wrapper = document.getElementById('analysis-history-wrapper');
    const btn = document.getElementById('toggle-analysis-history-btn');
    if (!wrapper || !btn) return;
    
    const isCollapsed = wrapper.classList.toggle('collapsed');
    if (isCollapsed) {
        btn.innerHTML = '<i class="fa-solid fa-chevron-down"></i> Expand';
        btn.title = "Expand AI Decision History";
    } else {
        btn.innerHTML = '<i class="fa-solid fa-chevron-up"></i> Collapse';
        btn.title = "Collapse AI Decision History";
    }
}

function toggleTradeHistory() {
    const wrapper = document.getElementById('trade-history-wrapper');
    const btn = document.getElementById('toggle-trade-history-btn');
    if (!wrapper || !btn) return;
    
    const isCollapsed = wrapper.classList.toggle('collapsed');
    if (isCollapsed) {
        btn.innerHTML = '<i class="fa-solid fa-chevron-down"></i> Expand';
        btn.title = "Expand Trade History";
    } else {
        btn.innerHTML = '<i class="fa-solid fa-chevron-up"></i> Collapse';
        btn.title = "Collapse Trade History";
    }
}

// Tab Switching
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => {
        el.style.display = 'none';
    });
    const selectedContent = document.getElementById('tab-content-' + tabId);
    if (selectedContent) {
        selectedContent.style.display = 'block';
    }
    
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = 'none';
        btn.style.borderColor = 'transparent';
        btn.style.color = 'var(--text-secondary)';
    });
    
    const activeBtn = document.getElementById('tab-btn-' + tabId);
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = 'rgba(255, 255, 255, 0.05)';
        activeBtn.style.borderColor = 'var(--surface-border)';
        activeBtn.style.color = 'var(--text-primary)';
    }

    if (tabId === 'all-orders') {
        loadAllOrdersHistory();
    } else if (tabId === 'decision-history') {
        loadAIDecisionsHistory();
    }
}

// Fetch all orders
function loadAllOrdersHistory() {
    const pair = document.getElementById('filter-order-pair').value;
    const mode = document.getElementById('filter-order-mode').value;
    const side = document.getElementById('filter-order-side').value;
    const status = document.getElementById('filter-order-status').value;
    const startDate = document.getElementById('filter-order-start').value;
    const endDate = document.getElementById('filter-order-end').value;

    let url = `/api/all_orders?pair=${encodeURIComponent(pair)}&mode=${encodeURIComponent(mode)}&side=${encodeURIComponent(side)}&status=${encodeURIComponent(status)}&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;

    fetch(url)
        .then(res => res.json())
        .then(data => {
            const tbody = document.getElementById('all-orders-history-table-body');
            if (!tbody) return;
            tbody.innerHTML = '';
            
            if (!data.success || !data.orders || data.orders.length === 0) {
                tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-secondary); padding: 3rem;">Нет подходящих ордеров.</td></tr>`;
                return;
            }

            data.orders.forEach(o => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
                
                const badgeClass = o.side === 'BUY' ? 'badge-success' : 'badge-danger';
                const statusClass = o.status === 'ACTIVE' || o.status === 'PENDING' ? 'badge-warning' : 
                                  (o.pnl !== null && o.pnl >= 0) || o.status.includes('TP') ? 'badge-success' : 'badge-danger';
                
                let pnlText = '0.00';
                let pnlClass = '';
                if (o.pnl !== null) {
                    pnlText = `${o.pnl >= 0 ? '+' : ''}${o.pnl.toFixed(2)} USDT`;
                    pnlClass = o.pnl >= 0 ? 'text-green' : 'text-red';
                }

                // Show margin adjusted by leverage for futures
                const margin = (o.market_type === 'FUTURES') ? (o.size_usdt / (o.leverage || 1)) : o.size_usdt;
                const leverageStr = (o.market_type === 'FUTURES') ? ` (${o.leverage || 1}x)` : '';

                tr.innerHTML = `
                    <td style="padding: 0.75rem; color: var(--text-secondary); font-family: monospace;">${o.id}</td>
                    <td style="padding: 0.75rem; font-weight: 600;">${o.pair}</td>
                    <td style="padding: 0.75rem;"><span class="badge ${o.trading_mode === 'LIVE' ? 'badge-warning' : 'badge-secondary'}">${o.trading_mode} (${o.market_type})</span></td>
                    <td style="padding: 0.75rem;"><span class="badge ${badgeClass}">${o.side}</span></td>
                    <td style="padding: 0.75rem;">$${Number(o.entry_price).toLocaleString()}</td>
                    <td style="padding: 0.75rem;">$${margin.toFixed(2)}${leverageStr}</td>
                    <td style="padding: 0.75rem; font-size: 0.75rem; color: var(--text-secondary);">
                        TP: $${Number(o.take_profit || 0).toLocaleString()}<br>
                        SL: $${Number(o.stop_loss || 0).toLocaleString()}
                    </td>
                    <td style="padding: 0.75rem; font-weight: 700;" class="${pnlClass}">${pnlText}</td>
                    <td style="padding: 0.75rem;"><span class="badge ${statusClass}">${o.status}</span></td>
                    <td style="padding: 0.75rem; color: var(--text-secondary); font-size: 0.75rem;">${formatDateTimeToLocal(o.created_at)}</td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(err => console.error('Failed to load orders history:', err));
}

let loadedDecisions = {};

// Fetch AI Decisions
function loadAIDecisionsHistory() {
    const pair = document.getElementById('filter-decision-pair').value;
    const startDate = document.getElementById('filter-decision-start').value;
    const endDate = document.getElementById('filter-decision-end').value;

    let url = `/api/ai_decision_history?pair=${encodeURIComponent(pair)}&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;

    fetch(url)
        .then(res => res.json())
        .then(data => {
            const tbody = document.getElementById('decision-history-list-tbody');
            if (!tbody) return;
            tbody.innerHTML = '';
            loadedDecisions = {};

            if (!data.success || !data.logs || data.logs.length === 0) {
                tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-secondary); padding: 3rem;">Нет логов за этот период.</td></tr>`;
                return;
            }

            data.logs.forEach(l => {
                loadedDecisions[l.id] = l;
                const tr = document.createElement('tr');
                tr.id = `api-decision-row-${l.id}`;
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
                tr.style.cursor = 'pointer';
                
                tr.onclick = () => selectDecisionDetail(l.id);

                let signalText = 'HOLD';
                let signalClass = 'badge-secondary';
                if (l.stage3_output) {
                    if (l.stage3_output.includes('BUY')) { signalText = 'BUY'; signalClass = 'badge-success'; }
                    else if (l.stage3_output.includes('SELL')) { signalText = 'SELL'; signalClass = 'badge-danger'; }
                }

                tr.innerHTML = `
                    <td style="padding: 0.75rem; color: var(--text-secondary); font-size: 0.75rem;">${formatDateTimeToLocal(l.created_at)}</td>
                    <td style="padding: 0.75rem; font-weight: 600;">${l.pair}</td>
                    <td style="padding: 0.75rem;"><span class="badge ${signalClass}">${signalText}</span></td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(err => console.error('Failed to load decision history:', err));
}

function selectDecisionDetail(id) {
    const log = loadedDecisions[id];
    if (!log) return;

    // Highlight row
    document.querySelectorAll('#decision-history-list-tbody tr').forEach(r => r.style.background = 'transparent');
    const selectedRow = document.getElementById(`api-decision-row-${id}`);
    if (selectedRow) selectedRow.style.background = 'rgba(255,255,255,0.06)';

    document.getElementById('decision-detail-empty').style.display = 'none';
    document.getElementById('decision-detail-content').style.display = 'block';

    document.getElementById('decision-detail-title').textContent = `ИИ Решение: ${log.pair}`;
    document.getElementById('decision-detail-time').textContent = formatDateTimeToLocal(log.created_at);

    // Update the stages content dynamically
    const stagesContainer = document.getElementById('decision-stages-container');
    stagesContainer.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 1rem; height: 100%;">
            <div class="stage-card" style="border-left-color: var(--accent-gold); background: rgba(255, 183, 3, 0.03);">
                <div class="stage-title" style="color: var(--accent-gold);">
                    <span>Технический анализ (Индикаторы ИИ)</span>
                    <i class="fa-solid fa-calculator"></i>
                </div>
                <div class="stage-body" style="white-space: pre-wrap; font-weight: 600; font-size: 0.85rem;">${log.indicators_summary || 'N/A'}</div>
            </div>
            <div class="stage-card">
                <div class="stage-title" style="color: var(--accent-gold);">
                    <span>Этап 1: Сентимент и рыночный контекст</span>
                    <i class="fa-solid fa-magnifying-glass-chart"></i>
                </div>
                <div class="stage-body" style="white-space: pre-wrap;">${log.stage1_output}</div>
            </div>
            <div class="stage-card stage-2">
                <div class="stage-title" style="color: var(--accent-cyan);">
                    <span>Этап 2: Планировщик стратегии</span>
                    <i class="fa-solid fa-chess"></i>
                </div>
                <div class="stage-body" style="white-space: pre-wrap;">${log.stage2_output}</div>
            </div>
        </div>
        <div class="stage-card stage-3" style="display: flex; flex-direction: column; height: 100%; justify-content: space-between; border-left-color: var(--accent-green);">
            <div class="stage-title" style="color: var(--accent-green);">
                <span>Этап 3: Конфигурация исполнения ордера</span>
                <i class="fa-solid fa-list-check"></i>
            </div>
            <div class="stage-body" style="flex: 1; display: flex; flex-direction: column; justify-content: center; margin-top: 1rem;">
                ${formatStage3Output(log.stage3_output)}
            </div>
        </div>
    `;
}

document.addEventListener('DOMContentLoaded', function() {
    const autoCenterCheckbox = document.getElementById('auto-center-chart');
    if (autoCenterCheckbox) {
        autoCenterCheckbox.addEventListener('change', function() {
            fetch('/save_ui_settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ui_auto_center: this.checked
                })
            }).catch(err => console.error('Failed to save UI settings:', err));
        });
    }
    
    // Set default date filters to today's date
    const todayStr = new Date().toISOString().split('T')[0];
    const orderStart = document.getElementById('filter-order-start');
    const orderEnd = document.getElementById('filter-order-end');
    const decStart = document.getElementById('filter-decision-start');
    const decEnd = document.getElementById('filter-decision-end');
    if (orderStart) orderStart.value = todayStr;
    if (orderEnd) orderEnd.value = todayStr;
    if (decStart) decStart.value = todayStr;
    if (decEnd) decEnd.value = todayStr;

    // Switch to initial tab sent by Flask template
    const initialTab = window.dashboardSettings ? window.dashboardSettings.activeTab : null;
    if (initialTab && initialTab !== "terminal") {
        switchTab(initialTab);
        // Set active class on navbar links
        document.querySelectorAll('.nav-tab-link').forEach(link => {
            link.classList.remove('active');
        });
        const activeLink = document.getElementById('nav-link-' + initialTab);
        if (activeLink) activeLink.classList.add('active');
    }
});
