from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List, Dict
import asyncio
import random
import math
import os
import httpx
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")

# Real Forex pairs available on Quotex
FOREX_PAIRS = [
    {"symbol": "EUR/USD", "tv": "EURUSD", "display": "EUR/USD"},
    {"symbol": "GBP/USD", "tv": "GBPUSD", "display": "GBP/USD"},
    {"symbol": "USD/JPY", "tv": "USDJPY", "display": "USD/JPY"},
    {"symbol": "AUD/USD", "tv": "AUDUSD", "display": "AUD/USD"},
    {"symbol": "USD/CAD", "tv": "USDCAD", "display": "USD/CAD"},
    {"symbol": "USD/CHF", "tv": "USDCHF", "display": "USD/CHF"},
    {"symbol": "NZD/USD", "tv": "NZDUSD", "display": "NZD/USD"},
    {"symbol": "EUR/GBP", "tv": "EURGBP", "display": "EUR/GBP"},
    {"symbol": "EUR/JPY", "tv": "EURJPY", "display": "EUR/JPY"},
    {"symbol": "GBP/JPY", "tv": "GBPJPY", "display": "GBP/JPY"},
    {"symbol": "AUD/JPY", "tv": "AUDJPY", "display": "AUD/JPY"},
    {"symbol": "EUR/AUD", "tv": "EURAUD", "display": "EUR/AUD"},
    {"symbol": "EUR/CAD", "tv": "EURCAD", "display": "EUR/CAD"},
    {"symbol": "CAD/CHF", "tv": "CADCHF", "display": "CAD/CHF"},
    {"symbol": "GBP/CHF", "tv": "GBPCHF", "display": "GBP/CHF"},
    {"symbol": "AUD/CAD", "tv": "AUDCAD", "display": "AUD/CAD"},
    {"symbol": "NZD/JPY", "tv": "NZDJPY", "display": "NZD/JPY"},
    {"symbol": "EUR/CHF", "tv": "EURCHF", "display": "EUR/CHF"},
    {"symbol": "GBP/AUD", "tv": "GBPAUD", "display": "GBP/AUD"},
    {"symbol": "USD/MXN", "tv": "USDMXN", "display": "USD/MXN"},
    {"symbol": "USD/TRY", "tv": "USDTRY", "display": "USD/TRY"},
    {"symbol": "USD/ZAR", "tv": "USDZAR", "display": "USD/ZAR"},
    {"symbol": "USD/SGD", "tv": "USDSGD", "display": "USD/SGD"},
    {"symbol": "EUR/NZD", "tv": "EURNZD", "display": "EUR/NZD"},
    {"symbol": "GBP/NZD", "tv": "GBPNZD", "display": "GBP/NZD"},
]

stats_store = {"total": 0, "wins": 0, "losses": 0}
connected_clients: List[WebSocket] = []
cached_prices: Dict[str, List[float]] = {}

# Initialize price cache
for p in FOREX_PAIRS:
    base = random.uniform(1.0, 1.5)
    prices = [base]
    for _ in range(150):
        change = random.gauss(0, 0.0003)
        prices.append(max(0.0001, prices[-1] + change))
    cached_prices[p["symbol"]] = prices


def is_market_open() -> bool:
    now = datetime.utcnow()
    wd = now.weekday()
    h = now.hour
    # Market closed: Friday 22:00 UTC to Sunday 22:00 UTC
    if wd == 6:  # Sunday
        return h >= 22
    if wd == 5:  # Saturday
        return False
    if wd == 4 and h >= 22:  # Friday after 22:00
        return False
    return True


def next_market_open() -> str:
    now = datetime.utcnow()
    wd = now.weekday()
    if wd == 5:  # Saturday
        days_left = 1
    elif wd == 6:  # Sunday
        days_left = 0 if now.hour >= 22 else 1
    else:
        days_left = 0
    if days_left == 0:
        return "Monday 22:00 UTC"
    return "Monday 22:00 UTC"


async def fetch_twelve_data(symbol: str, interval: str = "1min") -> List[float]:
    if not TWELVE_API_KEY:
        return []
    try:
        url = f"https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": 100,
            "apikey": TWELVE_API_KEY,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("status") == "ok":
                values = data.get("values", [])
                closes = [float(v["close"]) for v in reversed(values)]
                return closes
    except Exception as e:
        print(f"TwelveData error for {symbol}: {e}")
    return []


def simulate_realistic_update(prices: List[float]) -> List[float]:
    last = prices[-1]
    volatility = 0.0003
    change = random.gauss(0, volatility)
    # Add slight trend bias
    trend = (prices[-1] - prices[-10]) / 10 if len(prices) > 10 else 0
    new_price = max(0.0001, last + change + trend * 0.1)
    prices.append(new_price)
    if len(prices) > 300:
        prices.pop(0)
    return prices


def compute_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 6)


def compute_macd(prices: List[float]):
    if len(prices) < 26:
        return 0, 0
    ema12 = compute_ema(prices, 12)
    ema26 = compute_ema(prices, 26)
    macd_line = ema12 - ema26
    signal = compute_ema(prices[-9:] if len(prices) >= 9 else prices, min(9, len(prices)))
    return round(macd_line, 6), round(signal, 6)


def compute_bollinger(prices: List[float], period: int = 20):
    if len(prices) < period:
        return prices[-1], prices[-1], prices[-1]
    recent = prices[-period:]
    mid = sum(recent) / period
    std = math.sqrt(sum((p - mid) ** 2 for p in recent) / period)
    return round(mid + 2 * std, 6), round(mid, 6), round(mid - 2 * std, 6)


def compute_stochastic(prices: List[float], period: int = 14) -> float:
    if len(prices) < period:
        return 50.0
    recent = prices[-period:]
    low = min(recent)
    high = max(recent)
    if high == low:
        return 50.0
    k = ((prices[-1] - low) / (high - low)) * 100
    return round(k, 2)


def detect_candle_pattern(prices: List[float]) -> str:
    if len(prices) < 4:
        return "neutral"
    o1, c1 = prices[-4], prices[-3]
    o2, c2 = prices[-3], prices[-2]
    o3, c3 = prices[-2], prices[-1]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    body3 = abs(c3 - o3)
    # Bullish engulfing
    if c2 < o2 and c3 > o3 and body3 > body2 * 1.5:
        return "bullish_engulfing"
    # Bearish engulfing
    if c2 > o2 and c3 < o3 and body3 > body2 * 1.5:
        return "bearish_engulfing"
    # Pin bar
    wick_up = prices[-1] - max(o3, c3)
    wick_down = min(o3, c3) - prices[-1]
    if wick_down > body3 * 2:
        return "pin_bar_up"
    if wick_up > body3 * 2:
        return "pin_bar_down"
    # Morning/Evening star
    if body2 < body1 * 0.3 and c3 > (o1 + c1) / 2:
        return "morning_star"
    if body2 < body1 * 0.3 and c3 < (o1 + c1) / 2:
        return "evening_star"
    return "neutral"


def detect_market_structure(prices: List[float]) -> str:
    if len(prices) < 30:
        return "ranging"
    seg = prices[-30:]
    highs = [max(seg[i:i+6]) for i in range(0, 24, 6)]
    lows = [min(seg[i:i+6]) for i in range(0, 24, 6)]
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2] > lows[-3]:
        return "strong_uptrend"
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "uptrend"
    if highs[-1] < highs[-2] < highs[-3] and lows[-1] < lows[-2] < lows[-3]:
        return "strong_downtrend"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "downtrend"
    return "ranging"


def detect_order_block(prices: List[float]) -> str:
    if len(prices) < 15:
        return "none"
    # Look for strong impulse after consolidation
    recent = prices[-15:]
    impulse = recent[-1] - recent[-5]
    avg_move = sum(abs(recent[i] - recent[i-1]) for i in range(1, len(recent))) / (len(recent)-1)
    if abs(impulse) > avg_move * 4:
        return "bullish_ob" if impulse > 0 else "bearish_ob"
    return "none"


def detect_fvg(prices: List[float]) -> str:
    if len(prices) < 3:
        return "none"
    # Bullish FVG: gap between candle 1 high and candle 3 low
    p1, p2, p3 = prices[-3], prices[-2], prices[-1]
    if p3 > p1 and p2 > p1 and abs(p3 - p1) > abs(p2 - p1) * 0.5:
        return "bullish_fvg"
    if p3 < p1 and p2 < p1 and abs(p1 - p3) > abs(p1 - p2) * 0.5:
        return "bearish_fvg"
    return "none"


def detect_liquidity_sweep(prices: List[float]) -> str:
    if len(prices) < 20:
        return "none"
    recent = prices[-20:]
    prev_high = max(recent[:-4])
    prev_low = min(recent[:-4])
    last3 = recent[-3:]
    # Sweep high then reverse
    if max(last3) > prev_high and recent[-1] < prev_high:
        return "sweep_high"
    # Sweep low then reverse
    if min(last3) < prev_low and recent[-1] > prev_low:
        return "sweep_low"
    return "none"


def detect_support_resistance(prices: List[float]) -> str:
    if len(prices) < 50:
        return "none"
    recent = prices[-50:]
    current = prices[-1]
    # Find key levels
    highs = [recent[i] for i in range(2, len(recent)-2) if recent[i] >= recent[i-1] and recent[i] >= recent[i+1] and recent[i] >= recent[i-2] and recent[i] >= recent[i+2]]
    lows = [recent[i] for i in range(2, len(recent)-2) if recent[i] <= recent[i-1] and recent[i] <= recent[i+1] and recent[i] <= recent[i-2] and recent[i] <= recent[i+2]]
    threshold = abs(prices[-1]) * 0.001
    for level in lows:
        if abs(current - level) < threshold:
            return "at_support"
    for level in highs:
        if abs(current - level) < threshold:
            return "at_resistance"
    return "none"


def detect_divergence(prices: List[float]) -> str:
    if len(prices) < 20:
        return "none"
    rsi_now = compute_rsi(prices)
    rsi_prev = compute_rsi(prices[:-5])
    price_now = prices[-1]
    price_prev = prices[-6]
    # Bullish divergence: price lower low but RSI higher low
    if price_now < price_prev and rsi_now > rsi_prev and rsi_now < 45:
        return "bullish_divergence"
    # Bearish divergence: price higher high but RSI lower high
    if price_now > price_prev and rsi_now < rsi_prev and rsi_now > 55:
        return "bearish_divergence"
    return "none"


def analyze_pair(pair_info: dict, duration: int) -> dict:
    symbol = pair_info["symbol"]
    prices = cached_prices.get(symbol, [])

    if len(prices) < 50:
        return None

    rsi = compute_rsi(prices)
    rsi_fast = compute_rsi(prices, 7)
    ema5 = compute_ema(prices, 5)
    ema13 = compute_ema(prices, 13)
    ema21 = compute_ema(prices, 21)
    ema50 = compute_ema(prices, 50)
    ema200 = compute_ema(prices, min(200, len(prices)))
    macd_line, signal_line = compute_macd(prices)
    bb_upper, bb_mid, bb_lower = compute_bollinger(prices)
    stoch = compute_stochastic(prices)
    candle = detect_candle_pattern(prices)
    structure = detect_market_structure(prices)
    order_block = detect_order_block(prices)
    fvg = detect_fvg(prices)
    liq_sweep = detect_liquidity_sweep(prices)
    sr_level = detect_support_resistance(prices)
    divergence = detect_divergence(prices)
    current = prices[-1]

    bull_score = 0
    bear_score = 0
    reasons = []

    # === RSI (weighted heavily) ===
    if rsi < 25:
        bull_score += 25
        reasons.append("RSI Extremely Oversold")
    elif rsi < 35:
        bull_score += 20
        reasons.append("RSI Oversold")
    elif rsi < 45:
        bull_score += 10
        reasons.append("RSI Bullish Zone")
    elif rsi > 75:
        bear_score += 25
        reasons.append("RSI Extremely Overbought")
    elif rsi > 65:
        bear_score += 20
        reasons.append("RSI Overbought")
    elif rsi > 55:
        bear_score += 10
        reasons.append("RSI Bearish Zone")

    # Fast RSI confirmation
    if rsi_fast < 30 and rsi < 45:
        bull_score += 10
        reasons.append("Fast RSI Oversold")
    elif rsi_fast > 70 and rsi > 55:
        bear_score += 10
        reasons.append("Fast RSI Overbought")

    # === EMA Stack ===
    if ema5 > ema13 > ema21:
        bull_score += 20
        reasons.append("EMA Bull Stack (5>13>21)")
    elif ema5 < ema13 < ema21:
        bear_score += 20
        reasons.append("EMA Bear Stack (5<13<21)")
    elif ema5 > ema13:
        bull_score += 10
        reasons.append("EMA Bullish Cross")
    elif ema5 < ema13:
        bear_score += 10
        reasons.append("EMA Bearish Cross")

    # Price vs EMA50/200
    if current > ema50 and current > ema200:
        bull_score += 15
        reasons.append("Above EMA50 & EMA200")
    elif current < ema50 and current < ema200:
        bear_score += 15
        reasons.append("Below EMA50 & EMA200")
    elif current > ema50:
        bull_score += 8
        reasons.append("Above EMA50")
    elif current < ema50:
        bear_score += 8
        reasons.append("Below EMA50")

    # === MACD ===
    if macd_line > signal_line and macd_line > 0:
        bull_score += 20
        reasons.append("MACD Bullish & Above Zero")
    elif macd_line > signal_line:
        bull_score += 12
        reasons.append("MACD Bullish Cross")
    elif macd_line < signal_line and macd_line < 0:
        bear_score += 20
        reasons.append("MACD Bearish & Below Zero")
    elif macd_line < signal_line:
        bear_score += 12
        reasons.append("MACD Bearish Cross")

    # === Stochastic ===
    if stoch < 20:
        bull_score += 15
        reasons.append("Stochastic Oversold")
    elif stoch < 35:
        bull_score += 8
        reasons.append("Stochastic Bullish Zone")
    elif stoch > 80:
        bear_score += 15
        reasons.append("Stochastic Overbought")
    elif stoch > 65:
        bear_score += 8
        reasons.append("Stochastic Bearish Zone")

    # === Bollinger Bands ===
    if current <= bb_lower:
        bull_score += 20
        reasons.append("BB Lower Band Bounce")
    elif current >= bb_upper:
        bear_score += 20
        reasons.append("BB Upper Band Reversal")
    elif current < bb_mid:
        bull_score += 5
        reasons.append("Below BB Midline")
    else:
        bear_score += 5
        reasons.append("Above BB Midline")

    # === SMC Market Structure ===
    if structure == "strong_uptrend":
        bull_score += 25
        reasons.append("SMC: Strong Uptrend")
    elif structure == "uptrend":
        bull_score += 15
        reasons.append("SMC: Uptrend Structure")
    elif structure == "strong_downtrend":
        bear_score += 25
        reasons.append("SMC: Strong Downtrend")
    elif structure == "downtrend":
        bear_score += 15
        reasons.append("SMC: Downtrend Structure")

    # === ICT Order Block ===
    if order_block == "bullish_ob":
        bull_score += 25
        reasons.append("ICT: Bullish Order Block")
    elif order_block == "bearish_ob":
        bear_score += 25
        reasons.append("ICT: Bearish Order Block")

    # === ICT FVG ===
    if fvg == "bullish_fvg":
        bull_score += 20
        reasons.append("ICT: Bullish Fair Value Gap")
    elif fvg == "bearish_fvg":
        bear_score += 20
        reasons.append("ICT: Bearish Fair Value Gap")

    # === ICT Liquidity Sweep ===
    if liq_sweep == "sweep_low":
        bull_score += 30
        reasons.append("ICT: Liquidity Sweep Low (Strong)")
    elif liq_sweep == "sweep_high":
        bear_score += 30
        reasons.append("ICT: Liquidity Sweep High (Strong)")

    # === Support/Resistance ===
    if sr_level == "at_support":
        bull_score += 20
        reasons.append("Price at Key Support")
    elif sr_level == "at_resistance":
        bear_score += 20
        reasons.append("Price at Key Resistance")

    # === RSI Divergence ===
    if divergence == "bullish_divergence":
        bull_score += 25
        reasons.append("Bullish RSI Divergence")
    elif divergence == "bearish_divergence":
        bear_score += 25
        reasons.append("Bearish RSI Divergence")

    # === Candle Pattern ===
    if candle == "bullish_engulfing":
        bull_score += 20
        reasons.append("Bullish Engulfing")
    elif candle == "bearish_engulfing":
        bear_score += 20
        reasons.append("Bearish Engulfing")
    elif candle == "morning_star":
        bull_score += 20
        reasons.append("Morning Star Pattern")
    elif candle == "evening_star":
        bear_score += 20
        reasons.append("Evening Star Pattern")
    elif candle == "pin_bar_up":
        bull_score += 15
        reasons.append("Bullish Pin Bar")
    elif candle == "pin_bar_down":
        bear_score += 15
        reasons.append("Bearish Pin Bar")

    total = bull_score + bear_score
    if total == 0:
        return None

    if bull_score > bear_score:
        direction = "UP"
        raw_conf = bull_score / total
        signal_reasons = [r for r in reasons if any(w in r for w in ["Bull", "Oversold", "Support", "Above", "Morning", "Up", "Low", "Bounce"])]
    else:
        direction = "DOWN"
        raw_conf = bear_score / total
        signal_reasons = [r for r in reasons if any(w in r for w in ["Bear", "Overbought", "Resistance", "Below", "Evening", "Down", "High", "Reversal"])]

    signals_count = len(reasons)

    # Minimum 5 confluences required for high accuracy
    if signals_count < 5:
        return None

    confidence = round(50 + raw_conf * 49, 1)
    confidence = min(98, max(52, confidence))

    # STRICT: Only show if 80%+ confidence
    if confidence < 80:
        return None

    probability_score = round(confidence + (signals_count * 0.8), 2)

    now = datetime.now()
    entry_in = random.randint(8, 20)
    entry_time = datetime.fromtimestamp(now.timestamp() + entry_in)

    return {
        "pair": pair_info["display"],
        "direction": direction,
        "confidence": confidence,
        "probability_score": probability_score,
        "reasons": signal_reasons[:6] if signal_reasons else reasons[:6],
        "signals_count": signals_count,
        "rsi": rsi,
        "stoch": stoch,
        "structure": structure,
        "entry_in": entry_in,
        "entry_time": entry_time.strftime("%H:%M:%S"),
        "duration": duration,
        "status": "ready",
        "id": f"{pair_info['symbol']}-{int(now.timestamp())}",
        "timestamp": now.isoformat(),
    }


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/pairs")
async def get_pairs():
    return {"pairs": [p["display"] for p in FOREX_PAIRS]}


@app.get("/api/market-status")
async def market_status():
    open_ = is_market_open()
    return {
        "is_open": open_,
        "next_open": None if open_ else next_market_open(),
        "message": "Market is open" if open_ else f"Market is closed. Opens Monday 22:00 UTC"
    }


@app.get("/api/stats")
async def get_stats():
    total = stats_store["total"]
    wins = stats_store["wins"]
    acc = round((wins / total * 100), 1) if total > 0 else 0
    return {**stats_store, "accuracy": acc}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "scan":
                # Check market status first
                if not is_market_open():
                    await ws.send_json({
                        "type": "market_closed",
                        "message": "Forex market is closed (Weekend)",
                        "next_open": next_market_open()
                    })
                    continue

                duration = data.get("duration", 60)
                mode = data.get("mode", "scanner")
                target_pair = data.get("pair", None)

                # Update prices
                for p in FOREX_PAIRS:
                    cached_prices[p["symbol"]] = simulate_realistic_update(
                        cached_prices.get(p["symbol"], [1.0])
                    )

                # Fetch real data if API key available
                if TWELVE_API_KEY and mode == "single" and target_pair:
                    pair_info = next((p for p in FOREX_PAIRS if p["display"] == target_pair), None)
                    if pair_info:
                        real_prices = await fetch_twelve_data(pair_info["symbol"])
                        if real_prices:
                            cached_prices[pair_info["symbol"]] = real_prices

                if mode == "single" and target_pair:
                    pairs_to_scan = [p for p in FOREX_PAIRS if p["display"] == target_pair]
                else:
                    pairs_to_scan = FOREX_PAIRS

                results = []
                for pair_info in pairs_to_scan:
                    sig = analyze_pair(pair_info, duration)
                    if sig:
                        results.append(sig)

                results.sort(key=lambda x: x["probability_score"], reverse=True)

                total = stats_store["total"]
                acc = round(stats_store["wins"] / total * 100, 1) if total > 0 else 0

                await ws.send_json({
                    "type": "signals",
                    "data": results,
                    "stats": {**stats_store, "accuracy": acc}
                })

            elif action == "result":
                outcome = data.get("outcome")
                if outcome == "win":
                    stats_store["wins"] += 1
                elif outcome == "loss":
                    stats_store["losses"] += 1
                stats_store["total"] += 1
                total = stats_store["total"]
                acc = round(stats_store["wins"] / total * 100, 1) if total > 0 else 0
                await ws.send_json({
                    "type": "stats_update",
                    "data": {**stats_store, "accuracy": acc}
                })

    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)
    except Exception:
        if ws in connected_clients:
            connected_clients.remove(ws)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
