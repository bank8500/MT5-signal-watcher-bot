import time
from datetime import datetime
import MetaTrader5 as mt5
import pandas as pd
import requests
import winsound
import os
from dotenv import load_dotenv  

# ================= CONFIG =================
load_dotenv()

MT5_PATH = os.getenv("MT5_PATH")
SYMBOL = os.getenv("SYMBOL", "XAUUSDm")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TIMEFRAME_ENTRY = mt5.TIMEFRAME_M5
TIMEFRAME_TREND = mt5.TIMEFRAME_M15

BARS = 150
CHECK_EVERY_SECONDS = 10

START_HOUR = 10
END_HOUR = 23

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
ATR_PERIOD = 14

RSI_BUY = 55
RSI_SELL = 45

MIN_EMA_GAP = 0.8
MIN_ATR = 1.5

COOLDOWN_MIN = 15
# ==========================================


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")


def beep(signal):
    if signal == "BUY":
        winsound.Beep(1200, 400)
    elif signal == "SELL":
        winsound.Beep(700, 400)


def is_trading_time():
    h = datetime.now().hour
    return START_HOUR <= h < END_HOUR


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)

    return true_range.rolling(period).mean()


def add_indicators(df):
    df["ema9"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema21"] = df["close"].ewm(span=EMA_SLOW).mean()
    df["rsi"] = calculate_rsi(df["close"], RSI_PERIOD)
    df["atr"] = calculate_atr(df, ATR_PERIOD)
    return df


def fetch(symbol, timeframe):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, BARS)
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return add_indicators(df)


def get_trend(df):
    last = df.iloc[-2]
    if last["ema9"] > last["ema21"]:
        return "UP"
    elif last["ema9"] < last["ema21"]:
        return "DOWN"
    return "FLAT"


def get_signal(entry_df, trend):
    prev = entry_df.iloc[-3]
    last = entry_df.iloc[-2]

    ema_gap = abs(last["ema9"] - last["ema21"])

    if ema_gap < MIN_EMA_GAP:
        return "NO", f"EMA GAP TOO SMALL ({ema_gap:.2f})"

    if last["atr"] < MIN_ATR:
        return "NO", f"LOW VOLATILITY ATR={last['atr']:.2f}"

    buy_cross = prev["ema9"] <= prev["ema21"] and last["ema9"] > last["ema21"]
    sell_cross = prev["ema9"] >= prev["ema21"] and last["ema9"] < last["ema21"]

    # 1) cross entry
    if trend == "UP":
        if buy_cross and last["rsi"] > RSI_BUY:
            return "BUY", "UP TREND + BUY CROSS"

        # 2) pullback entry
        if (
            last["ema9"] > last["ema21"]
            and 50 <= last["rsi"] <= 65
            and last["close"] > last["ema9"]
            and last["close"] > last["open"]
        ):
            return "BUY", "UP TREND + PULLBACK BUY"

        return "NO", f"UP TREND BUT NO BUY | RSI={last['rsi']:.2f}"

    if trend == "DOWN":
        if sell_cross and last["rsi"] < RSI_SELL:
            return "SELL", "DOWN TREND + SELL CROSS"

        if (
            last["ema9"] < last["ema21"]
            and 35 <= last["rsi"] <= 50
            and last["close"] < last["ema9"]
            and last["close"] < last["open"]
        ):
            return "SELL", "DOWN TREND + PULLBACK SELL"

        return "NO", f"DOWN TREND BUT NO SELL | RSI={last['rsi']:.2f}"

    return "NO", f"TREND={trend}"


def main():
    if not mt5.initialize(path=MT5_PATH):
        print("MT5 fail")
        return

    print("🚀 BOT V2 STARTED")
    send_telegram("🚀 Bot v2 started")

    last_alert_time = None
    last_bar_time = None

    while True:
        try:
            if not is_trading_time():
                time.sleep(30)
                continue

            entry_df = fetch(SYMBOL, TIMEFRAME_ENTRY)
            trend_df = fetch(SYMBOL, TIMEFRAME_TREND)

            last = entry_df.iloc[-2]

            if last_bar_time == last["time"]:
                time.sleep(CHECK_EVERY_SECONDS)
                continue

            last_bar_time = last["time"]

            trend = get_trend(trend_df)
            signal, reason = get_signal(entry_df, trend)

            log(f"{signal} | {reason}")

            if signal in ["BUY", "SELL"]:

                now = datetime.now()
                if last_alert_time:
                    diff = (now - last_alert_time).seconds / 60
                    if diff < COOLDOWN_MIN:
                        log("Cooldown")
                        continue

                last_alert_time = now

                msg = (
                    f"{signal} {SYMBOL}\n"
                    f"Time: {last['time']}\n"
                    f"Price: {last['close']:.2f}\n"
                    f"Trend: {trend}\n"
                    f"RSI: {last['rsi']:.2f}\n"
                    f"ATR: {last['atr']:.2f}\n"
                    f"{reason}"
                )

                print("\n" + msg + "\n")

                beep(signal)
                send_telegram(msg)

            time.sleep(CHECK_EVERY_SECONDS)

        except Exception as e:
            log(f"ERROR: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()