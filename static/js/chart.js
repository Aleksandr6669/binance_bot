// Lightweight Charts Global State
let chartInstance = null;
let candlestickSeries = null;
let activePriceLines = [];
let isFreshLoad = true;
let isChartCreating = false;

function initChart(klinesData, activeOrders) {
    const container = document.getElementById('priceChart');
    if (!container) { console.error('[Chart] #priceChart container not found!'); return; }

    console.log('[Chart] initChart called. container size:', container.offsetWidth, 'x', container.offsetHeight,
                '| parent size:', container.parentElement.offsetWidth, 'x', container.parentElement.offsetHeight);

    // Destroy previous instance if exists
    if (chartInstance) {
        try { chartInstance.remove(); } catch(e) {}
        chartInstance = null;
        candlestickSeries = null;
        activePriceLines = [];
    }
    isChartCreating = true;
    isFreshLoad = true;

    // autoSize:true lets LightweightCharts handle width/height via ResizeObserver internally
    chartInstance = LightweightCharts.createChart(container, {
        autoSize: true,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: '#8a9fc2',
            fontSize: 11,
            fontFamily: 'Inter, sans-serif',
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: {
                labelBackgroundColor: '#1c2438',
            },
            horzLine: {
                labelBackgroundColor: '#1c2438',
            }
        },
        rightPriceScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
            textColor: '#8a9fc2',
        },
        timeScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
            textColor: '#8a9fc2',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    candlestickSeries = chartInstance.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    isChartCreating = false;

    if (klinesData) {
        updateChartData(klinesData, activeOrders);
    }
}

function updateChartData(klinesData, activeOrders) {
    if (!candlestickSeries) { console.warn('[Chart] updateChartData called but no candlestickSeries'); return; }
    
    let uniqueData = [];
    if (klinesData && klinesData.length > 0) {
        const chartData = klinesData.map(k => ({
            time: Math.floor(k.time / 1000),  // ms -> seconds (UTC Unix)
            open: parseFloat(k.open),
            high: parseFloat(k.high),
            low: parseFloat(k.low),
            close: parseFloat(k.close),
        }));

        // Remove duplicates and sort
        const seen = new Set();
        uniqueData = chartData.filter(c => {
            if (seen.has(c.time)) return false;
            seen.add(c.time);
            return true;
        });
        uniqueData.sort((a, b) => a.time - b.time);

        if (isFreshLoad) {
            try {
                candlestickSeries.setData(uniqueData);
                window.chartInitialized = true;
                window.lastTimeframe = window.currentTimeframe;
                window.lastChartTime = uniqueData[uniqueData.length - 1].time;
            } catch(e) {
                console.error('Chart setData error:', e, 'First item:', uniqueData[0]);
                return;
            }
        } else {
            // Fallback: smoothly update the latest candle from REST data every 1s 
            // in case WebSockets are blocked by the browser or network.
            if (!window.chartInitialized || window.lastTimeframe !== window.currentTimeframe) {
                candlestickSeries.setData(uniqueData);
                window.chartInitialized = true;
                window.lastTimeframe = window.currentTimeframe;
                window.lastChartTime = uniqueData[uniqueData.length - 1].time;
            } else {
                // ONLY update from REST if WebSocket is disconnected or hasn't sent a message in 3s!
                // Otherwise, REST's slightly delayed data overwrites the ultra-fast WS ticks and causes jitter!
                const wsIsDead = !window.wsConnected || (Date.now() - (window.lastWsMessageTime || 0) > 3000);
                if (uniqueData.length > 0 && wsIsDead) {
                    // Update all candles that are >= our last known chart time to prevent missing candles
                    const newCandles = uniqueData.filter(c => c.time >= window.lastChartTime);
                    newCandles.forEach(c => {
                        try {
                            candlestickSeries.update(c);
                            window.lastChartTime = c.time; // This ensures we track the latest time appended
                        } catch (e) {
                            console.warn("Chart update skipped:", e);
                        }
                    });
                }
            }
        }
        
        if (uniqueData.length > 0) {
            window.lastChartPrice = uniqueData[uniqueData.length - 1].close;
            startCandleTimer(uniqueData[uniqueData.length - 1].time, window.currentTimeframe);
        }
    }
    
    // Check if active orders changed structurally (ignoring unrealized_pnl, etc.)
    const structuralOrders = (activeOrders || []).map(o => ({
        id: o.id,
        status: o.status,
        entry_price: o.entry_price,
        stop_loss: o.stop_loss,
        take_profit: o.take_profit,
        side: o.side
    }));
    const ordersStr = JSON.stringify(structuralOrders);
    
    if (window.lastOrdersStr !== ordersStr) {
        window.lastOrdersStr = ordersStr;
        activePriceLines.forEach(line => candlestickSeries.removePriceLine(line));
        activePriceLines = [];
        
        if (activeOrders && activeOrders.length > 0) {
            activeOrders.forEach(o => {
                if (o.status === 'PENDING') {
                    // Render pending limit line only
                    const limitLine = candlestickSeries.createPriceLine({
                        price: o.entry_price,
                        color: '#ffc107', // yellow
                        lineWidth: 1.5,
                        lineStyle: 3, // dotted
                        axisLabelVisible: true,
                        title: `LIMIT Order (${o.side}) $${o.entry_price.toFixed(2)}`,
                    });
                    activePriceLines.push(limitLine);
                } else {
                    // Render standard Entry, SL, and TP lines for ACTIVE orders
                    const entryLine = candlestickSeries.createPriceLine({
                        price: o.entry_price,
                        color: '#00e5ff',
                        lineWidth: 1.5,
                        lineStyle: 2,
                        axisLabelVisible: true,
                        title: `Entry (${o.side}) $${o.entry_price.toFixed(2)}`,
                    });
                    activePriceLines.push(entryLine);
                    
                    if (o.stop_loss) {
                        const slLine = candlestickSeries.createPriceLine({
                            price: o.stop_loss,
                            color: '#ff1744',
                            lineWidth: 1,
                            lineStyle: 3,
                            axisLabelVisible: true,
                            title: `SL $${o.stop_loss.toFixed(2)}`,
                        });
                        activePriceLines.push(slLine);
                    }
                    
                    if (o.take_profit) {
                        const tpLine = candlestickSeries.createPriceLine({
                            price: o.take_profit,
                            color: '#00e676',
                            lineWidth: 1,
                            lineStyle: 3,
                            axisLabelVisible: true,
                            title: `TP $${o.take_profit.toFixed(2)}`,
                        });
                        activePriceLines.push(tpLine);
                    }
                }
            });
        }
    }
    
    const autoCenterCb = document.getElementById('auto-center-chart');
    if (chartInstance && uniqueData.length > 0) {
        if (isFreshLoad) {
            // Keep the exact zoom ratio requested on load
            const totalCandles = uniqueData.length;
            chartInstance.timeScale().setVisibleLogicalRange({
                from: totalCandles - 45,
                to: totalCandles + 25
            });
            isFreshLoad = false;
        } else if (autoCenterCb && autoCenterCb.checked) {
            // Smoothly auto-scroll to the newest candle while preserving zoom level
            chartInstance.timeScale().scrollToRealTime();
        }
    }
}

function updateChart(klinesData, activeOrders) {
    if (!chartInstance) {
        if (!isChartCreating) {
            initChart(klinesData, activeOrders);
        }
        return;
    }
    updateChartData(klinesData, activeOrders);
}

// Formatters
function formatUSD(val, decimals = 2) {
    if (val === null || val === undefined || isNaN(val)) return 'N/A';
    return '$' + Number(val).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Candle Timer Logic
function getTimeframeSeconds(tf) {
    const unit = tf.slice(-1);
    const val = parseInt(tf.slice(0, -1));
    if (unit === 'm') return val * 60;
    if (unit === 'h') return val * 3600;
    if (unit === 'd') return val * 86400;
    return 60;
}

function startCandleTimer(openTimeSec, timeframe) {
    if (window.candleTimerRAF) cancelAnimationFrame(window.candleTimerRAF);
    const durationSec = getTimeframeSeconds(timeframe);
    const closeTimeSec = openTimeSec + durationSec;
    
    function updateTimerRAF() {
        const nowSec = Math.floor(Date.now() / 1000);
        let diff = closeTimeSec - nowSec;
        if (diff < 0) diff = 0;
        
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        const s = diff % 60;
        let timerStr = "";
        if (h > 0) {
            timerStr = `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        } else {
            timerStr = `${m}:${s.toString().padStart(2, '0')}`;
        }
        
        const el = document.getElementById('candle-timer');
        if (el) {
            el.textContent = `До закрытия: ${timerStr}`;
            if (diff <= 10) {
                el.style.color = 'var(--accent-red)';
            } else {
                el.style.color = 'var(--text-secondary)';
            }
        }
        
        if (diff > 0) {
            window.candleTimerRAF = requestAnimationFrame(updateTimerRAF);
        }
    }
    updateTimerRAF();
}
