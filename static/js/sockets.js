let binanceSocket = null;
window.currentSocketKey = null;

function connectToBinanceSocket(pair, timeframe, marketType) {
    if (binanceSocket) {
        try {
            binanceSocket.close();
        } catch (e) {}
    }
    
    const symbolLower = pair.toLowerCase().replace(/[^a-z0-9]/g, '');
    const wsUrl = marketType === 'FUTURES'
        ? `wss://fstream.binance.com/ws/${symbolLower}@kline_${timeframe}`
        : `wss://stream.binance.com:9443/ws/${symbolLower}@kline_${timeframe}`;
        
    console.log(`Connecting to Binance live WebSocket stream: ${wsUrl}`);
    binanceSocket = new WebSocket(wsUrl);
    window.wsConnected = false;
    
    binanceSocket.onopen = function() {
        window.wsConnected = true;
        console.log("Binance WebSocket stream connected.");
    };
    
    binanceSocket.onerror = function() {
        window.wsConnected = false;
    };
    
    binanceSocket.onmessage = function(event) {
        const message = JSON.parse(event.data);
        const kline = message.k;
        if (!kline) return;
        
        const t = kline.t;
        const o = parseFloat(kline.o);
        const h = parseFloat(kline.h);
        const l = parseFloat(kline.l);
        const c = parseFloat(kline.c);
        const v = parseFloat(kline.v);
        
        // Update candlestick chart tick-by-tick
        if (candlestickSeries) {
            try {
                window.lastWsMessageTime = Date.now();
                const candleTime = Math.floor(t / 1000);
                if (window.lastChartTime === undefined || candleTime >= window.lastChartTime) {
                    candlestickSeries.update({
                        time: candleTime,
                        open: o,
                        high: h,
                        low: l,
                        close: c
                    });
                    window.lastChartTime = candleTime;
                }
                window.lastChartPrice = c;
            } catch (e) {
                console.warn("Binance WS chart update skipped:", e);
            }
            
            const isNewCandle = (window.lastChartTime !== undefined && candleTime > window.lastChartTime);
            const autoCenterCb = document.getElementById('auto-center-chart');
            if (autoCenterCb && autoCenterCb.checked && chartInstance && isNewCandle) {
                chartInstance.timeScale().scrollToRealTime();
            }
        }
        
        // Update Live Price tag instantly
        const livePriceEl = document.getElementById('live-price-val');
        if (livePriceEl) {
            livePriceEl.textContent = formatUSD(c);
        }
        
        // Update order profit instantly
        updateLiveOrdersPnL(pair, c);
    };
    
    binanceSocket.onclose = function() {
        window.wsConnected = false;
        const socketKey = `${pair}_${timeframe}_${marketType}`;
        if (window.currentSocketKey === socketKey) {
            console.log("Binance WebSocket stream closed. Reconnecting...");
            setTimeout(() => {
                if (window.currentSocketKey === socketKey) {
                    connectToBinanceSocket(pair, timeframe, marketType);
                }
            }, 5000);
        }
    };
    
    binanceSocket.onerror = function(err) {
        console.error("Binance WebSocket stream error:", err);
    };
}

let backendSocket = null;

function connectToBackendSocket() {
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/ws/market_data`;
    
    console.log("Connecting to backend market data WebSocket...");
    backendSocket = new WebSocket(wsUrl);
    
    backendSocket.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.success) {
                window.currentTimeframe = data.timeframe;
                if (data.klines) {
                    updateChart(data.klines, data.active_orders);
                } else {
                    updateChartData(null, data.active_orders);
                }
                
                // Subscribing/switching live stream dynamically
                const socketKey = `${data.pair}_${data.timeframe}_${data.market_type}`;
                if (window.currentSocketKey !== socketKey) {
                    window.currentSocketKey = socketKey;
                    connectToBinanceSocket(data.pair, data.timeframe, data.market_type);
                }
                
                // All calculations are performed on the backend
                const unrealizedPnl = data.unrealized_pnl || 0;
                const equity = data.equity || 0;
                
                // Update balance dynamically on poll
                const balanceDisplay = document.getElementById('balance-amount-display');
                const balanceTitle = document.getElementById('balance-title');
                const balanceSubtitle = document.getElementById('balance-pnl-subtitle');
                
                if (balanceDisplay) {
                    balanceDisplay.textContent = formatUSD(equity);
                }
                if (balanceTitle) {
                    balanceTitle.textContent = formatUSD(equity);
                }
                if (balanceSubtitle) {
                    const pnlSign = unrealizedPnl >= 0 ? '+' : '';
                    const pnlColor = unrealizedPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                    
                    if (data.is_live) {
                        balanceSubtitle.innerHTML = `
                            <span style="color: ${pnlColor}; font-weight:700;">
                                ${pnlSign}${formatUSD(unrealizedPnl)} Unrealized P&L
                            </span>
                        `;
                    } else {
                        if (unrealizedPnl !== 0) {
                            balanceSubtitle.innerHTML = `
                                <span style="color: ${pnlColor}; font-weight:700;">
                                    ${pnlSign}${formatUSD(unrealizedPnl)} Unrealized P&L
                                </span>
                            `;
                        } else {
                            balanceSubtitle.innerHTML = `<span style="color: var(--text-secondary); font-weight:500;">Нет активных сделок</span>`;
                        }
                    }
                }
                
                // Live earnings metrics updating
                const demoEarningsContainer = document.getElementById('demo-earnings-container');
                const demoEarningsAmount = document.getElementById('demo-earnings-amount');
                const demoEarningsPercent = document.getElementById('demo-earnings-percent');
                
                if (data.bot_earnings !== undefined) {
                    if (demoEarningsContainer) {
                        demoEarningsContainer.style.display = 'block';
                    }
                    if (demoEarningsAmount) {
                        const earnVal = data.bot_earnings;
                        const sign = earnVal >= 0 ? '+' : '';
                        demoEarningsAmount.textContent = `${sign}${formatUSD(earnVal)}`;
                    }
                    if (demoEarningsPercent) {
                        const pctVal = data.bot_earnings_pct;
                        const sign = pctVal >= 0 ? '+' : '';
                        demoEarningsPercent.textContent = `${sign}${formatNum(pctVal, 2)}%`;
                        demoEarningsPercent.className = 'earnings-badge ' + (pctVal >= 0 ? 'positive' : 'negative');
                    }
                }
                
                // Bot status and buttons sync
                if (data.bot_enabled !== undefined) {
                    const statusDot = document.querySelector('.bot-panel .status-dot');
                    const statusText = document.querySelector('.bot-panel .status-text');
                    const botToggleBtn = document.getElementById('bot-toggle-btn');
                    const botForm = document.querySelector('form[action="/toggle_bot"]');
                    
                    if (statusDot) {
                        statusDot.className = 'status-dot ' + (data.bot_enabled ? 'active' : 'inactive');
                    }
                    if (statusText) {
                        if (data.bot_enabled) {
                            statusText.textContent = window.dashboardSettings.translations.bot_active.replace('PLACEHOLDER', data.pair);
                        } else {
                            statusText.textContent = window.dashboardSettings.translations.bot_stopped;
                        }
                    }
                    if (botToggleBtn) {
                        if (data.bot_enabled) {
                            botToggleBtn.className = 'btn btn-danger btn-block btn-sm';
                            botToggleBtn.innerHTML = '<i class="fa-solid fa-stop"></i> ' + window.dashboardSettings.translations.stop_bot;
                        } else {
                            botToggleBtn.className = 'btn btn-primary btn-block btn-sm';
                            botToggleBtn.innerHTML = '<i class="fa-solid fa-play"></i> ' + window.dashboardSettings.translations.start_bot;
                        }
                        botToggleBtn.style.margin = '0';
                        botToggleBtn.style.padding = '0.75rem 1rem';
                        botToggleBtn.style.borderRadius = '10px';
                        botToggleBtn.style.height = '100%';
                        botToggleBtn.style.display = 'flex';
                        botToggleBtn.style.alignItems = 'center';
                        botToggleBtn.style.justifyContent = 'center';
                        botToggleBtn.style.gap = '0.5rem';
                        botToggleBtn.style.fontWeight = '700';
                        botToggleBtn.style.width = '100%';
                    }
                    if (botForm) {
                        const actionInput = botForm.querySelector('input[name="action"]');
                        if (actionInput) {
                            actionInput.value = data.bot_enabled ? 'stop' : 'start';
                        }
                    }
                }
                
                const chartTimeframeBadge = document.getElementById('chart-timeframe-badge');
                const indicatorsTimeframeBadge = document.getElementById('indicators-timeframe-badge');
                if (chartTimeframeBadge) chartTimeframeBadge.textContent = `${data.pair} - ${data.timeframe}`;
                if (indicatorsTimeframeBadge) indicatorsTimeframeBadge.textContent = data.timeframe;
                
                const errorEl = document.getElementById('indicators-error-msg');
                const containerEl = document.getElementById('indicators-list-container');
                if (errorEl) errorEl.style.display = 'none';
                if (containerEl) containerEl.style.display = 'grid';
                
                const ind = data.indicators;
                
                const livePriceEl = document.getElementById('live-price-val');
                if (livePriceEl) livePriceEl.textContent = formatUSD(ind.current_price);
                
                const rsiValEl = document.getElementById('rsi-val');
                if (rsiValEl) {
                    rsiValEl.textContent = formatNum(ind.rsi, 2);
                    rsiValEl.className = 'indicator-val';
                    if (ind.rsi > 70) {
                        rsiValEl.classList.add('text-red');
                    } else if (ind.rsi < 30) {
                        rsiValEl.classList.add('text-green');
                    }
                }
                
                const rsiDescEl = document.getElementById('rsi-desc');
                if (rsiDescEl) {
                    if (ind.rsi > 70) {
                        rsiDescEl.textContent = 'Overbought';
                    } else if (ind.rsi < 30) {
                        rsiDescEl.textContent = 'Oversold';
                    } else {
                        rsiDescEl.textContent = 'Neutral';
                    }
                }
                
                const emaEl = document.getElementById('ema-val');
                if (emaEl) emaEl.textContent = `${formatUSD(ind.ema9, 0)} / ${formatUSD(ind.ema21, 0)}`;
                
                const macdEl = document.getElementById('macd-val');
                if (macdEl) macdEl.textContent = `Hist: ${formatNum(ind.macd_hist, 2)}`;
                
                const bbEl = document.getElementById('bb-val');
                if (bbEl) bbEl.textContent = `L: ${formatUSD(ind.bb_lower, 1)} - U: ${formatUSD(ind.bb_upper, 1)}`;
                
                renderRecommendation(data.recommendation);
                // Update ML three-stage logs if provided by backend recommendation
                try {
                    if (data.recommendation && data.recommendation.latest_log) {
                        updateStageLogs(data.recommendation.latest_log);
                    }
                } catch (e) {
                    console.error('Failed to update stage logs from recommendation', e);
                }
                
                // Update AI analysis logs history table
                if (data.analysis_history) {
                    window.analysisHistoryData = mergeHistoryData(window.analysisHistoryData || [], data.analysis_history);
                    updateAnalysisLogsHistoryTable(window.analysisHistoryData);
                    
                    // Если живой лог еще не прилетел, автоматически выводим последний лог из истории
                    if (!window.latestLiveLog && window.analysisHistoryData.length > 0 && !window.isViewingHistoricalLog) {
                        const latestHist = window.analysisHistoryData[0];
                        updateStageLogs(latestHist);
                    }
                }
                
                // Dynamic unrealized P&L, live price updating, and active order table syncing
                const currentPrices = data.current_prices || {};
                const tableBody = document.getElementById('active-orders-table-body');
                
                if (data.active_orders.length === 0) {
                    tableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-secondary); padding: 2rem;">No active orders.</td></tr>`;
                } else {
                    const existingRowIds = Array.from(document.querySelectorAll('tr[id^="active-order-row-"]')).map(tr => tr.id.replace('active-order-row-', ''));
                    
                    // Remove closed orders from DOM
                    existingRowIds.forEach(idStr => {
                        const found = data.active_orders.find(o => String(o.id) === String(idStr));
                        if (!found) {
                            const tr = document.getElementById(`active-order-row-${idStr}`);
                            if (tr) tr.remove();
                        }
                    });
                    
                    // Remove the empty state row if it exists
                    const emptyRow = tableBody.querySelector('tr > td[colspan="10"]');
                    if (emptyRow) emptyRow.parentElement.remove();
                    
                    // Add or update existing orders
                    data.active_orders.forEach(o => {
                        let tr = document.getElementById(`active-order-row-${o.id}`);
                        const sideBadgeClass = o.side === 'BUY' ? 'badge-success' : 'badge-danger';
                        const slText = o.stop_loss ? '$' + o.stop_loss.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'None';
                        let tpText = o.take_profit ? '$' + o.take_profit.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'None';
                        
                        if (o.is_trailing && !o.take_profit) {
                            tpText = `<span class="badge" style="background: rgba(255, 183, 3, 0.2); color: var(--accent-gold); font-size: 0.65rem; display: inline-block;">TRAILING</span>`;
                        }
                        
                        // Show margin adjusted by leverage for futures (both live and demo)
                        const margin = (o.market_type === 'FUTURES') ? (o.size_usdt / (o.leverage || 1)) : o.size_usdt;
                        const leverageStr = (o.market_type === 'FUTURES') ? ` (${o.leverage || 1}x)` : '';
                        
                        // Live price from currentPrices map
                        const currPrice = currentPrices[o.pair.toUpperCase()] || o.entry_price;
                        const currPriceStr = '$' + currPrice.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                        
                        // PnL from backend
                        const pnlVal = o.unrealized_pnl || 0.0;
                        const pnlSign = pnlVal >= 0 ? '+' : '';
                        const pnlPct = margin > 0 ? (pnlVal / margin) * 100 : 0.0;
                        const pnlColor = pnlVal >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                        const pnlHtml = o.status === 'PENDING' ? '<span style="color: var(--accent-gold)">PENDING</span>' : `<span style="color: ${pnlColor}">${pnlSign}$${pnlVal.toFixed(2)} (${pnlSign}${pnlPct.toFixed(2)}%)</span>`;
                        
                        const rowHtml = `
                            <td><strong>${o.pair}</strong></td>
                            <td><span class="badge ${sideBadgeClass}">${o.side}</span> ${o.status === 'PENDING' ? '<span class="badge" style="background: var(--accent-gold); color: #000; font-size: 0.65rem;">LIMIT</span>' : ''}</td>
                            <td>${o.amount.toFixed(5)}</td>
                            <td>$${margin.toFixed(2)}${leverageStr}</td>
                            <td>$${o.entry_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                            <td style="color: var(--accent-red);">${slText}</td>
                            <td style="color: var(--accent-green);">${tpText}</td>
                            <td class="order-curr-price">${currPriceStr}</td>
                            <td class="order-pnl">${pnlHtml}</td>
                            <td>
                                <form action="/close_order/${o.id}" method="POST">
                                    <button type="submit" class="btn btn-danger btn-sm" style="padding: 0.25rem 0.5rem; font-size:0.75rem;">
                                        <i class="fa-solid fa-rectangle-xmark"></i> ${o.status === 'PENDING' ? 'Cancel' : 'Close'}
                                    </button>
                                </form>
                            </td>
                        `;

                        if (!tr) {
                            // Create new row
                            tr = document.createElement('tr');
                            tr.id = `active-order-row-${o.id}`;
                            tableBody.appendChild(tr);
                        }
                        
                        tr.setAttribute('data-pair', o.pair);
                        tr.setAttribute('data-entry-price', o.entry_price);
                        tr.setAttribute('data-amount', o.amount);
                        tr.setAttribute('data-side', o.side);
                        tr.setAttribute('data-colateral', o.size_usdt);
                        tr.setAttribute('data-status', o.status);
                        tr.innerHTML = rowHtml;
                    });
                }
                
                // Sync Completed Trade History Table
                if (data.history) {
                    window.tradeHistoryData = mergeHistoryData(window.tradeHistoryData || [], data.history);
                    updateTradeHistoryTable(window.tradeHistoryData);
                }
                
            } else {
                console.error("Market data error:", data.error);
                showIndicatorsError(data.error);
                const container = document.getElementById('stages-container');
                if (container) {
                    container.innerHTML = `
                        <div style="text-align: center; color: var(--accent-red); padding: 2rem; width: 100%; border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 12px; background: rgba(239, 68, 68, 0.05);">
                            <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
                            <p style="font-weight: 600; margin-bottom: 0.25rem;">Ошибка получения рыночных данных (Binance/Telegram)</p>
                            <p style="font-size: 0.85rem; opacity: 0.8; margin: 0;">${data.error || 'Неизвестная ошибка'}</p>
                        </div>
                    `;
                }
            }
        } catch (err) {
            console.error("Failed to parse market data JSON:", err);
        }
    };
    
    backendSocket.onclose = function() {
        console.warn("Backend WebSocket closed. Reconnecting in 3s...");
        setTimeout(connectToBackendSocket, 3000);
    };
    
    backendSocket.onerror = function(err) {
        console.error("Backend WebSocket error:", err);
    };
}
