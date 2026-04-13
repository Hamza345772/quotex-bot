from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import random
import math
from datetime import datetime, timezone
from typing import List, Dict
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

ALL_PAIRS = [
    "EUR/USD OTC","GBP/USD OTC","USD/JPY OTC","AUD/USD OTC","USD/CAD OTC",
    "USD/CHF OTC","NZD/USD OTC","EUR/GBP OTC","EUR/JPY OTC","GBP/JPY OTC",
    "AUD/JPY OTC","EUR/AUD OTC","EUR/CAD OTC","CAD/CHF OTC","GBP/CHF OTC",
    "AUD/CAD OTC","NZD/JPY OTC","EUR/CHF OTC","GBP/AUD OTC","USD/PKR OTC",
    "USD/INR OTC","USD/TRY OTC","USD/MXN OTC","BRL/USD OTC","ARS/USD OTC",
    "USD/IDR OTC","USD/ZAR OTC","USD/NGN OTC","EUR/SGD OTC","USD/COP OTC",
    "BTC/USD OTC","DOGE/USD OTC","XRP/USD OTC","ETH/USD OTC",
    "Gold OTC","Silver OTC","US Oil OTC","Brent OTC",
    "Apple OTC","Microsoft OTC","Google OTC","Amazon OTC","Meta OTC",
    "FTSE 100 OTC","Dow Jones OTC","Nikkei 225 OTC","DAX OTC","CAC 40 OTC"
]

price_data: Dict[str, List[float]] = {}
for pair in ALL_PAIRS:
    base = random.uniform(50, 200)
    prices = [base]
    for _ in range(100):
        change = random.gauss(0, 0.3)
        prices.append(max(0.1, prices[-1] + change))
    price_data[pair] = prices

stats_store = {"total": 0, "wins": 0, "losses": 0}
active_signals: Dict[str, dict] = {}
connected_clients: List[WebSocket] = []


def simulate_price_update():
    for pair in ALL_PAIRS:
        prices = price_data[pair]
        last = prices[-1]
        change = random.gauss(0, 0.25)
        new_price = max(0.1, last + change)
        prices.append(new_price)
        if len(prices) > 200:
            prices.pop(0)


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
    return round(ema, 4)


def compute_macd(prices: List[float]):
    if len(prices) < 26:
        return 0, 0
    ema12 = compute_ema(prices, 12)
    ema26 = compute_ema(prices, 26)
    macd_line = ema12 - ema26
    signal_line = compute_ema(prices[-9:] if len(prices) >= 9 else prices, min(9, len(prices)))
    return round(macd_line, 4), round(signal_line, 4)


def compute_bollinger(prices: List[float], period: int = 20):
    if len(prices) < period:
        return prices[-1], prices[-1], prices[-1]
    recent = prices[-period:]
    mid = sum(recent) / period
    std = math.sqrt(sum((p - mid) ** 2 for p in recent) / period)
    return round(mid + 2 * std, 4), round(mid, 4), round(mid - 2 * std, 4)


def detect_candle_pattern(prices: List[float]) -> str:
    if len(prices) < 3:
        return "neutral"
    o1, c1 = prices[-3], prices[-2]
    o2, c2 = prices[-2], prices[-1]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    if c1 < o1 and c2 > o2 and body2 > body1 * 1.5:
        return "bullish_engulfing"
    if c1 > o1 and c2 < o2 and body2 > body1 * 1.5:
        return "bearish_engulfing"
    wick = abs(prices[-1] - prices[-2])
    if wick > body2 * 2:
        return "pin_bar_up" if prices[-1] > prices[-2] else "pin_bar_down"
    return "neutral"


def detect_market_structure(prices: List[float]) -> str:
    if len(prices) < 20:
        return "ranging"
    segment = prices[-20:]
    highs = [max(segment[i:i+5]) for i in range(0, 15, 5)]
    lows = [min(segment[i:i+5]) for i in range(0, 15, 5)]
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
        return "uptrend"
    if highs[-1] < highs[-2] < highs[-3] and lows[-1] < lows[-2]:
        return "downtrend"
    return "ranging"


def detect_order_block(prices: List[float]) -> str:
    if len(prices) < 10:
        return "none"
    recent = prices[-10:]
    impulse = recent[-1] - recent[0]
    if abs(impulse) > 1.5:
        return "bullish_ob" if impulse > 0 else "bearish_ob"
    return "none"


def detect_fvg(prices: List[float]) -> str:
    if len(prices) < 3:
        return "none"
    if prices[-3] < prices[-1] and prices[-2] > prices[-3]:
        return "bullish_fvg"
    if prices[-3] > prices[-1] and prices[-2] < prices[-3]:
        return "bearish_fvg"
    return "none"


def detect_liquidity_sweep(prices: List[float]) -> str:
    if len(prices) < 15:
        return "none"
    recent = prices[-15:]
    prev_high = max(recent[:-3])
    prev_low = min(recent[:-3])
    last = recent[-1]
    if recent[-2] > prev_high and last < prev_high:
        return "sweep_high"
    if recent[-2] < prev_low and last > prev_low:
        return "sweep_low"
    return "none"


def analyze_pair(pair: str, duration: int) -> dict:
    prices = price_data[pair]
    if len(prices) < 30:
        return None

    rsi = compute_rsi(prices)
    ema5 = compute_ema(prices, 5)
    ema13 = compute_ema(prices, 13)
    ema50 = compute_ema(prices, min(50, len(prices)))
    macd_line, signal_line = compute_macd(prices)
    bb_upper, bb_mid, bb_lower = compute_bollinger(prices)
    candle = detect_candle_pattern(prices)
    structure = detect_market_structure(prices)
    order_block = detect_order_block(prices)
    fvg = detect_fvg(prices)
    liq_sweep = detect_liquidity_sweep(prices)
    current_price = prices[-1]

    bull_score = 0
    bear_score = 0
    reasons = []

    # RSI
    if rsi < 30:
        bull_score += 20
        reasons.append("RSI Oversold")
    elif rsi < 45:
        bull_score += 10
        reasons.append("RSI Bullish Zone")
    elif rsi > 70:
        bear_score += 20
        reasons.append("RSI Overbought")
    elif rsi > 55:
        bear_score += 10
        reasons.append("RSI Bearish Zone")

    # EMA
    if ema5 > ema13:
        bull_score += 15
        reasons.append("EMA Bullish Cross")
    else:
        bear_score += 15
        reasons.append("EMA Bearish Cross")

    if current_price > ema50:
        bull_score += 10
        reasons.append("Above EMA50")
    else:
        bear_score += 10
        reasons.append("Below EMA50")

    # MACD
    if macd_line > signal_line:
        bull_score += 15
        reasons.append("MACD Bullish")
    else:
        bear_score += 15
        reasons.append("MACD Bearish")

    # Bollinger
    if current_price <= bb_lower:
        bull_score += 15
        reasons.append("BB Lower Band Bounce")
    elif current_price >= bb_upper:
        bear_score += 15
        reasons.append("BB Upper Band Reversal")

    # Market Structure (SMC)
    if structure == "uptrend":
        bull_score += 15
        reasons.append("SMC: Uptrend Structure")
    elif structure == "downtrend":
        bear_score += 15
        reasons.append("SMC: Downtrend Structure")

    # Order Block (ICT)
    if order_block == "bullish_ob":
        bull_score += 20
        reasons.append("ICT: Bullish Order Block")
    elif order_block == "bearish_ob":
        bear_score += 20
        reasons.append("ICT: Bearish Order Block")

    # FVG (ICT)
    if fvg == "bullish_fvg":
        bull_score += 15
        reasons.append("ICT: Bullish FVG")
    elif fvg == "bearish_fvg":
        bear_score += 15
        reasons.append("ICT: Bearish FVG")

    # Liquidity Sweep (ICT)
    if liq_sweep == "sweep_high":
        bear_score += 20
        reasons.append("ICT: Liquidity Sweep High")
    elif liq_sweep == "sweep_low":
        bull_score += 20
        reasons.append("ICT: Liquidity Sweep Low")

    # Candle Pattern
    if candle == "bullish_engulfing":
        bull_score += 15
        reasons.append("Bullish Engulfing Candle")
    elif candle == "bearish_engulfing":
        bear_score += 15
        reasons.append("Bearish Engulfing Candle")
    elif candle == "pin_bar_up":
        bull_score += 10
        reasons.append("Pin Bar Reversal Up")
    elif candle == "pin_bar_down":
        bear_score += 10
        reasons.append("Pin Bar Reversal Down")

    total = bull_score + bear_score
    if total == 0:
        return None

    if bull_score > bear_score:
        direction = "UP"
        raw_conf = bull_score / total
    else:
        direction = "DOWN"
        raw_conf = bear_score / total

    # Min confluence check — at least 3 signals needed
    signals_count = len(reasons)
    if signals_count < 3:
        return None

    confidence = round(50 + raw_conf * 48, 1)
    confidence = min(98, max(52, confidence))

    # Probability score for sorting (higher = show first)
    probability_score = round(confidence + (signals_count * 0.5), 2)

    now = datetime.now()
    entry_in = random.randint(5, 25)
    entry_time = datetime.fromtimestamp(now.timestamp() + entry_in)

    return {
        "pair": pair,
        "direction": direction,
        "confidence": confidence,
        "probability_score": probability_score,
        "reasons": reasons[:5],
        "signals_count": signals_count,
        "rsi": rsi,
        "structure": structure,
        "entry_in": entry_in,
        "entry_time": entry_time.strftime("%H:%M:%S"),
        "duration": duration,
        "status": "ready",
        "id": f"{pair}-{int(now.timestamp())}",
        "timestamp": now.isoformat()
    }


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/pairs")
async def get_pairs():
    return {"pairs": ALL_PAIRS}


@app.get("/api/stats")
async def get_stats():
    total = stats_store["total"]
    wins = stats_store["wins"]
    acc = round((wins / total * 100), 1) if total > 0 else 0
    return {**stats_store, "accuracy": acc}


@app.post("/api/result")
async def post_result(data: dict):
    outcome = data.get("outcome")
    if outcome == "win":
        stats_store["wins"] += 1
    elif outcome == "loss":
        stats_store["losses"] += 1
    stats_store["total"] += 1
    total = stats_store["total"]
    wins = stats_store["wins"]
    acc = round((wins / total * 100), 1) if total > 0 else 0
    result = {**stats_store, "accuracy": acc}
    for client in connected_clients:
        try:
            await client.send_json({"type": "stats_update", "data": result})
        except:
            pass
    return result


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "scan":
                duration = data.get("duration", 60)
                mode = data.get("mode", "scanner")
                target_pair = data.get("pair", None)

                simulate_price_update()

                if mode == "single" and target_pair:
                    pairs_to_scan = [target_pair]
                else:
                    pairs_to_scan = ALL_PAIRS

                results = []
                for pair in pairs_to_scan:
                    sig = analyze_pair(pair, duration)
                    if sig:
                        results.append(sig)

                # Sort by probability score descending
                results.sort(key=lambda x: x["probability_score"], reverse=True)

                await ws.send_json({
                    "type": "signals",
                    "data": results,
                    "stats": {**stats_store, "accuracy": round(stats_store["wins"] / stats_store["total"] * 100, 1) if stats_store["total"] > 0 else 0}
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
        connected_clients.remove(ws)
    except Exception as e:
        if ws in connected_clients:
            connected_clients.remove(ws)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
