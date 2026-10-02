// Express server for TATA Trading Charts
const express = require('express');
const path = require('path');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.static(path.join(__dirname)));
app.use(express.json());

// Serve index.html
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// API endpoint to fetch trading data
app.get('/api/trading-data', async (req, res) => {
    try {
        const { symbol, interval } = req.query;
        const apiKey = process.env.ALPHA_VANTAGE_API_KEY || 'demo';

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

        const response = await axios.get(endpoint);
        const timeSeriesData = response.data[dataKey];

        if (!timeSeriesData) {
            return res.status(400).json({ error: 'Unable to fetch data', details: response.data });
        }

        const candles = [];
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

        res.json(candles.sort((a, b) => a.time - b.time));
    } catch (error) {
        console.error('Error fetching trading data:', error.message);
        res.status(500).json({ error: error.message });
    }
});

// Health check endpoint
app.get('/api/health', (req, res) => {
    res.json({ status: 'TATA Trading Charts Server is running' });
});

// Start server
app.listen(PORT, () => {
    console.log(`\n🚀 TATA Trading Charts Server`);
    console.log(`📊 Running at http://localhost:${PORT}`);
    console.log(`\nUsage:`);
    console.log(`  - Open http://localhost:${PORT} in your browser`);
    console.log(`  - Set ALPHA_VANTAGE_API_KEY environment variable for real data`);
    console.log(`  - Get free API key at: https://www.alphavantage.co/\n`);
});
