/**
 * SPOTTREND Trading Engine
 * Core trading logic, signal generation, and position management
 */

class TradingEngine {
    constructor() {
        this.symbol = 'NIFTY';
        this.interval = '5m';
        this.candles = [];
        this.ema20 = [];
        this.ema50 = [];
        this.positions = [];
        this.tradeLog = [];
        this.isAutoTrading = false;
        this.paperBalance = 1000000;
        this.paperPnL = 0;
        this.lastSignal = null;
    }

    /**
     * Calculate Exponential Moving Average
     */
    calculateEMA(prices, period) {
        if (prices.length === 0) return [];

        const ema = [];
        const multiplier = 2 / (period + 1);
        let currentEMA = prices[0];
        ema.push(currentEMA);

        for (let i = 1; i < prices.length; i++) {
            currentEMA = (prices[i] - currentEMA) * multiplier + currentEMA;
            ema.push(currentEMA);
        }

        return ema;
    }

    /**
     * Detect crossover signals
     */
    detectSignal() {
        if (this.ema20.length < 2 || this.ema50.length < 2) {
            return null;
        }

        const lastIdx = this.ema20.length - 1;
        const prevIdx = lastIdx - 1;

        const prevEMA20 = this.ema20[prevIdx];
        const prevEMA50 = this.ema50[prevIdx];
        const currEMA20 = this.ema20[lastIdx];
        const currEMA50 = this.ema50[lastIdx];

        // Golden Cross: EMA20 crosses above EMA50
        if (prevEMA20 <= prevEMA50 && currEMA20 > currEMA50) {
            return 'BUY';
        }

        // Death Cross: EMA20 crosses below EMA50
        if (prevEMA20 >= prevEMA50 && currEMA20 < currEMA50) {
            return 'SELL';
        }

        return null;
    }

    /**
     * Get current trend
     */
    getTrend() {
        if (this.ema20.length === 0 || this.ema50.length === 0) {
            return 'WAIT';
        }

        const lastEMA20 = this.ema20[this.ema20.length - 1];
        const lastEMA50 = this.ema50[this.ema50.length - 1];

        return lastEMA20 > lastEMA50 ? 'BULLISH' : 'BEARISH';
    }

    /**
     * Open a paper trading position
     */
    openPosition(side, entry, quantity = 1) {
        const riskPercent = 0.02;
        const risk = entry * riskPercent;

        const position = {
            id: Date.now(),
            side,
            entry,
            quantity,
            stopLoss: side === 'BUY' ? entry - risk : entry + risk,
            takeProfit: side === 'BUY' ? entry + (risk * 2) : entry - (risk * 2),
            openTime: new Date(),
            status: 'OPEN'
        };

        this.positions.push(position);
        this.addTradeLog('OPEN', side, entry, position.stopLoss, position.takeProfit);

        return position;
    }

    /**
     * Close a position
     */
    closePosition(positionId, exitPrice) {
        const position = this.positions.find(p => p.id === positionId);

        if (!position) return null;

        const pnl = position.side === 'BUY'
            ? (exitPrice - position.entry) * position.quantity
            : (position.entry - exitPrice) * position.quantity;

        this.paperPnL += pnl;
        position.exit = exitPrice;
        position.pnl = pnl;
        position.status = 'CLOSED';
        position.closeTime = new Date();

        this.addTradeLog('CLOSE', position.side, exitPrice, pnl);

        return position;
    }

    /**
     * Add entry to trade log
     */
    addTradeLog(type, side, price, ...data) {
        this.tradeLog.push({
            timestamp: new Date(),
            type,
            side,
            price,
            data,
            pnl: this.paperPnL
        });

        // Keep only last 100 trades
        if (this.tradeLog.length > 100) {
            this.tradeLog.shift();
        }
    }

    /**
     * Update candles and calculate indicators
     */
    updateCandles(newCandles) {
        this.candles = newCandles;

        const closes = newCandles.map(c => c.close);
        this.ema20 = this.calculateEMA(closes, 20);
        this.ema50 = this.calculateEMA(closes, 50);

        return this.detectSignal();
    }

    /**
     * Get statistics
     */
    getStats() {
        const closedTrades = this.tradeLog.filter(t => t.type === 'CLOSE');
        const winningTrades = closedTrades.filter(t => t.data[0] > 0).length;
        const losingTrades = closedTrades.filter(t => t.data[0] < 0).length;

        return {
            totalTrades: closedTrades.length,
            winRate: closedTrades.length > 0 ? ((winningTrades / closedTrades.length) * 100).toFixed(2) : 0,
            winningTrades,
            losingTrades,
            paperBalance: this.paperBalance + this.paperPnL,
            paperPnL: this.paperPnL,
            roi: this.paperBalance > 0 ? ((this.paperPnL / this.paperBalance) * 100).toFixed(2) : 0
        };
    }
}

/**
 * Market Data Provider
 */
class MarketDataProvider {
    constructor() {
        this.updateInterval = null;
    }

    /**
     * Generate realistic demo data
     */
    generateCandles(count = 250, symbol = 'NIFTY') {
        const candles = [];
        let price = 25000;
        const now = Math.floor(Date.now() / 1000);

        for (let i = 0; i < count; i++) {
            const time = now - ((count - i) * 300); // 5-minute intervals
            const volatility = 80 + Math.sin(i / 50) * 40;
            const movement = (Math.random() - 0.48) * volatility;

            const open = price;
            const close = price + movement;
            const high = Math.max(open, close) + Math.random() * 30;
            const low = Math.min(open, close) - Math.random() * 30;

            candles.push({
                time,
                open: Math.round(open * 100) / 100,
                high: Math.round(high * 100) / 100,
                low: Math.round(low * 100) / 100,
                close: Math.round(close * 100) / 100,
                volume: Math.floor(Math.random() * 1000000)
            });

            price = close;
        }

        return candles;
    }

    /**
     * Fetch real market data (placeholder for API integration)
     */
    async fetchMarketData(symbol, interval) {
        try {
            // Implement API call here
            // Example: Alpha Vantage, Finnhub, Polygon, etc.
            return this.generateCandles();
        } catch (error) {
            console.error('Error fetching market data:', error);
            return this.generateCandles();
        }
    }

    /**
     * Subscribe to live updates
     */
    subscribe(callback, intervalMs = 5000) {
        this.updateInterval = setInterval(() => {
            const candles = this.generateCandles();
            callback(candles);
        }, intervalMs);
    }

    /**
     * Unsubscribe from updates
     */
    unsubscribe() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }
}

/**
 * Chart Manager
 */
class ChartManager {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.candleSeries = null;
        this.ema20Series = null;
        this.ema50Series = null;
    }

    /**
     * Initialize chart
     */
    init() {
        if (!this.container) {
            console.error('Chart container not found');
            return;
        }

        this.chart = LightweightCharts.createChart(this.container, {
            layout: {
                background: { color: '#111820' },
                textColor: '#d8e0e8',
                fontSize: 12
            },
            grid: {
                vertLines: { color: '#202a34' },
                horzLines: { color: '#202a34' }
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 12
            },
            rightPriceScale: {
                borderColor: '#344150',
                scaleMargins: {
                    top: 0.3,
                    bottom: 0.25
                }
            },
            handleScale: {
                mouseWheel: true,
                pinch: true
            }
        });

        // Add candlestick series
        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00c853',
            downColor: '#ff1744',
            borderVisible: false,
            wickUpColor: '#00c853',
            wickDownColor: '#ff1744'
        });

        // Add EMA 20
        this.ema20Series = this.chart.addLineSeries({
            color: '#00d4ff',
            lineWidth: 2,
            title: 'EMA 20'
        });

        // Add EMA 50
        this.ema50Series = this.chart.addLineSeries({
            color: '#ffab00',
            lineWidth: 2,
            title: 'EMA 50'
        });

        // Handle resize
        window.addEventListener('resize', () => this.resize());
    }

    /**
     * Update chart data
     */
    update(candles, ema20, ema50) {
        if (!this.chart) return;

        // Set candle data
        this.candleSeries.setData(candles);

        // Set EMA data
        const ema20Data = candles.map((c, i) => ({
            time: c.time,
            value: ema20[i] || c.close
        }));

        const ema50Data = candles.map((c, i) => ({
            time: c.time,
            value: ema50[i] || c.close
        }));

        this.ema20Series.setData(ema20Data);
        this.ema50Series.setData(ema50Data);

        // Fit content
        this.chart.timeScale().fitContent();
    }

    /**
     * Resize chart
     */
    resize() {
        if (!this.chart || !this.container) return;

        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        this.chart.applyOptions({ width, height });
    }

    /**
     * Clear chart
     */
    clear() {
        if (this.candleSeries) this.candleSeries.setData([]);
        if (this.ema20Series) this.ema20Series.setData([]);
        if (this.ema50Series) this.ema50Series.setData([]);
    }
}

/**
 * UI Manager
 */
class UIManager {
    constructor() {
        this.elements = new Map();
    }

    /**
     * Register element
     */
    register(id, selector) {
        const element = typeof selector === 'string'
            ? document.querySelector(selector)
            : selector;

        if (element) {
            this.elements.set(id, element);
        }

        return element;
    }

    /**
     * Get element
     */
    get(id) {
        return this.elements.get(id);
    }

    /**
     * Update text
     */
    setText(id, text) {
        const el = this.get(id);
        if (el) el.textContent = text;
    }

    /**
     * Update HTML
     */
    setHTML(id, html) {
        const el = this.get(id);
        if (el) el.innerHTML = html;
    }

    /**
     * Add class
     */
    addClass(id, className) {
        const el = this.get(id);
        if (el) el.classList.add(className);
    }

    /**
     * Remove class
     */
    removeClass(id, className) {
        const el = this.get(id);
        if (el) el.classList.remove(className);
    }

    /**
     * Toggle class
     */
    toggleClass(id, className) {
        const el = this.get(id);
        if (el) el.classList.toggle(className);
    }

    /**
     * Show message
     */
    showMessage(message, type = 'info', duration = 3000) {
        const messageEl = document.createElement('div');
        messageEl.className = `message message-${type}`;
        messageEl.textContent = message;
        document.body.appendChild(messageEl);

        setTimeout(() => {
            messageEl.remove();
        }, duration);
    }

    /**
     * Disable element
     */
    disable(id) {
        const el = this.get(id);
        if (el) el.disabled = true;
    }

    /**
     * Enable element
     */
    enable(id) {
        const el = this.get(id);
        if (el) el.disabled = false;
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { TradingEngine, MarketDataProvider, ChartManager, UIManager };
}