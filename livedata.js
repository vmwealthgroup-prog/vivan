/**
 * SPOTTREND Live Data Provider
 * Real-time market data integration with Yahoo Finance WebSocket
 */

class LiveDataProvider {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.subscriptions = new Map();
        this.callbacks = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 3000;
        this.messageQueue = [];
    }

    /**
     * Connect to Yahoo Finance WebSocket
     */
    connect() {
        return new Promise((resolve, reject) => {
            try {
                this.ws = new WebSocket('wss://streamer.finance.yahoo.com/?version=2');

                this.ws.onopen = () => {
                    console.log('✅ Connected to Yahoo Finance WebSocket');
                    this.isConnected = true;
                    this.reconnectAttempts = 0;
                    this.flushMessageQueue();
                    resolve();
                };

                this.ws.onmessage = (event) => {
                    this.handleMessage(event.data);
                };

                this.ws.onerror = (error) => {
                    console.error('❌ WebSocket Error:', error);
                    this.isConnected = false;
                    reject(error);
                };

                this.ws.onclose = () => {
                    console.warn('⚠️ WebSocket Closed');
                    this.isConnected = false;
                    this.attemptReconnect();
                };

            } catch (error) {
                console.error('Connection Error:', error);
                reject(error);
            }
        });
    }

    /**
     * Subscribe to a symbol's real-time data
     */
    subscribe(symbols, callback) {
        if (typeof symbols === 'string') {
            symbols = [symbols];
        }

        // Store callback
        if (callback && !this.callbacks.includes(callback)) {
            this.callbacks.push(callback);
        }

        // Subscribe to each symbol
        symbols.forEach(symbol => {
            this.subscriptions.set(symbol, {
                symbol,
                lastPrice: null,
                lastUpdate: null,
                bid: null,
                ask: null,
                volume: 0
            });

            // Send subscription message
            const subscribeMsg = {
                subscribe: [symbol]
            };

            this.sendMessage(subscribeMsg);
            console.log(`📡 Subscribed to ${symbol}`);
        });
    }

    /**
     * Unsubscribe from a symbol
     */
    unsubscribe(symbols) {
        if (typeof symbols === 'string') {
            symbols = [symbols];
        }

        symbols.forEach(symbol => {
            this.subscriptions.delete(symbol);
            
            const unsubscribeMsg = {
                unsubscribe: [symbol]
            };

            this.sendMessage(unsubscribeMsg);
            console.log(`📴 Unsubscribed from ${symbol}`);
        });
    }

    /**
     * Send message to WebSocket
     */
    sendMessage(message) {
        if (this.isConnected && this.ws) {
            try {
                this.ws.send(JSON.stringify(message));
            } catch (error) {
                console.error('Error sending message:', error);
                this.messageQueue.push(message);
            }
        } else {
            this.messageQueue.push(message);
        }
    }

    /**
     * Handle incoming WebSocket messages
     */
    handleMessage(data) {
        try {
            const message = JSON.parse(data);

            // Handle different message types
            if (message.data) {
                const quoteData = message.data.quoteType === 'EQUITY' ? message.data : null;

                if (quoteData) {
                    const quote = {
                        symbol: quoteData.symbol,
                        price: quoteData.regularMarketPrice || quoteData.preMarketPrice,
                        bid: quoteData.bid,
                        ask: quoteData.ask,
                        bidSize: quoteData.bidSize,
                        askSize: quoteData.askSize,
                        volume: quoteData.regularMarketVolume,
                        change: quoteData.regularMarketChange,
                        changePercent: quoteData.regularMarketChangePercent,
                        high: quoteData.regularMarketDayHigh,
                        low: quoteData.regularMarketDayLow,
                        open: quoteData.regularMarketOpen,
                        previousClose: quoteData.regularMarketPreviousClose,
                        timestamp: new Date(quoteData.quoteTime * 1000),
                        marketState: quoteData.marketState
                    };

                    // Update subscription
                    if (this.subscriptions.has(quoteData.symbol)) {
                        const sub = this.subscriptions.get(quoteData.symbol);
                        sub.lastPrice = quote.price;
                        sub.lastUpdate = quote.timestamp;
                        sub.bid = quote.bid;
                        sub.ask = quote.ask;
                        sub.volume = quote.volume;
                    }

                    // Call all registered callbacks
                    this.callbacks.forEach(callback => {
                        try {
                            callback(quote);
                        } catch (error) {
                            console.error('Callback error:', error);
                        }
                    });
                }
            }

        } catch (error) {
            console.error('Message parse error:', error);
        }
    }

    /**
     * Flush queued messages
     */
    flushMessageQueue() {
        while (this.messageQueue.length > 0) {
            const message = this.messageQueue.shift();
            this.sendMessage(message);
        }
    }

    /**
     * Attempt to reconnect
     */
    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`🔄 Reconnecting... (Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

            setTimeout(() => {
                this.connect().catch(error => {
                    console.error('Reconnect failed:', error);
                });
            }, this.reconnectDelay);
        } else {
            console.error('❌ Max reconnection attempts reached');
        }
    }

    /**
     * Get subscription data
     */
    getSubscription(symbol) {
        return this.subscriptions.get(symbol);
    }

    /**
     * Get all subscriptions
     */
    getAllSubscriptions() {
        return Array.from(this.subscriptions.values());
    }

    /**
     * Disconnect WebSocket
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.isConnected = false;
            console.log('🔌 Disconnected from Yahoo Finance');
        }
    }
}

/**
 * Historical Data Fetcher
 * Fetch OHLCV data for chart initialization
 */
class HistoricalDataFetcher {
    constructor() {
        this.baseUrl = 'https://query1.finance.yahoo.com/v7/finance/download';
    }

    /**
     * Fetch historical data
     */
    async fetchCandles(symbol, interval = '5m', period = '1d') {
        try {
            // Yahoo Finance download endpoint
            const params = new URLSearchParams({
                interval: interval,
                period1: Math.floor(Date.now() / 1000) - (86400 * 30), // 30 days ago
                period2: Math.floor(Date.now() / 1000),
                events: 'history',
                includeAdjustedClose: 'true'
            });

            const url = `${this.baseUrl}/${symbol}?${params}`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const text = await response.text();
            return this.parseCSV(text);

        } catch (error) {
            console.error('Error fetching historical data:', error);
            return [];
        }
    }

    /**
     * Parse CSV response
     */
    parseCSV(csvText) {
        const lines = csvText.trim().split('\n');
        const candles = [];

        // Skip header
        for (let i = 1; i < lines.length; i++) {
            const parts = lines[i].split(',');

            if (parts.length >= 6) {
                const date = new Date(parts[0]);
                const candle = {
                    time: Math.floor(date.getTime() / 1000),
                    open: parseFloat(parts[1]),
                    high: parseFloat(parts[2]),
                    low: parseFloat(parts[3]),
                    close: parseFloat(parts[4]),
                    volume: parseInt(parts[6]) || 0
                };

                candles.push(candle);
            }
        }

        return candles.sort((a, b) => a.time - b.time);
    }

    /**
     * Fetch intraday data (alternative method)
     */
    async fetchIntradayData(symbol, interval = '5m') {
        try {
            const params = new URLSearchParams({
                symbol: symbol,
                interval: interval
            });

            // Using alternative endpoint
            const url = `https://query1.finance.yahoo.com/v10/finance/quoteSummary/${symbol}?modules=price`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            return data;

        } catch (error) {
            console.error('Error fetching intraday data:', error);
            return null;
        }
    }
}

/**
 * Market Data Aggregator
 * Combines WebSocket live data with historical data
 */
class MarketDataAggregator {
    constructor() {
        this.liveProvider = new LiveDataProvider();
        this.historicalFetcher = new HistoricalDataFetcher();
        this.candles = [];
        this.currentSymbol = null;
        this.updateCallback = null;
    }

    /**
     * Initialize with symbol and fetch both historical and live data
     */
    async initialize(symbol = 'NIFTY', interval = '5m') {
        this.currentSymbol = symbol;

        try {
            // Fetch historical data first
            console.log(`📊 Fetching historical data for ${symbol}...`);
            const historical = await this.historicalFetcher.fetchCandles(symbol, interval);

            if (historical.length > 0) {
                this.candles = historical.slice(-250); // Keep last 250 candles
                console.log(`✅ Loaded ${this.candles.length} historical candles`);
            } else {
                console.warn('No historical data found, using demo data');
                this.candles = this.generateDemoCandles();
            }

            // Connect to live data
            await this.liveProvider.connect();
            this.liveProvider.subscribe(symbol, (quote) => {
                this.handleLiveUpdate(quote);
            });

            return this.candles;

        } catch (error) {
            console.error('Initialization error:', error);
            console.log('Falling back to demo data...');
            return this.generateDemoCandles();
        }
    }

    /**
     * Handle live price updates
     */
    handleLiveUpdate(quote) {
        if (quote.symbol !== this.currentSymbol) return;

        // Update last candle or create new one
        const now = Math.floor(Date.now() / 1000);
        const lastCandle = this.candles[this.candles.length - 1];

        if (lastCandle && (now - lastCandle.time) < 300) {
            // Update current candle
            lastCandle.close = quote.price;
            lastCandle.high = Math.max(lastCandle.high, quote.price);
            lastCandle.low = Math.min(lastCandle.low, quote.price);
            lastCandle.volume = quote.volume;
        } else {
            // Create new candle
            this.candles.push({
                time: now,
                open: quote.price,
                high: quote.price,
                low: quote.price,
                close: quote.price,
                volume: quote.volume || 0
            });

            // Keep only last 250 candles
            if (this.candles.length > 250) {
                this.candles.shift();
            }
        }

        // Call update callback
        if (this.updateCallback) {
            this.updateCallback({
                candles: this.candles,
                quote: quote
            });
        }
    }

    /**
     * Register callback for updates
     */
    onUpdate(callback) {
        this.updateCallback = callback;
    }

    /**
     * Generate demo candles (fallback)
     */
    generateDemoCandles(count = 250) {
        const candles = [];
        let price = 25000;
        const now = Math.floor(Date.now() / 1000);

        for (let i = 0; i < count; i++) {
            const time = now - ((count - i) * 300);
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
     * Get current candles
     */
    getCandles() {
        return this.candles;
    }

    /**
     * Get live quote for symbol
     */
    getLiveQuote(symbol = this.currentSymbol) {
        return this.liveProvider.getSubscription(symbol);
    }

    /**
     * Disconnect and cleanup
     */
    disconnect() {
        this.liveProvider.disconnect();
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { LiveDataProvider, HistoricalDataFetcher, MarketDataAggregator };
}