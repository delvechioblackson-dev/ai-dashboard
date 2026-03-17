import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os

FASTFOREX_API_KEY = "3f620b8b32-36d07209f8-t9y7ax"
TELEGRAM_TOKEN_DEFAULT = "8315640824:AAE1fjoNkzwDAtWhTpLVNmSWKLyUlfQkrk8"
TELEGRAM_CHAT_ID_DEFAULT = "6275880448"


def send_telegram_alert(message: str):
    """Stuur een simpele Telegram-alert (optioneel).

    Bronvolgorde voor configuratie:
    1. Waarden uit de Streamlit-UI (session_state)
    2. Environment-variabelen
    3. Eventueel Streamlit secrets
    """

    # 1) Waarden uit de Streamlit-UI (indien gezet)
    ui_token = st.session_state.get("TELEGRAM_TOKEN_UI")
    ui_chat_id = st.session_state.get("TELEGRAM_CHAT_ID_UI")

    # 2) Environment-variabelen als fallback
    token = ui_token or os.getenv("TELEGRAM_TOKEN")
    chat_id = ui_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    # Probeer optioneel Streamlit secrets te lezen, maar vang de fout af
    if (not token) or (not chat_id):
        try:
            # st.secrets is alleen beschikbaar als secrets.toml bestaat
            secrets = getattr(st, "secrets", None)
            if secrets is not None:
                if not token and "TELEGRAM_TOKEN" in secrets:
                    token = secrets["TELEGRAM_TOKEN"]
                if not chat_id and "TELEGRAM_CHAT_ID" in secrets:
                    chat_id = secrets["TELEGRAM_CHAT_ID"]
        except Exception:
            # Als secrets niet geconfigureerd zijn, gewoon stilletjes geen alerts sturen
            pass

    # 3) Vaste standaardwaarden uit deze app als laatste fallback
    if not token and TELEGRAM_TOKEN_DEFAULT:
        token = TELEGRAM_TOKEN_DEFAULT
    if not chat_id and TELEGRAM_CHAT_ID_DEFAULT:
        chat_id = TELEGRAM_CHAT_ID_DEFAULT

    if not token or not chat_id:
        st.warning("Telegram is niet geconfigureerd (token of chat ID mist). Geen alert verstuurd.")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Iets ruimere timeout zodat tijdelijke netwerkvertraging geen directe fout geeft
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=15)
        if resp.status_code != 200:
            # Toon korte foutmelding zonder geheime gegevens
            try:
                info = resp.json()
                desc = info.get("description", "onbekende fout")
            except Exception:
                desc = resp.text[:200]
            st.warning(f"Telegram API-fout ({resp.status_code}): {desc}")
    except Exception as e:
        # Geen harde fout in de UI – maar nu wel een zichtbare waarschuwing
        st.warning(f"Kon Telegram-alert niet versturen: {e}")


def build_news_query(instrument_type, base_currency=None, target_currency=None, index_choice=None):
    """Maak een simpele zoekquery voor nieuws op basis van instrument."""
    if instrument_type == "Forex" and base_currency and target_currency:
        pair = f"{base_currency}{target_currency}"
        # Richt je vooral op valuta + algemene macro/FX termen
        return f"({base_currency} OR {target_currency} OR {pair}) AND (forex OR currency OR FX OR ECB OR FED OR central bank OR interest rates)"

    if index_choice:
        if index_choice.startswith("US30"):
            return "(Dow Jones OR \"US30\" OR \"Dow\" OR \"DJIA\") AND (stocks OR index OR futures)"
        if index_choice.startswith("NAS100"):
            return "(Nasdaq 100 OR \"Nasdaq\" OR \"NAS100\") AND (stocks OR index OR futures)"

    # Fallback: breed marktnieuws
    return "(forex OR stocks OR indices) AND (market OR economy OR inflation OR interest rates)"


def fetch_news_articles(query, api_key, language="en", max_articles=8):
    """Haal nieuwsartikelen op via NewsData.io (alleen metadata: titel, beschrijving, url).

    Gebruikt de endpoint:
        https://newsdata.io/api/1/latest?apikey=...&q=...
    """
    if not api_key:
        return []

    url = "https://newsdata.io/api/1/latest"
    params = {
        "apikey": api_key,
        "q": query,
        "language": language,
        "page": 1,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if not data or data.get("status") not in ("success", True):
            # NewsData.io returns status 'success' on success
            st.warning(f"News API fout: {data.get('message', 'onbekende fout') if isinstance(data, dict) else 'onbekend antwoord'}")
            return []

        articles = []
        for a in data.get("results", [])[:max_articles]:
            articles.append(
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "url": a.get("link") or a.get("source_url"),
                    "source": a.get("source_id", ""),
                    "publishedAt": a.get("pubDate", ""),
                }
            )
        return articles
    except Exception as e:
        st.warning(f"Kon nieuws niet ophalen: {e}")
        return []


def analyze_news_sentiment(articles):
    """Eenvoudige sentiment-score op basis van woorden in titel + beschrijving.

    Geeft een dict terug met 'score' (-1 t/m 1) en een label: Bullish / Bearish / Neutraal.
    Dit is bewust simpel gehouden als extra filter bovenop je technische signalen.
    """
    if not articles:
        return {"score": 0.0, "label": "Neutraal (geen nieuws)"}

    positive_words = [
        "rises",
        "rise",
        "surge",
        "rally",
        "record high",
        "growth",
        "strong",
        "bullish",
        "optimistic",
        "rebound",
        "recovery",
        "beats expectations",
    ]
    negative_words = [
        "falls",
        "fall",
        "plunge",
        "selloff",
        "recession",
        "weak",
        "bearish",
        "pessimistic",
        "crisis",
        "war",
        "inflation",
        "rate hike",
        "cuts forecast",
    ]

    total_score = 0
    for art in articles:
        text = f"{art.get('title', '')} {art.get('description', '')}".lower()
        score = 0
        for w in positive_words:
            if w in text:
                score += 1
        for w in negative_words:
            if w in text:
                score -= 1
        total_score += score

    avg = total_score / max(len(articles), 1)

    if avg > 0.5:
        label = "Bullish"
    elif avg < -0.5:
        label = "Bearish"
    else:
        label = "Neutraal"

    return {"score": float(avg), "label": label}


def filter_signals_by_news(signals, news_sentiment):
    """Ken elke trade een nieuws-gebonden slagingsscore toe en filter extreem
    tegengestelde trades weg.

    - Elke trade krijgt velden:
        - ``news_sentiment_score`` (numeriek)
        - ``news_sentiment_label`` (Bullish/Bearish/Neutraal)
        - ``news_success_score`` (0–100%, inschatting kans van slagen i.v.m. nieuws)
    - Bij sterk Bullish sentiment (score > 0.5): erg lage kans voor SELL (<30%)
        wordt weggefilterd.
    - Bij sterk Bearish sentiment (score < -0.5): erg lage kans voor BUY (<30%)
        wordt weggefilterd.
    """
    if not signals or not news_sentiment:
        return signals

    score = float(news_sentiment.get("score", 0.0))
    label = news_sentiment.get("label", "")

    def _estimate_success(direction, s):
        """Zet nieuwsscore om in simpele slagingskans per trade."""
        # Beperk de sterkte tot [-2, 2] om extreme waarden te dempen
        strength = min(abs(s), 2.0) / 2.0  # 0..1
        base = 0.5  # 50%

        if direction == "Buy":
            if s > 0:
                prob = base + 0.3 * strength  # max ~80%
            elif s < 0:
                prob = base - 0.3 * strength  # min ~20%
            else:
                prob = base
        elif direction == "Sell":
            if s < 0:
                prob = base + 0.3 * strength
            elif s > 0:
                prob = base - 0.3 * strength
            else:
                prob = base
        else:
            prob = base

        # Clamp tussen 0.1 en 0.9 zodat het nooit 0 of 100% is
        prob = max(0.1, min(0.9, prob))
        return prob * 100.0

    filtered = []
    for s in signals:
        sig = dict(s)  # kopie zodat we origineel niet muteren
        direction = str(sig.get("signal", "")).capitalize()

        sig["news_sentiment_score"] = score
        sig["news_sentiment_label"] = label
        sig["news_success_score"] = _estimate_success(direction, score)

        # Nieuws-filter logica alleen bij sterk sentiment én lage kans
        if score > 0.5 and direction == "Sell" and sig["news_success_score"] < 30:
            # Sterk positief nieuws → zeer lage kans voor short, overslaan
            continue
        if score < -0.5 and direction == "Buy" and sig["news_success_score"] < 30:
            # Sterk negatief nieuws → zeer lage kans voor long, overslaan
            continue

        filtered.append(sig)

    return filtered

# Fetch single pair exchange rate (no caching so price can update live)
def fetch_single_pair(from_currency="USD", to_currency="EUR"):
    url = f"https://api.fastforex.io/fetch-one?from={from_currency}&to={to_currency}&api_key={FASTFOREX_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if "result" in data:
            return data["result"].get(to_currency, None)
        else:
            st.error(f"API Error: {data.get('error', 'Unknown error')}")
            return None
    except Exception as e:
        st.warning(f"Error fetching exchange rate: {e}")
        return None


def fetch_fx_history_alpha_vantage(from_currency, to_currency, freq, periods, api_key):
    """Haal echte intraday-forexdata op via Alpha Vantage.

    Valt terug naar lege DataFrame als er iets misgaat; aanroeper
    gebruikt dan de simulatiefunctie.
    """
    if not api_key:
        return pd.DataFrame()

    interval = freq  # "1min", "5min", "15min", "30min" passen direct
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "FX_INTRADAY",
        "from_symbol": from_currency,
        "to_symbol": to_currency,
        "interval": interval,
        "outputsize": "compact",
        "apikey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        # Foutmelding van Alpha Vantage
        if "Error Message" in data or "Note" in data:
            msg = data.get("Error Message") or data.get("Note", "Unknown Alpha Vantage error")
            st.warning(f"Alpha Vantage FX error: {msg}")
            return pd.DataFrame()

        ts_key = f"Time Series FX ({interval})"
        ts = data.get(ts_key)
        if not ts:
            return pd.DataFrame()

        records = []
        for ts_str, values in ts.items():
            records.append({
                "Datetime": pd.to_datetime(ts_str),
                "Open": float(values.get("1. open", 0.0)),
                "High": float(values.get("2. high", 0.0)),
                "Low": float(values.get("3. low", 0.0)),
                "Close": float(values.get("4. close", 0.0)),
            })

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records).sort_values("Datetime")
        # Beperk tot het gevraagde aantal periodes
        df = df.tail(periods)

        # Alpha Vantage geeft geen volume mee -> synthetisch volume toevoegen
        volume_multiplier = {
            "1min": 1,
            "5min": 5,
            "15min": 15,
            "30min": 30,
        }
        multiplier = volume_multiplier.get(freq, 1)
        df["Volume"] = np.random.randint(100 * multiplier, 1000 * multiplier, len(df))

        return df
    except Exception as e:
        st.warning(f"Fout bij ophalen echte FX data: {e}")
        return pd.DataFrame()


# Generate historical data for forex
def generate_historical_data(rate, periods, freq, base_currency=None, target_currency=None, fx_api_key=None):
    """Generate historical data aangepast aan timeframe.

    - Als een Alpha Vantage key is opgegeven en we een forex-paar hebben,
      proberen we eerst echte candles op te halen.
    - Als dat niet lukt, vallen we terug op gesimuleerde data rond de live rate.
    """
    if rate is None:
        st.error("Rate is unavailable. Cannot generate historical data.")
        return pd.DataFrame()

    # Probeer echte data als dat kan
    if fx_api_key and base_currency and target_currency:
        real_df = fetch_fx_history_alpha_vantage(base_currency, target_currency, freq, periods, fx_api_key)
        if not real_df.empty:
            return real_df

    # Fallback: gesimuleerde data rond de huidige koers
    base_price = rate
    dates = pd.date_range(end=pd.Timestamp.now(), periods=periods, freq=freq)

    volatility_map = {
        "1min": 0.005,
        "5min": 0.008,
        "15min": 0.012,
        "30min": 0.015,
    }
    volatility = volatility_map.get(freq, 0.005)

    closes = np.random.normal(base_price, base_price * volatility, len(dates))
    opens = closes + np.random.normal(0, base_price * volatility * 0.6, len(dates))
    highs = closes + abs(np.random.normal(0, base_price * volatility * 0.8, len(dates)))
    lows = closes - abs(np.random.normal(0, base_price * volatility * 0.8, len(dates)))

    volume_multiplier = {
        "1min": 1,
        "5min": 5,
        "15min": 15,
        "30min": 30,
    }
    multiplier = volume_multiplier.get(freq, 1)
    volumes = np.random.randint(100 * multiplier, 1000 * multiplier, len(dates))

    return pd.DataFrame({
        "Datetime": dates,
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    })

# Generate order flow data (bid/ask volumes, delta)
def generate_order_flow_data(df):
    """
    Simulate order flow metrics:
    - Buy Volume: Aggressive buys (market orders hitting asks)
    - Sell Volume: Aggressive sells (market orders hitting bids)
    - Delta: Buy Volume - Sell Volume
    - Cumulative Delta: Running sum of delta
    """
    df = df.copy()
    
    # Simulate buy/sell split based on price movement
    price_change = df['Close'] - df['Open']
    bullish_bars = price_change > 0
    
    # Buy volume higher when price rises
    df['Buy_Volume'] = np.where(
        bullish_bars,
        df['Volume'] * np.random.uniform(0.55, 0.75, len(df)),
        df['Volume'] * np.random.uniform(0.25, 0.45, len(df))
    )
    
    df['Sell_Volume'] = df['Volume'] - df['Buy_Volume']
    df['Delta'] = df['Buy_Volume'] - df['Sell_Volume']
    df['Cumulative_Delta'] = df['Delta'].cumsum()
    
    # Volume-Weighted Average Price (VWAP)
    df['VWAP'] = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    
    return df

def apply_pip_limits(entry_price, stop_loss, take_profit, direction, pip_size, max_sl_pips=50, max_tp_pips=100):
    """Cap SL/TP distances to configured pip limits."""
    if stop_loss is None or take_profit is None or pip_size is None:
        return stop_loss, take_profit

    max_sl = max_sl_pips * pip_size
    max_tp = max_tp_pips * pip_size

    sl_dist = abs(stop_loss - entry_price)
    tp_dist = abs(take_profit - entry_price)

    if max_sl > 0 and sl_dist > max_sl:
        sl_dist = max_sl
        if direction == 'Buy':
            stop_loss = entry_price - sl_dist
        else:
            stop_loss = entry_price + sl_dist

    if max_tp > 0 and tp_dist > max_tp:
        tp_dist = max_tp
        if direction == 'Buy':
            take_profit = entry_price + tp_dist
        else:
            take_profit = entry_price - tp_dist

    return stop_loss, take_profit

# Identify Supply and Demand Zones
def identify_supply_demand_zones(df, lookback=50, threshold=0.002):
    """
    Identify supply (resistance) and demand (support) zones based on:
    - Price rejections (wicks)
    - Volume spikes
    - Consolidation areas
    """
    zones = []
    
    for i in range(lookback, len(df) - 10):
        # Check for strong rejection candles (large wicks)
        body = abs(df.iloc[i]['Close'] - df.iloc[i]['Open'])
        upper_wick = df.iloc[i]['High'] - max(df.iloc[i]['Close'], df.iloc[i]['Open'])
        lower_wick = min(df.iloc[i]['Close'], df.iloc[i]['Open']) - df.iloc[i]['Low']
        total_range = df.iloc[i]['High'] - df.iloc[i]['Low']
        
        if total_range == 0:
            continue
            
        # SUPPLY ZONE (Resistance) - Strong rejection from top
        if upper_wick > body * 2 and upper_wick / total_range > 0.5:
            # Check if volume is higher than average
            avg_volume = df.iloc[i-lookback:i]['Volume'].mean()
            if df.iloc[i]['Volume'] > avg_volume * 1.3:
                # Define zone boundaries
                zone_top = df.iloc[i]['High']
                zone_bottom = df.iloc[i]['High'] - (total_range * 0.3)
                
                # Check if this is a significant zone (price hasn't breached it recently)
                future_prices = df.iloc[i+1:i+11]['High']
                if len(future_prices) > 0 and future_prices.max() < zone_top * 1.001:
                    zones.append({
                        'type': 'Supply',
                        'top': zone_top,
                        'bottom': zone_bottom,
                        'start_idx': i,
                        'strength': 'High' if df.iloc[i]['Volume'] > avg_volume * 1.5 else 'Medium',
                        'touches': 1
                    })
        
        # DEMAND ZONE (Support) - Strong rejection from bottom
        if lower_wick > body * 2 and lower_wick / total_range > 0.5:
            avg_volume = df.iloc[i-lookback:i]['Volume'].mean()
            if df.iloc[i]['Volume'] > avg_volume * 1.3:
                zone_bottom = df.iloc[i]['Low']
                zone_top = df.iloc[i]['Low'] + (total_range * 0.3)
                
                future_prices = df.iloc[i+1:i+11]['Low']
                if len(future_prices) > 0 and future_prices.min() > zone_bottom * 0.999:
                    zones.append({
                        'type': 'Demand',
                        'top': zone_top,
                        'bottom': zone_bottom,
                        'start_idx': i,
                        'strength': 'High' if df.iloc[i]['Volume'] > avg_volume * 1.5 else 'Medium',
                        'touches': 1
                    })
    
    # Remove overlapping zones, keep the strongest
    filtered_zones = []
    for zone in zones:
        overlap = False
        for existing in filtered_zones:
            if zone['type'] == existing['type']:
                # Check for overlap
                if not (zone['top'] < existing['bottom'] or zone['bottom'] > existing['top']):
                    overlap = True
                    # Keep the one with higher strength
                    if zone['strength'] == 'High' and existing['strength'] == 'Medium':
                        filtered_zones.remove(existing)
                        overlap = False
                    break
        if not overlap:
            filtered_zones.append(zone)
    
    return filtered_zones

# Generate Supply/Demand Zone Signals
def generate_supply_demand_signals(df, zones, pip_size=0.0001):
    """
    Generate trading signals when price enters supply/demand zones
    Based on the strategy shown in the images:
    - SELL when price enters Supply zone from below
    - BUY when price enters Demand zone from above
    """
    signals = []
    
    for i in range(1, len(df)):
        current_price = df.iloc[i]['Close']
        previous_price = df.iloc[i-1]['Close']
        current_high = df.iloc[i]['High']
        current_low = df.iloc[i]['Low']
        timestamp = df.iloc[i]['Datetime']
        
        for zone in zones:
            zone_top = zone['top']
            zone_bottom = zone['bottom']
            zone_mid = (zone_top + zone_bottom) / 2
            
            # SELL SIGNAL - Price enters Supply Zone from below
            if zone['type'] == 'Supply':
                # Price was below zone, now touching/entering it
                if previous_price < zone_bottom and current_high >= zone_bottom:
                    # Entry at zone bottom (first touch)
                    entry_price = float(zone_bottom)
                    
                    # Stop Loss above the supply zone
                    stop_loss = float(zone_top * 1.0005)  # Small buffer above zone
                    risk = stop_loss - entry_price
                    
                    # Take Profit with 2:1 or 3:1 risk-reward (capped by pip limits)
                    take_profit = entry_price - (2.5 * risk)

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'Supply Zone Rejection',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '1m',
                        'zone_strength': zone['strength'],
                        'risk_reward': '2.5:1'
                    })
            
            # BUY SIGNAL - Price enters Demand Zone from above
            elif zone['type'] == 'Demand':
                # Price was above zone, now touching/entering it
                if previous_price > zone_top and current_low <= zone_top:
                    # Entry at zone top (first touch)
                    entry_price = float(zone_top)
                    
                    # Stop Loss below the demand zone
                    stop_loss = float(zone_bottom * 0.9995)  # Small buffer below zone
                    risk = entry_price - stop_loss
                    
                    # Take Profit with 2:1 or 3:1 risk-reward (capped by pip limits)
                    take_profit = entry_price + (2.5 * risk)

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'Demand Zone Bounce',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '1m',
                        'zone_strength': zone['strength'],
                        'risk_reward': '2.5:1'
                    })
    
    return signals


def generate_m15_market_structure_signals(df_15m, zones, pip_size=0.0001):
    """Generate 15m market structure signals (breakouts & reversals) around supply/demand zones with volume filter."""
    signals = []

    if df_15m.empty or not zones:
        return signals

    for i in range(1, len(df_15m)):
        row = df_15m.iloc[i]
        prev = df_15m.iloc[i - 1]
        timestamp = row['Datetime']

        # Local volume benchmark (kept as context info, but no longer required)
        vol_start = max(0, i - 10)
        avg_vol = df_15m['Volume'].iloc[vol_start:i].mean() if i > 0 else df_15m['Volume'].iloc[:1].mean()
        high_volume = row['Volume'] > avg_vol * 1.2 if avg_vol > 0 else False

        for zone in zones:
            zone_top = zone['top']
            zone_bottom = zone['bottom']

            # --- SUPPLY ZONE LOGIC ---
            if zone['type'] == 'Supply':
                # Breakout above supply (bullish continuation)
                if prev['Close'] <= zone_top and row['Close'] > zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_top * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M15 Supply Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '15m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                # Reversal at/above supply (fakeout & rejection)
                if row['High'] > zone_top and row['Close'] < zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(max(row['High'], zone_top) * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M15 Supply Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '15m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

            # --- DEMAND ZONE LOGIC ---
            elif zone['type'] == 'Demand':
                # Breakout below demand (bearish continuation)
                if prev['Close'] >= zone_bottom and row['Close'] < zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_bottom * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M15 Demand Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '15m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                # Reversal at/below demand (fakeout & bounce)
                if row['Low'] < zone_bottom and row['Close'] > zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(min(row['Low'], zone_bottom) * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M15 Demand Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '15m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

    return signals


def generate_m5_market_structure_signals(df_5m, zones, pip_size=0.0001):
    """Generate 5m market structure signals around higher-timeframe supply/demand zones."""
    signals = []

    if df_5m.empty or not zones:
        return signals

    for i in range(1, len(df_5m)):
        row = df_5m.iloc[i]
        prev = df_5m.iloc[i - 1]
        timestamp = row['Datetime']

        vol_start = max(0, i - 10)
        avg_vol = df_5m['Volume'].iloc[vol_start:i].mean() if i > 0 else df_5m['Volume'].iloc[:1].mean()
        high_volume = row['Volume'] > avg_vol * 1.2 if avg_vol > 0 else False

        for zone in zones:
            zone_top = zone['top']
            zone_bottom = zone['bottom']

            if zone['type'] == 'Supply':
                # Breakout above supply (bullish continuation)
                if prev['Close'] <= zone_top and row['Close'] > zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_top * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M5 Supply Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '5m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                # Reversal at/above supply (fakeout & rejection)
                if row['High'] > zone_top and row['Close'] < zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(max(row['High'], zone_top) * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M5 Supply Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '5m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

            elif zone['type'] == 'Demand':
                # Breakout below demand (bearish continuation)
                if prev['Close'] >= zone_bottom and row['Close'] < zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_bottom * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M5 Demand Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '5m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                # Reversal at/below demand (fakeout & bounce)
                if row['Low'] < zone_bottom and row['Close'] > zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(min(row['Low'], zone_bottom) * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M5 Demand Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '5m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

    return signals


def generate_m30_market_structure_signals(df_30m, zones, pip_size=0.0001):
    """Generate 30m market structure signals (breakouts & reversals) around supply/demand zones with volume filter."""
    signals = []

    if df_30m.empty or not zones:
        return signals

    for i in range(1, len(df_30m)):
        row = df_30m.iloc[i]
        prev = df_30m.iloc[i - 1]
        timestamp = row['Datetime']

        vol_start = max(0, i - 10)
        avg_vol = df_30m['Volume'].iloc[vol_start:i].mean() if i > 0 else df_30m['Volume'].iloc[:1].mean()
        high_volume = row['Volume'] > avg_vol * 1.2 if avg_vol > 0 else False

        for zone in zones:
            zone_top = zone['top']
            zone_bottom = zone['bottom']

            if zone['type'] == 'Supply':
                if prev['Close'] <= zone_top and row['Close'] > zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_top * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M30 Supply Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '30m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                if row['High'] > zone_top and row['Close'] < zone_top:
                    entry_price = float(row['Close'])
                    stop_loss = float(max(row['High'], zone_top) * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M30 Supply Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '30m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

            elif zone['type'] == 'Demand':
                if prev['Close'] >= zone_bottom and row['Close'] < zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(zone_bottom * 1.0005)
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'M30 Demand Breakout',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '30m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

                if row['Low'] < zone_bottom and row['Close'] > zone_bottom:
                    entry_price = float(row['Close'])
                    stop_loss = float(min(row['Low'], zone_bottom) * 0.9995)
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        risk = abs(entry_price) * 0.001
                    take_profit = entry_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        entry_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'M30 Demand Reversal',
                        'price': float(round(entry_price, 5)),
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                        'timeframe': '30m',
                        'zone_strength': zone.get('strength', ''),
                        'volume': float(row['Volume']),
                    })

    return signals

# Generate footprint chart data (price levels with buy/sell volume)
def generate_footprint_data(df, bar_index):
    """
    Create footprint data for a specific candlestick bar.
    Shows buy/sell volume at each price level within that bar.
    """
    if bar_index >= len(df):
        return pd.DataFrame()
    
    row = df.iloc[bar_index]
    low_price = row['Low']
    high_price = row['High']
    close_price = row['Close']
    total_volume = row['Volume']
    buy_vol = row['Buy_Volume']
    sell_vol = row['Sell_Volume']
    
    # Create price levels (ticks) within the bar
    num_levels = max(5, int((high_price - low_price) / (low_price * 0.0001)))
    num_levels = min(num_levels, 20)  # Cap at 20 levels
    
    price_levels = np.linspace(low_price, high_price, num_levels)
    
    # Distribute volume across price levels with concentration near close
    weights = np.exp(-((price_levels - close_price) ** 2) / (2 * ((high_price - low_price) / 4) ** 2))
    weights = weights / weights.sum()
    
    # Allocate buy/sell volume
    buy_volumes = buy_vol * weights
    sell_volumes = sell_vol * weights
    
    footprint_df = pd.DataFrame({
        'Price': price_levels,
        'Buy_Volume': buy_volumes,
        'Sell_Volume': sell_volumes,
        'Delta': buy_volumes - sell_volumes,
        'Total_Volume': buy_volumes + sell_volumes
    })
    
    return footprint_df

# Detect order flow signals
def detect_order_flow_signals(df, timeframe_label="1m", pip_size=0.0001):
    """
    Detect trading signals based on order flow:
    1. Delta Divergence: Price makes new high/low but delta doesn't confirm
    2. Exhaustion: Large volume spike with opposite delta
    3. Absorption: High volume but small price movement (supply/demand absorption)
    4. Cumulative Delta Trend: Strong positive/negative cumulative delta
    """
    signals = []
    
    for i in range(20, len(df)):  # Need some history
        current_price = df.iloc[i]['Close']
        current_delta = df.iloc[i]['Delta']
        current_cum_delta = df.iloc[i]['Cumulative_Delta']
        current_volume = df.iloc[i]['Volume']
        timestamp = df.iloc[i]['Datetime']
        
        # Look back window
        lookback = df.iloc[i-10:i]
        avg_volume = lookback['Volume'].mean()
        
        # Prepare recent swing levels for TP/SL logic
        swing_start = max(0, i - 5)
        recent_low = float(df['Low'].iloc[swing_start:i+1].min())
        recent_high = float(df['High'].iloc[swing_start:i+1].max())

        # 1. DELTA DIVERGENCE - Bullish
        if i >= 20:
            recent_price_low = df.iloc[i-10:i]['Low'].min()
            recent_delta_at_low_idx = df.iloc[i-10:i]['Low'].idxmin()
            
            if df.iloc[i]['Low'] < recent_price_low:
                if df.iloc[i]['Delta'] > df.loc[recent_delta_at_low_idx, 'Delta']:
                    stop_loss = min(recent_low, current_price)
                    risk = current_price - stop_loss
                    if risk <= 0:
                        risk = abs(current_price) * 0.001
                    take_profit = current_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        current_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'Delta Divergence (Bullish)',
                        'price': float(current_price),
                        'delta': float(current_delta),
                        'cum_delta': float(current_cum_delta),
                        'strength': 'High',
                        'timeframe': timeframe_label,
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                    })
        
        # 2. DELTA DIVERGENCE - Bearish
        if i >= 20:
            recent_price_high = df.iloc[i-10:i]['High'].max()
            recent_delta_at_high_idx = df.iloc[i-10:i]['High'].idxmax()
            
            if df.iloc[i]['High'] > recent_price_high:
                if df.iloc[i]['Delta'] < df.loc[recent_delta_at_high_idx, 'Delta']:
                    stop_loss = max(recent_high, current_price)
                    risk = stop_loss - current_price
                    if risk <= 0:
                        risk = abs(current_price) * 0.001
                    take_profit = current_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        current_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'Delta Divergence (Bearish)',
                        'price': float(current_price),
                        'delta': float(current_delta),
                        'cum_delta': float(current_cum_delta),
                        'strength': 'High',
                        'timeframe': timeframe_label,
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                    })
        
        # 3. VOLUME EXHAUSTION - Bullish (selling exhaustion)
        if current_volume > avg_volume * 1.5 and current_delta < -avg_volume * 0.3:
            price_change_pct = (df.iloc[i]['Close'] - df.iloc[i]['Open']) / df.iloc[i]['Open']
            if price_change_pct > -0.001:
                stop_loss = min(recent_low, current_price)
                risk = current_price - stop_loss
                if risk <= 0:
                    risk = abs(current_price) * 0.001
                take_profit = current_price + 2 * risk

                stop_loss, take_profit = apply_pip_limits(
                    current_price, stop_loss, take_profit, 'Buy', pip_size
                )

                signals.append({
                    'timestamp': timestamp,
                    'signal': 'Buy',
                    'type': 'Selling Exhaustion',
                    'price': float(current_price),
                    'delta': float(current_delta),
                    'cum_delta': float(current_cum_delta),
                    'strength': 'Medium',
                    'timeframe': timeframe_label,
                    'stop_loss': float(round(stop_loss, 5)),
                    'take_profit': float(round(take_profit, 5)),
                })
        
        # 4. VOLUME EXHAUSTION - Bearish (buying exhaustion)
        if current_volume > avg_volume * 1.5 and current_delta > avg_volume * 0.3:
            price_change_pct = (df.iloc[i]['Close'] - df.iloc[i]['Open']) / df.iloc[i]['Open']
            if price_change_pct < 0.001:
                stop_loss = max(recent_high, current_price)
                risk = stop_loss - current_price
                if risk <= 0:
                    risk = abs(current_price) * 0.001
                take_profit = current_price - 2 * risk

                stop_loss, take_profit = apply_pip_limits(
                    current_price, stop_loss, take_profit, 'Sell', pip_size
                )

                signals.append({
                    'timestamp': timestamp,
                    'signal': 'Sell',
                    'type': 'Buying Exhaustion',
                    'price': float(current_price),
                    'delta': float(current_delta),
                    'cum_delta': float(current_cum_delta),
                    'strength': 'Medium',
                    'timeframe': timeframe_label,
                    'stop_loss': float(round(stop_loss, 5)),
                    'take_profit': float(round(take_profit, 5)),
                })
        
        # 5. STRONG CUMULATIVE DELTA TREND
        if i >= 10:
            delta_slope = (df.iloc[i]['Cumulative_Delta'] - df.iloc[i-5]['Cumulative_Delta']) / 5
            price_slope = (df.iloc[i]['Close'] - df.iloc[i-5]['Close']) / 5
            
            if delta_slope > 0 and price_slope > 0 and current_delta > 0:
                if i % 15 == 0:
                    stop_loss = min(recent_low, current_price)
                    risk = current_price - stop_loss
                    if risk <= 0:
                        risk = abs(current_price) * 0.001
                    take_profit = current_price + 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        current_price, stop_loss, take_profit, 'Buy', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Buy',
                        'type': 'Strong Buying Flow',
                        'price': float(current_price),
                        'delta': float(current_delta),
                        'cum_delta': float(current_cum_delta),
                        'strength': 'Medium',
                        'timeframe': timeframe_label,
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                    })
            
            elif delta_slope < 0 and price_slope < 0 and current_delta < 0:
                if i % 15 == 0:
                    stop_loss = max(recent_high, current_price)
                    risk = stop_loss - current_price
                    if risk <= 0:
                        risk = abs(current_price) * 0.001
                    take_profit = current_price - 2 * risk

                    stop_loss, take_profit = apply_pip_limits(
                        current_price, stop_loss, take_profit, 'Sell', pip_size
                    )

                    signals.append({
                        'timestamp': timestamp,
                        'signal': 'Sell',
                        'type': 'Strong Selling Flow',
                        'price': float(current_price),
                        'delta': float(current_delta),
                        'cum_delta': float(current_cum_delta),
                        'strength': 'Medium',
                        'timeframe': timeframe_label,
                        'stop_loss': float(round(stop_loss, 5)),
                        'take_profit': float(round(take_profit, 5)),
                    })
    
    return signals

# Add lower highs and lower lows detection and technical indicators
def add_technical_indicators(df):
    df['SMA_50'] = df['Close'].rolling(window=50, min_periods=1).mean()
    df['SMA_200'] = df['Close'].rolling(window=200, min_periods=1).mean()
    df['Lower_High'] = (df['High'].diff() < 0) & (df['High'].shift(-1) < df['High'])
    df['Lower_Low'] = (df['Low'].diff() < 0) & (df['Low'].shift(-1) < df['Low'])
    df['Higher_High'] = (df['High'].diff() > 0) & (df['High'].shift(-1) > df['High'])
    df['Higher_Low'] = (df['Low'].diff() > 0) & (df['Low'].shift(-1) > df['Low'])
    return df

# Generate trading signals based on lower highs/lows and SMAs
def generate_sell_signals(df, pip_size=0.0001):
    signals = []
    for i in range(1, len(df)):
        entry_price = float(df.iloc[i]['Close'])

        # SELL setup: lower highs/lows in a downtrend
        if df['Lower_High'][i] and df['Lower_Low'][i]:
            if df['SMA_50'][i] < df['SMA_200'][i] and df['Close'][i] < df['SMA_50'][i]:
                start_idx = max(0, i - 5)
                recent_high = float(df['High'].iloc[start_idx:i+1].max())
                stop_loss = max(recent_high, entry_price)
                risk = stop_loss - entry_price
                if risk <= 0:
                    risk = entry_price * 0.001
                take_profit = entry_price - 2 * risk

                stop_loss, take_profit = apply_pip_limits(
                    entry_price, stop_loss, take_profit, 'Sell', pip_size
                )
                signals.append({
                    'timestamp': df.iloc[i]['Datetime'],
                    'signal': 'Sell',
                    'type': 'Technical Pattern',
                    'price': entry_price,
                    'timeframe': '1m',
                    'stop_loss': float(round(stop_loss, 5)),
                    'take_profit': float(round(take_profit, 5)),
                })

        # BUY setup: higher highs/lows in an uptrend
        if df['Higher_High'][i] and df['Higher_Low'][i]:
            if df['SMA_50'][i] > df['SMA_200'][i] and df['Close'][i] > df['SMA_50'][i]:
                start_idx = max(0, i - 5)
                recent_low = float(df['Low'].iloc[start_idx:i+1].min())
                stop_loss = min(recent_low, entry_price)
                risk = entry_price - stop_loss
                if risk <= 0:
                    risk = entry_price * 0.001
                take_profit = entry_price + 2 * risk

                stop_loss, take_profit = apply_pip_limits(
                    entry_price, stop_loss, take_profit, 'Buy', pip_size
                )
                signals.append({
                    'timestamp': df.iloc[i]['Datetime'],
                    'signal': 'Buy',
                    'type': 'Technical Pattern',
                    'price': entry_price,
                    'timeframe': '1m',
                    'stop_loss': float(round(stop_loss, 5)),
                    'take_profit': float(round(take_profit, 5)),
                })
    return signals

# Plot footprint chart for a specific bar
def plot_footprint_chart(footprint_df, bar_datetime):
    """Create a footprint chart visualization"""
    fig = go.Figure()
    
    # Add buy volume bars (positive side)
    fig.add_trace(go.Bar(
        y=footprint_df['Price'],
        x=footprint_df['Buy_Volume'],
        orientation='h',
        name='Buy Volume',
        marker=dict(color='green'),
        text=footprint_df['Buy_Volume'].round(0),
        textposition='auto'
    ))
    
    # Add sell volume bars (negative side)
    fig.add_trace(go.Bar(
        y=footprint_df['Price'],
        x=-footprint_df['Sell_Volume'],
        orientation='h',
        name='Sell Volume',
        marker=dict(color='red'),
        text=footprint_df['Sell_Volume'].round(0),
        textposition='auto'
    ))
    
    fig.update_layout(
        title=f"Footprint Chart - {bar_datetime}",
        xaxis_title="Volume (Buy→ / ←Sell)",
        yaxis_title="Price Level",
        barmode='overlay',
        template="plotly_dark",
        height=500
    )
    
    return fig

# Streamlit app main function
def main():
    st.set_page_config(page_title="Supply/Demand Trading Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Advanced Supply/Demand Zone Trading Dashboard")
    
    st.markdown("""
    **Features:**
    - 📈 Real-time Forex Data
    - 🎯 Supply & Demand Zone Detection
    - 📊 Order Flow Analysis (Delta, Cumulative Delta, VWAP)
    - 👣 Footprint Charts
    - 💡 Multiple Trading Signal Types
    """)

    # Sidebar settings
    st.sidebar.title("⚙️ Settings")

    # NIEUW: Primary Timeframe Selector
    st.sidebar.subheader("⏰ Primary Chart Timeframe")
    primary_timeframe_choice = st.sidebar.selectbox(
        "Select Primary Chart",
        ["M1 (1 minute)", "M5 (5 minutes)", "M15 (15 minutes)", "M30 (30 minutes)"],
        index=0,
        help="This timeframe will be shown in the main chart"
    )

    # Map naar config
    timeframe_config = {
        "M1 (1 minute)": {"freq": "1min", "periods": 1500, "label": "1m", "lookback": 50},
        "M5 (5 minutes)": {"freq": "5min", "periods": 500, "label": "5m", "lookback": 40},
        "M15 (15 minutes)": {"freq": "15min", "periods": 300, "label": "15m", "lookback": 30},
        "M30 (30 minutes)": {"freq": "30min", "periods": 200, "label": "30m", "lookback": 20},
    }

    tf_config = timeframe_config[primary_timeframe_choice]
    primary_freq = tf_config["freq"]
    primary_periods = tf_config["periods"]
    primary_label = tf_config["label"]
    zone_lookback = tf_config["lookback"]

    instrument_type = st.sidebar.selectbox(
        "Instrument Type",
        ["Forex", "Indices (US30, NAS100)"],
        index=0,
    )

    # Forex pair selection
    base_currency = None
    target_currency = None
    index_choice = None

    if instrument_type == "Forex":
        base_currency = st.sidebar.selectbox("Base Currency", ["USD", "EUR", "GBP"], index=0)
        target_currency = st.sidebar.selectbox("Target Currency", ["EUR", "USD", "GBP"], index=1)
    else:
        # Synthetic indices (no external API dependency)
        index_choice = st.sidebar.selectbox(
            "Index",
            ["US30 (Dow Jones)", "NAS100 (Nasdaq 100)"],
            index=0,
        )

    refresh_seconds = st.sidebar.slider("Refresh interval (seconds)", 5, 60, 15)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Analysis Options")
    show_supply_demand = st.sidebar.checkbox("Show Supply/Demand Zones", value=True)
    show_orderflow = st.sidebar.checkbox("Show Order Flow Signals", value=True)
    show_technical = st.sidebar.checkbox("Show Technical Signals", value=False)
    show_footprint = st.sidebar.checkbox("Show Footprint Chart", value=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("📰 Nieuws & Sentiment")
    show_news = st.sidebar.checkbox("Analyseer marktnieuws", value=True)
    default_news_key = os.getenv("NEWSDATA_API_KEY", os.getenv("NEWS_API_KEY", ""))
    news_api_key = st.sidebar.text_input(
        "NewsData.io API key (optioneel)", value=default_news_key, type="password"
    )
    news_language = st.sidebar.selectbox(
        "Nieuwstaal",
        ["en", "de", "fr", "es", "nl"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("📈 Echte Forex-data (Alpha Vantage)")
    default_fx_key = os.getenv("ALPHAVANTAGE_API_KEY", "")
    fx_api_key_input = st.sidebar.text_input(
        "Alpha Vantage API key (optioneel, voor echte GBP/USD candles)",
        value="" if default_fx_key else "",
        type="password",
    )

    # Gebruik de environment key als fallback wanneer veld leeg is
    fx_api_key = fx_api_key_input or default_fx_key

    if default_fx_key:
        st.sidebar.caption("Alpha Vantage key geladen uit omgeving (wordt gebruikt, ook als dit veld leeg lijkt).")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🧪 Test Zone Settings")
    enable_test_zone = st.sidebar.checkbox("Enable Test Zone (Fake Trading)", value=True)
    starting_balance = st.sidebar.number_input(
        "Starting Balance (fake money)",
        min_value=1000.0,
        max_value=1000000.0,
        value=10000.0,
        step=1000.0,
    )
    pip_value_money = st.sidebar.number_input(
        "Value per Pip (fake money)",
        min_value=0.1,
        max_value=100.0,
        value=1.0,
        step=0.1,
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔔 Alert Settings")
    default_tg_token = os.getenv("TELEGRAM_TOKEN", TELEGRAM_TOKEN_DEFAULT)
    default_tg_chat = os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID_DEFAULT)

    tg_token_input = st.sidebar.text_input(
        "Telegram bot token (optioneel)",
        value=default_tg_token,
        type="password",
    )
    tg_chat_input = st.sidebar.text_input(
        "Telegram chat ID (optioneel)",
        value=default_tg_chat,
    )

    # Sla UI-waarden op in session_state zodat send_telegram_alert ze kan gebruiken
    st.session_state["TELEGRAM_TOKEN_UI"] = tg_token_input
    st.session_state["TELEGRAM_CHAT_ID_UI"] = tg_chat_input

    enable_alerts = st.sidebar.checkbox("Enable Telegram alerts for new signals", value=False)

    if st.sidebar.button("📨 Stuur testbericht naar Telegram"):
        send_telegram_alert("Test alert vanuit je Streamlit dashboard ✅")
        st.sidebar.success("Testbericht verstuurd (als token/chat ID kloppen).")

    # Single-pass render
    placeholder = st.empty()

    with placeholder.container():
        # Determine instrument label and current price
        if instrument_type == "Forex":
            instrument_label = f"{base_currency}/{target_currency}"
            pip_size = 0.0001
            rate = fetch_single_pair(base_currency, target_currency)
        else:
            if index_choice.startswith("US30"):
                instrument_label = "US30"
                pip_size = 1.0
                rate = 38000.0  # synthetic current price for Dow Jones
            else:
                instrument_label = "NAS100"
                pip_size = 1.0
                rate = 17000.0  # synthetic current price for Nasdaq 100

        # Nieuws & sentiment ophalen voor dit instrument (als geactiveerd)
        news_articles = []
        news_sentiment = None
        if show_news and news_api_key:
            query = build_news_query(
                instrument_type,
                base_currency=base_currency,
                target_currency=target_currency,
                index_choice=index_choice,
            )
            news_articles = fetch_news_articles(query, news_api_key, language=news_language)
            news_sentiment = analyze_news_sentiment(news_articles)

        col1, col2, col3 = st.columns(3)

        if rate:
            col1.metric(label=f"💱 {instrument_label}", value=f"{rate:.5f}")
        else:
            st.error("Failed to fetch price.")
            return

        # Generate PRIMARY timeframe historical data
        df_primary = generate_historical_data(
            rate,
            primary_periods,
            primary_freq,
            base_currency=base_currency,
            target_currency=target_currency,
            fx_api_key=fx_api_key,
        )
        if df_primary.empty:
            st.warning("Unable to generate historical data.")
            return

        # Add technical indicators
        df_primary = add_technical_indicators(df_primary)
        df_primary = generate_order_flow_data(df_primary)

        # Build HIGHER timeframes
        df_idx = df_primary.set_index('Datetime')

        def _resample_ohlcv(frame, rule):
            r = frame.resample(rule).agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum',
            }).dropna()
            r = r.reset_index()
            r = add_technical_indicators(r)
            r = generate_order_flow_data(r)
            return r

        # Dynamically create higher timeframes
        higher_tfs = []
        df_5m = None
        df_15m = None
        df_30m = None

        if primary_label == "1m":
            df_5m = _resample_ohlcv(df_idx, '5min')
            df_15m = _resample_ohlcv(df_idx, '15min')
            df_30m = _resample_ohlcv(df_idx, '30min')
            higher_tfs = [("5m", df_5m), ("15m", df_15m), ("30m", df_30m)]
            df_for_zones = df_15m  # Zones from 15m
        elif primary_label == "5m":
            df_15m = _resample_ohlcv(df_idx, '15min')
            df_30m = _resample_ohlcv(df_idx, '30min')
            higher_tfs = [("15m", df_15m), ("30m", df_30m)]
            df_for_zones = df_15m
        elif primary_label == "15m":
            df_30m = _resample_ohlcv(df_idx, '30min')
            higher_tfs = [("30m", df_30m)]
            df_for_zones = df_primary
        else:  # 30m
            df_for_zones = df_primary

        # Identify zones
        supply_demand_zones = []
        if show_supply_demand:
            supply_demand_zones = identify_supply_demand_zones(df_for_zones, lookback=zone_lookback)
        
        # Display current metrics (primary timeframe)
        current_delta = df_primary.iloc[-1]['Delta']
        current_cum_delta = df_primary.iloc[-1]['Cumulative_Delta']
        
        col2.metric(
            label="📊 Current Delta", 
            value=f"{current_delta:.0f}",
            delta=f"{'Buying' if current_delta > 0 else 'Selling'} Pressure"
        )
        col3.metric(
            label="📈 Cumulative Delta", 
            value=f"{current_cum_delta:.0f}",
            delta=f"{'Bullish' if current_cum_delta > 0 else 'Bearish'} Trend"
        )

        # Nieuwssentiment tonen (als beschikbaar)
        if show_news:
            if news_api_key and news_sentiment is not None:
                st.metric(
                    label="📰 Nieuwssentiment",
                    value=news_sentiment.get("label", "Neutraal"),
                    delta=f"Score: {news_sentiment.get('score', 0.0):.2f}",
                )
            elif not news_api_key:
                st.info("Voer je NewsData.io key in de sidebar in om nieuws te analyseren.")
        
        # Generate signals based on primary + higher timeframes
        all_signals = []
        m5_ms_signals = []
        m15_ms_signals = []
        m30_ms_signals = []

        # Primary timeframe signals
        if show_supply_demand and supply_demand_zones:
            sd_signals = generate_supply_demand_signals(
                df_primary, supply_demand_zones, pip_size=pip_size
            )
            for sig in sd_signals:
                sig['timeframe'] = primary_label
            all_signals.extend(sd_signals)

        if show_orderflow:
            orderflow_primary = detect_order_flow_signals(
                df_primary, timeframe_label=primary_label, pip_size=pip_size
            )
            all_signals.extend(orderflow_primary)

        # Higher timeframe signals
        for tf_label, tf_df in higher_tfs:
            if show_orderflow:
                orderflow_htf = detect_order_flow_signals(tf_df, timeframe_label=tf_label, pip_size=pip_size)
                all_signals.extend(orderflow_htf)

            if show_supply_demand and supply_demand_zones:
                if tf_label == "5m" and df_5m is not None:
                    ms_htf = generate_m5_market_structure_signals(
                        tf_df, supply_demand_zones, pip_size=pip_size
                    )
                elif tf_label == "15m" and df_15m is not None:
                    ms_htf = generate_m15_market_structure_signals(
                        tf_df, supply_demand_zones, pip_size=pip_size
                    )
                elif tf_label == "30m" and df_30m is not None:
                    ms_htf = generate_m30_market_structure_signals(
                        tf_df, supply_demand_zones, pip_size=pip_size
                    )
                else:
                    ms_htf = []

                if tf_label == "5m":
                    m5_ms_signals = ms_htf
                elif tf_label == "15m":
                    m15_ms_signals = ms_htf
                elif tf_label == "30m":
                    m30_ms_signals = ms_htf

                all_signals.extend(ms_htf)

        if show_technical:
            technical_signals = generate_sell_signals(df_primary, pip_size=pip_size)
            for sig in technical_signals:
                sig['timeframe'] = primary_label
            all_signals.extend(technical_signals)

        # Filter alle signalen op basis van nieuws-sentiment (optioneel)
        if show_news and news_sentiment is not None and all_signals:
            before_n = len(all_signals)
            all_signals = filter_signals_by_news(all_signals, news_sentiment)
            after_n = len(all_signals)
            removed = before_n - after_n
            if removed > 0:
                st.info(
                    f"{removed} signalen gefilterd door nieuwssentiment: {news_sentiment.get('label', '')}"
                )

        # Alerts voor nieuwe signalen (per run, per instrument)
        if enable_alerts and all_signals:
            signal_df_alert = pd.DataFrame(all_signals).copy()
            if 'timestamp' in signal_df_alert.columns:
                signal_df_alert['timestamp'] = pd.to_datetime(signal_df_alert['timestamp'])

            # Unieke key per instrument, zodat EURUSD en NAS100 apart tellen
            alert_key = f"last_alert_ts::{instrument_label}"

            if alert_key not in st.session_state:
                # Eerste keer alerts inschakelen: beschouw alle bestaande signalen als "oud"
                # zodat je alleen echt nieuwe signalen vanaf nu via Telegram krijgt.
                if 'timestamp' in signal_df_alert.columns and not signal_df_alert['timestamp'].empty:
                    st.session_state[alert_key] = signal_df_alert['timestamp'].max()
                else:
                    st.session_state[alert_key] = pd.Timestamp.utcnow()
                st.info("Telegram-alerts geactiveerd: je ontvangt alleen nieuwe signalen vanaf nu.")
            else:
                last_ts = st.session_state[alert_key]

                new_mask = signal_df_alert['timestamp'] > last_ts
                new_signals = signal_df_alert[new_mask]

                if not new_signals.empty:
                    # Stuur per signaal een korte alert
                    for _, sig in new_signals.sort_values('timestamp').iterrows():
                        tf = sig.get('timeframe', primary_label)
                        direction = sig.get('signal', '')
                        sig_type = sig.get('type', '')
                        price = sig.get('price', np.nan)
                        ts_str = sig.get('timestamp')

                        msg = f"{instrument_label} | {tf} {direction} @ {price:.5f} | {sig_type} | {ts_str}"
                        send_telegram_alert(msg)

                    # Toon ook een korte samenvatting in de UI
                    st.success(f"🔔 {len(new_signals)} nieuwe signalen verstuurd als alert.")

                    st.session_state[alert_key] = new_signals['timestamp'].max()

        # Nieuwssectie onder de signalen
        if show_news:
            st.subheader("📰 Laatste markt-nieuws voor dit instrument")
            if news_api_key and news_articles:
                for art in news_articles:
                    title = art.get("title", "(geen titel)")
                    desc = art.get("description") or ""
                    src = art.get("source") or ""
                    url = art.get("url") or ""
                    when = art.get("publishedAt") or ""

                    st.markdown(
                        f"**{title}**  \n"
                        f"{desc}  \n"
                        f"Bron: {src} | {when}  \n"
                        f"[Open artikel]({url})"
                    )
            elif news_api_key and not news_articles:
                st.info("Geen relevante nieuwsartikelen gevonden voor dit instrument.")
            elif not news_api_key:
                st.info("Geen NewsData.io key opgegeven; nieuws wordt niet opgehaald.")
        
        # Display Supply/Demand Zones Summary
        if show_supply_demand and supply_demand_zones:
            st.subheader("🎯 Supply & Demand Zones")
            zone_col1, zone_col2 = st.columns(2)
            
            supply_zones = [z for z in supply_demand_zones if z['type'] == 'Supply']
            demand_zones = [z for z in supply_demand_zones if z['type'] == 'Demand']
            
            with zone_col1:
                st.markdown("### 🔴 SUPPLY ZONES (Resistance)")
                if supply_zones:
                    for idx, zone in enumerate(supply_zones[:3]):  # Show top 3
                        st.info(f"**Zone {idx+1}**: {zone['bottom']:.5f} - {zone['top']:.5f} | Strength: {zone['strength']}")
                else:
                    st.write("No supply zones detected")
            
            with zone_col2:
                st.markdown("### 🟢 DEMAND ZONES (Support)")
                if demand_zones:
                    for idx, zone in enumerate(demand_zones[:3]):  # Show top 3
                        st.success(f"**Zone {idx+1}**: {zone['bottom']:.5f} - {zone['top']:.5f} | Strength: {zone['strength']}")
                else:
                    st.write("No demand zones detected")
        
        # Display signals
        st.subheader("🎯 Trading Signals")
        if all_signals:
            signal_df = pd.DataFrame(all_signals)
            
            if 'timeframe' not in signal_df.columns:
                signal_df['timeframe'] = '1m'

            preferred_order = ['1m', '5m', '15m', '30m']
            # Always show 1m, 5m, 15m & 30m tabs (even if currently no signals),
            # zodat alle timeframes altijd een eigen tab hebben.
            unique_tfs = set(signal_df['timeframe'].dropna().unique()) | set(preferred_order)
            unique_tfs_sorted = sorted(
                unique_tfs,
                key=lambda x: preferred_order.index(x) if x in preferred_order else len(preferred_order)
            )

            tabs = st.tabs([f"{tf} Signals" for tf in unique_tfs_sorted])

            for tf, tab in zip(unique_tfs_sorted, tabs):
                with tab:
                    tf_df = signal_df[signal_df['timeframe'] == tf]

                    col1, col2 = st.columns(2)

                    buy_signals = tf_df[tf_df['signal'] == 'Buy']
                    sell_signals = tf_df[tf_df['signal'] == 'Sell']

                    with col1:
                        st.markdown("### 🟢 BUY SIGNALS")
                        if not buy_signals.empty:
                            st.dataframe(buy_signals, use_container_width=True)
                        else:
                            st.info("No buy signals")

                    with col2:
                        st.markdown("### 🔴 SELL SIGNALS")
                        if not sell_signals.empty:
                            st.dataframe(sell_signals, use_container_width=True)
                        else:
                            st.info("No sell signals")
        else:
            st.info("No signals generated based on current data.")

        # Dedicated sections for higher-timeframe market structure / supply-demand signals
        any_ms = False
        if m5_ms_signals:
            any_ms = True
            st.subheader("📐 M5 Market Structure / Supply-Demand Signals")
            ms5_df = pd.DataFrame(m5_ms_signals)
            st.dataframe(ms5_df, use_container_width=True)

        if m15_ms_signals:
            any_ms = True
            st.subheader("📐 M15 Market Structure / Supply-Demand Signals")
            ms_df = pd.DataFrame(m15_ms_signals)
            st.dataframe(ms_df, use_container_width=True)

        if m30_ms_signals:
            any_ms = True
            st.subheader("📐 M30 Market Structure / Supply-Demand Signals")
            ms30_df = pd.DataFrame(m30_ms_signals)
            st.dataframe(ms30_df, use_container_width=True)

        if not any_ms and show_supply_demand and supply_demand_zones:
            st.info("No M5/M15/M30 market-structure signals for the current data.")

        # Test Zone - Fake money backtest on generated signals
        if enable_test_zone and all_signals:
            st.subheader("🧪 Test Zone: Backtest Signals with Fake Money")

            signal_df_full = pd.DataFrame(all_signals).copy()
            if 'timestamp' in signal_df_full.columns:
                signal_df_full['timestamp'] = pd.to_datetime(signal_df_full['timestamp'])

            # Dynamic timeframe mapping
            timeframe_to_df = {primary_label: df_primary}
            for tf_label, tf_df in higher_tfs:
                timeframe_to_df[tf_label] = tf_df

            results = []
            equity = starting_balance

            for _, sig in signal_df_full.iterrows():
                direction = sig.get('signal')
                entry_price = sig.get('price')
                ts = sig.get('timestamp')
                sl = sig.get('stop_loss')
                tp = sig.get('take_profit')

                result = 'Open'
                exit_price = np.nan
                exit_time = pd.NaT
                pips = 0.0
                pnl = 0.0

                if pd.notna(entry_price) and pd.notna(ts) and pd.notna(sl) and pd.notna(tp):
                    timeframe_label = sig.get('timeframe', primary_label)
                    price_df = timeframe_to_df.get(timeframe_label, df_primary).sort_values('Datetime')

                    after_mask = price_df['Datetime'] >= ts
                    if after_mask.any():
                        idx_start = price_df.index[after_mask][0]

                        for j in range(idx_start + 1, len(price_df)):
                            bar = price_df.iloc[j]
                            bar_low = bar['Low']
                            bar_high = bar['High']
                            bar_time = bar['Datetime']

                            if direction == 'Buy':
                                sl_hit = bar_low <= sl
                                tp_hit = bar_high >= tp
                                if sl_hit:
                                    result = 'Loss'
                                    exit_price = sl
                                    exit_time = bar_time
                                    break
                                if tp_hit:
                                    result = 'Win'
                                    exit_price = tp
                                    exit_time = bar_time
                                    break
                            elif direction == 'Sell':
                                sl_hit = bar_high >= sl
                                tp_hit = bar_low <= tp
                                if sl_hit:
                                    result = 'Loss'
                                    exit_price = sl
                                    exit_time = bar_time
                                    break
                                if tp_hit:
                                    result = 'Win'
                                    exit_price = tp
                                    exit_time = bar_time
                                    break

                        if result in ('Win', 'Loss'):
                            move = (exit_price - entry_price) if direction == 'Buy' else (entry_price - exit_price)
                            pips = move / pip_size
                            pnl = pips * pip_value_money
                            equity += pnl

                results.append({
                    'timestamp': ts,
                    'signal': direction,
                    'type': sig.get('type'),
                    'timeframe': sig.get('timeframe', '1m'),
                    'price': entry_price,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'exit_time': exit_time,
                    'exit_price': exit_price,
                    'result': result,
                    'pips': pips,
                    'pnl': pnl,
                    'equity_after': equity,
                })

            results_df = pd.DataFrame(results)

            if not results_df.empty:
                wins = (results_df['result'] == 'Win').sum()
                losses = (results_df['result'] == 'Loss').sum()
                opens = (results_df['result'] == 'Open').sum()
                total_pips = results_df['pips'].sum()

                st.markdown(
                    f"**Wins:** {wins} | **Losses:** {losses} | **Open:** {opens} | **Total Pips:** {total_pips:.1f}"
                )
                st.markdown(
                    f"**Starting Balance:** {starting_balance:.2f} → **Final Balance:** {equity:.2f}"
                )

                def highlight_result(row):
                    if row['result'] == 'Win':
                        color = 'background-color: rgba(0, 150, 0, 0.6); color: white;'
                    elif row['result'] == 'Loss':
                        color = 'background-color: rgba(200, 0, 0, 0.7); color: white;'
                    else:
                        color = ''
                    return [color] * len(row)

                preferred_order = ['1m', '5m', '15m', '30m']
                # Always show 1m, 5m, 15m & 30m result tabs so higher-timeframe
                # backtests have a clear place, even if no trades yet.
                unique_tfs = set(results_df['timeframe'].dropna().unique()) | set(preferred_order)
                unique_tfs_sorted = sorted(
                    unique_tfs,
                    key=lambda x: preferred_order.index(x) if x in preferred_order else len(preferred_order)
                )

                tabs = st.tabs([f"{tf} Results" for tf in unique_tfs_sorted])

                for tf, tab in zip(unique_tfs_sorted, tabs):
                    with tab:
                        tf_df = results_df[results_df['timeframe'] == tf]

                        if tf_df.empty:
                            st.info(f"No trades for {tf} timeframe.")
                        else:
                            wins_tf = (tf_df['result'] == 'Win').sum()
                            losses_tf = (tf_df['result'] == 'Loss').sum()
                            opens_tf = (tf_df['result'] == 'Open').sum()
                            total_pips_tf = tf_df['pips'].sum()

                            st.markdown(
                                f"**{tf} Wins:** {wins_tf} | **Losses:** {losses_tf} | **Open:** {opens_tf} | **Total Pips:** {total_pips_tf:.1f}"
                            )

                            st.dataframe(
                                tf_df.style.apply(highlight_result, axis=1),
                                use_container_width=True,
                            )

        # Main chart with subplots
        st.subheader(f"📈 {instrument_label} - {primary_label.upper()} Chart with Multi-Timeframe Analysis")
        
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.5, 0.25, 0.25],
            subplot_titles=('Price Action with Supply/Demand Zones', 'Volume & Delta', 'Cumulative Delta')
        )
        
        # Row 1: Candlesticks
        fig.add_trace(go.Candlestick(
            x=df_primary['Datetime'],
            open=df_primary['Open'],
            high=df_primary['High'],
            low=df_primary['Low'],
            close=df_primary['Close'],
            name="Price"
        ), row=1, col=1)
        
        # Add Supply/Demand Zones (15m zones projected across the full chart)
        if show_supply_demand and supply_demand_zones:
            for zone in supply_demand_zones:
                zone_start = df_primary['Datetime'].iloc[0]
                zone_end = df_primary['Datetime'].iloc[-1]

                color = 'rgba(255, 0, 0, 0.2)' if zone['type'] == 'Supply' else 'rgba(0, 255, 0, 0.2)'

                fig.add_shape(
                    type="rect",
                    x0=zone_start,
                    x1=zone_end,
                    y0=zone['bottom'],
                    y1=zone['top'],
                    fillcolor=color,
                    line=dict(color=color.replace('0.2', '0.5'), width=1),
                    layer='below',
                    row=1, col=1
                )
        
        # Add moving averages
        fig.add_trace(go.Scatter(
            x=df_primary['Datetime'],
            y=df_primary['SMA_50'],
            mode='lines',
            name='SMA-50',
            line=dict(color='blue', width=1)
        ), row=1, col=1)
        
        fig.add_trace(go.Scatter(
            x=df_primary['Datetime'],
            y=df_primary['VWAP'],
            mode='lines',
            name='VWAP',
            line=dict(color='purple', width=1, dash='dash')
        ), row=1, col=1)
        
        # Add signals to price chart with TP/SL visualization
        if all_signals:
            signal_df = pd.DataFrame(all_signals)
            buy_sigs = signal_df[signal_df['signal'] == 'Buy']
            sell_sigs = signal_df[signal_df['signal'] == 'Sell']
            
            if not buy_sigs.empty:
                fig.add_trace(go.Scatter(
                    x=buy_sigs['timestamp'],
                    y=buy_sigs['price'],
                    mode='markers',
                    name='Buy Signals',
                    marker=dict(color='lime', size=12, symbol='triangle-up'),
                    text=buy_sigs['type'],
                    hovertemplate='<b>%{text}</b><br>Price: %{y}<extra></extra>'
                ), row=1, col=1)
            
            if not sell_sigs.empty:
                fig.add_trace(go.Scatter(
                    x=sell_sigs['timestamp'],
                    y=sell_sigs['price'],
                    mode='markers',
                    name='Sell Signals',
                    marker=dict(color='red', size=12, symbol='triangle-down'),
                    text=sell_sigs['type'],
                    hovertemplate='<b>%{text}</b><br>Price: %{y}<extra></extra>'
                ), row=1, col=1)

            # TP/SL lines per trade
            for _, row_sig in signal_df.iterrows():
                ts = row_sig['timestamp']
                entry = row_sig['price']
                tp = row_sig.get('take_profit')
                sl = row_sig.get('stop_loss')
                color = 'lime' if row_sig['signal'] == 'Buy' else 'red'

                # Line to TP
                if tp is not None:
                    fig.add_trace(go.Scatter(
                        x=[ts, ts],
                        y=[entry, tp],
                        mode='lines',
                        line=dict(color=color, width=2, dash='dash'),
                        showlegend=False,
                        hoverinfo='skip'
                    ), row=1, col=1)

                # Line to SL
                if sl is not None:
                    fig.add_trace(go.Scatter(
                        x=[ts, ts],
                        y=[entry, sl],
                        mode='lines',
                        line=dict(color='gray', width=2, dash='dot'),
                        showlegend=False,
                        hoverinfo='skip'
                    ), row=1, col=1)
        
        # Row 2: Volume bars and Delta (primary timeframe)
        fig.add_trace(go.Bar(
            x=df_primary['Datetime'],
            y=df_primary['Buy_Volume'],
            name='Buy Volume',
            marker=dict(color='green'),
            opacity=0.6
        ), row=2, col=1)

        fig.add_trace(go.Bar(
            x=df_primary['Datetime'],
            y=df_primary['Sell_Volume'],
            name='Sell Volume',
            marker=dict(color='red'),
            opacity=0.6
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=df_primary['Datetime'],
            y=df_primary['Delta'],
            mode='lines',
            name='Delta',
            line=dict(color='yellow', width=2),
            yaxis='y2'
        ), row=2, col=1)

        # Row 3: Cumulative Delta (primary timeframe)
        colors = ['green' if val > 0 else 'red' for val in df_primary['Cumulative_Delta']]
        fig.add_trace(go.Bar(
            x=df_primary['Datetime'],
            y=df_primary['Cumulative_Delta'],
            name='Cumulative Delta',
            marker=dict(color=colors)
        ), row=3, col=1)
        
        fig.update_layout(
            height=900,
            template="plotly_dark",
            showlegend=True,
            xaxis_rangeslider_visible=False
        )
        
        fig.update_xaxes(title_text="Time", row=3, col=1)
        fig.update_yaxes(title_text="Price", row=1, col=1, tickformat=".5f")
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        fig.update_yaxes(title_text="Cumulative Delta", row=3, col=1)
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Footprint Chart (based on primary timeframe)
        if show_footprint:
            st.subheader("👣 Footprint Chart (Latest Bar)")
            latest_bar_idx = len(df_primary) - 1
            footprint_df = generate_footprint_data(df_primary, latest_bar_idx)
            
            if not footprint_df.empty:
                footprint_fig = plot_footprint_chart(footprint_df, df_primary.iloc[latest_bar_idx]['Datetime'])
                st.plotly_chart(footprint_fig, use_container_width=True)
                
                # Show dominant levels
                st.markdown("**Volume Profile Analysis:**")
                col1, col2, col3 = st.columns(3)
                
                max_buy_idx = footprint_df['Buy_Volume'].idxmax()
                max_sell_idx = footprint_df['Sell_Volume'].idxmax()
                poc_idx = footprint_df['Total_Volume'].idxmax()
                
                col1.metric("🟢 Max Buy Level", f"{footprint_df.loc[max_buy_idx, 'Price']:.5f}")
                col2.metric("🔴 Max Sell Level", f"{footprint_df.loc[max_sell_idx, 'Price']:.5f}")
                col3.metric("📍 POC (Point of Control)", f"{footprint_df.loc[poc_idx, 'Price']:.5f}")

if __name__ == "__main__":
    main()