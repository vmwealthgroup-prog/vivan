# 🚀 TATA - Algorithmic Trading Charts

Real-time trading charts visualization for algorithmic trading strategies using TradingView's Lightweight Charts library.

## Features

✨ **Real-Time Charts**
- Candlestick charts with volume indicators
- Multiple timeframe support (1min, 5min, 15min, 1hour, 1day)
- Interactive zoom and pan controls
- Dark theme optimized for trading

📊 **Data Integration**
- Real-time stock market data via Alpha Vantage API
- Support for any trading symbol
- High-performance rendering with lightweight-charts
- Mock data for demo purposes

🛠️ **Algo Trading Ready**
- Backend API for data fetching
- Easy integration with trading algorithms
- RESTful endpoints for data access
- Extensible architecture

## Quick Start

### 1. Install Dependencies
```bash
npm install
```

### 2. Get API Key (Optional)
For real data, get a free API key:
- Visit: https://www.alphavantage.co/
- Sign up for free tier
- Copy your API key

### 3. Run the Server
```bash
# Without real data (uses demo API)
npm start

# With real data (set your API key)
ALPHA_VANTAGE_API_KEY=your_api_key npm start
```

### 4. Open in Browser
Visit: `http://localhost:3000`

## Usage

1. **Enter a stock symbol** (e.g., AAPL, GOOGL, TSLA)
2. **Select a timeframe** (1min, 5min, 15min, 1hour, 1day)
3. **Click "Load Chart"** to fetch and display data
4. **Click "Refresh Data"** to update with latest candles

## API Endpoints

### Fetch Trading Data
```
GET /api/trading-data?symbol=AAPL&interval=60
```

### Health Check
```
GET /api/health
```

## Project Structure

```
tata/
├── index.html          # Frontend UI
├── app.js              # Chart initialization and data handling
├── server.js           # Express backend server
├── package.json        # Dependencies
└── README.md           # Documentation
```

## Technology Stack

- **Frontend**: TradingView Lightweight Charts (4.1.0)
- **Backend**: Express.js, Node.js
- **Data Source**: Alpha Vantage API
- **Styling**: CSS3 with dark theme

## Integration with Algo Trading

The TATA charts are designed to integrate with algorithmic trading systems:

```javascript
// Example: Get chart data for your algo
const response = await fetch('/api/trading-data?symbol=AAPL&interval=60');
const data = await response.json();

// Process for your trading algorithm
data.forEach(candle => {
    // Your algo logic here
    analyzeCandle(candle);
});
```

## Configuration

### Environment Variables
```bash
ALPHA_VANTAGE_API_KEY    # Your Alpha Vantage API key
PORT                      # Server port (default: 3000)
```

### Chart Customization
Edit `app.js` to customize:
- Color schemes
- Technical indicators
- Data timeframes
- Volume display options

## Roadmap

- [ ] Multiple technical indicators (SMA, EMA, RSI, MACD)
- [ ] Real-time WebSocket updates
- [ ] Trade history tracking
- [ ] Strategy backtesting
- [ ] Alert system
- [ ] Export chart data

## Troubleshooting

**"Unable to fetch data"**
- Check your internet connection
- Verify Alpha Vantage API key
- Check symbol spelling (e.g., AAPL)

**Chart not rendering**
- Clear browser cache
- Check browser console for errors
- Ensure server is running on port 3000

**Rate limiting**
- Free API tier has 5 requests/minute limit
- Upgrade plan for higher limits

## Support

For issues or questions:
1. Check the [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/)
2. Review [Lightweight Charts docs](https://tradingview.github.io/lightweight-charts/)
3. Open an issue in the repository

## License

MIT

---

**Happy Trading! 📈**
