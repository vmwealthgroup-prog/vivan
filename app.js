// TradingView Lightweight Charts - TATA Trading App
let chart = null;
let candlestickSeries = null;
let volumeSeries = null;

// Initialize chart on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeChart();
});

function initializeChart() {
    const container = document.getElementById('chart-container');
    
    chart = LightweightCharts.createChart(container, {
        layout: {
            background: { color: '#222' },
            textColor: '#DDD',
        },
        width: container.clientWidth,
        height: container.clientHeight,
        timeScale: {
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // Add candlestick series
    candlestickSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });

    // Add volume series
    volumeSeries = chart.addHistogramSeries({
        color: '#1f77d2',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    volumeSeries.priceScale().applyOptions({
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    // Handle window resize
    window.addEventListener('resize', () => {
        const width = container.clientWidth;
        const height = container.clientHeight;
        chart.applyOptions({ width, height });
    });

    updateStatus('Chart initialized');
}

async function loadChart() {
    const symbol = document.getElementById('symbol').value || 'AAPL';
    const interval = document.getElementById('interval').value;

    updateStatus(`Loading data for ${symbol}...`);

    try {
        // Fetch real trading data
        const data = await fetchTradingData(symbol, interval);
        
        if (data.length === 0) {
            updateStatus('No data available');
            return;
        }

        // Process and set data
        const candleData = [];
        const volumeData = [];

        data.forEach((candle) => {
            candleData.push({
                time: candle.time,
                open: candle.open,
                high: candle.high,
                low: candle.low,
                close: candle.close,
            });

            volumeData.push({
                time: candle.time,
                value: candle.volume,
                color: candle.close >= candle.open ? '#26a69a' : '#ef5350',
            });
        });

        candlestickSeries.setData(candleData);
        volumeSeries.setData(volumeData);

        chart.timeScale().fitContent();
        
        updateStatus(`Loaded ${symbol} - ${data.length} candles`);
        document.getElementById('data-points').textContent = data.length;
        document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

    } catch (error) {
        updateStatus(`Error: ${error.message}`);
        console.error('Chart loading error:', error);
    }
}

async function updateChart() {
    updateStatus('Refreshing data...');
    await loadChart();
}

async function fetchTradingData(symbol, interval) {
    try {
        // Using Alpha Vantage API (free tier)
        // Get your free API key at: https://www.alphavantage.co/
        const apiKey = 'demo'; // Replace with your API key
        
        let endpoint;
        let dataKey;

        if (interval === 'D') {
            endpoint = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}&outputsize=compact`;
            dataKey = 'Time Series (Daily)';
        } else {
            const intervalMinutes = interval === '1' ? '1min' : `${interval}min`;
            endpoint = `https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=${symbol}&interval=${intervalMinutes}&apikey=${apiKey}&outputsize=compact`;
            dataKey = `Time Series (${intervalMinutes})`;
        }

        const response = await fetch(endpoint);
        const result = await response.json();

        if (!result[dataKey]) {
            console.error('API Response:', result);
            throw new Error('Unable to fetch data. Check API key and symbol.');
        }

        const timeSeriesData = result[dataKey];
        const candles = [];

        // Convert API data to chart format
        Object.entries(timeSeriesData).forEach(([timestamp, data]) => {
            const timeInSeconds = new Date(timestamp).getTime() / 1000;
            
            candles.push({
                time: timeInSeconds,
                open: parseFloat(data['1. open']),
                high: parseFloat(data['2. high']),
                low: parseFloat(data['3. low']),
                close: parseFloat(data['4. close']),
                volume: parseInt(data['5. volume']),
            });
        });

        // Sort by time ascending
        return candles.sort((a, b) => a.time - b.time);

    } catch (error) {
        console.error('Fetch error:', error);
        // Return mock data for demo
        return generateMockData();
    }
}

function generateMockData() {
    const data = [];
    let price = 100;
    const now = Math.floor(Date.now() / 1000);

    for (let i = 100; i >= 0; i--) {
        const change = (Math.random() - 0.5) * 2;
        price += change;

        data.push({
            time: now - (i * 3600), // hourly data
            open: price - Math.random(),
            high: price + Math.random() * 2,
            low: price - Math.random() * 2,
            close: price + Math.random(),
            volume: Math.floor(Math.random() * 1000000),
        });
    }

    return data;
}

function updateStatus(message) {
    document.getElementById('status').textContent = message;
}

// Auto-load default chart
loadChart();
