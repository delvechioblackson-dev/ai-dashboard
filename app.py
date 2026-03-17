

import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time

# Try to import add_all_ta_features from ta, else define a fallback
try:
	from ta import add_all_ta_features
except ImportError:
	def add_all_ta_features(df, open, high, low, close, volume=None):
		# Simple RSI approximation using price changes
		delta = df[close].diff()
		up = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
		down = -delta.clip(upper=0).rolling(window=14, min_periods=1).mean()
		rs = up / (down.replace(0, 1e-8))
		df['momentum_rsi'] = 100 - (100 / (1 + rs)).fillna(50)
		# Simple MACD-like signal: difference between short and long EMA
		short_ema = df[close].ewm(span=12, adjust=False).mean()
		long_ema = df[close].ewm(span=26, adjust=False).mean()
		df['trend_macd'] = (short_ema - long_ema).fillna(0)
		return df

# Define symbols for FX pairs
symbols = {
	'EURUSD': ('EUR', 'USD'),
	'EURGBP': ('EUR', 'GBP'),
	'USDJPY': ('USD', 'JPY'),
	'GBPUSD': ('GBP', 'USD'),
	'XAUUSD': ('XAU', 'USD'),
	'BTCUSD': ('BTC', 'USD'),
}

# Fetch FX data from exchangerate.host (free, no API key required)
def fetch_realtime_data(symbol, granularity='M1'):
	import numpy as np
	min_rows = 15
	base, quote = symbols[symbol]
	api_key = "3f620b8b32-36d07209f8-t9y7ax"
	url = f"https://api.fastforex.io/fetch-one?from={base}&to={quote}&api_key={api_key}"
	try:
		response = requests.get(url, timeout=10)
		data = response.json()
		if 'result' in data and quote in data['result']:
			close = float(data['result'][quote])
		elif 'result' in data and 'rate' in data['result']:
			close = float(data['result']['rate'])
		else:
			raise ValueError(f"Unexpected API response: {data}")
		# Simulate a time series for demo: add small random walk
		closes = [close + np.random.normal(0, close * 0.001) for _ in range(min_rows)]
		# If closes is too short, pad with the first value
		if len(closes) < min_rows:
			pad_value = closes[0] if closes else 1.0
			closes = [pad_value] * (min_rows - len(closes)) + closes
		closes = closes[-min_rows:]
		df = pd.DataFrame({
			'close': closes,
			'open': closes,
			'high': [c + abs(np.random.normal(0, close * 0.0005)) for c in closes],
			'low': [c - abs(np.random.normal(0, close * 0.0005)) for c in closes],
			'volume': [0]*min_rows
		}, index=[pd.Timestamp.now() - pd.Timedelta(minutes=i) for i in reversed(range(min_rows))])
		return df
	except Exception as e:
		st.error(f"FX API error: {e}")
		now = pd.Timestamp.now()
		closes = [1.0]*min_rows
		df = pd.DataFrame({
			'close': closes,
			'open': closes,
			'high': closes,
			'low': closes,
			'volume': [0]*min_rows
		}, index=[now - pd.Timedelta(minutes=i) for i in reversed(range(min_rows))])
		return df
def generate_signal(df, symbol_metrics, fx_rates=None, symbol=None):
	# Add simple RSI and MACD-style indicators without relying on external TA package
	delta = df['close'].diff()
	up = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
	down = -delta.clip(upper=0).rolling(window=14, min_periods=1).mean()
	rs = up / (down.replace(0, 1e-8))
	rsi = 100 - (100 / (1 + rs)).fillna(50)
	short_ema = df['close'].ewm(span=12, adjust=False).mean()
	long_ema = df['close'].ewm(span=26, adjust=False).mean()
	macd = (short_ema - long_ema).fillna(0)
	current_price = df['close'].iloc[-1]

	# Use pip_size from Streamlit session state if available, else default
	pip_size = 0.0001
	if hasattr(st, 'session_state') and 'pip_size' in st.session_state:
		pip_size = st.session_state['pip_size']

	# Use fx_rates for USD/GBP pairs if provided
	fx_adj = 1.0
	if fx_rates and symbol:
		if 'USD' in symbol:
			fx_adj = fx_rates.get('USD', 1.0)
		elif 'GBP' in symbol:
			fx_adj = fx_rates.get('GBP', 1.0)

	# Determine signal direction based on indicators
	if symbol_metrics['profit_factor'] >= 1.2 and rsi.iloc[-1] < 30 and macd.iloc[-1] > 0:
		signal_type = 'BUY'
		tp = current_price + pip_size * fx_adj
		sl = current_price - pip_size * fx_adj
	elif symbol_metrics['profit_factor'] < 1.2 and rsi.iloc[-1] > 70:
		signal_type = 'SELL'
		tp = current_price - pip_size * fx_adj
		sl = current_price + pip_size * fx_adj
	else:
		# Force a signal: if MACD positive, BUY; else SELL
		if macd.iloc[-1] > 0:
			signal_type = 'BUY'
			tp = current_price + pip_size * fx_adj
			sl = current_price - pip_size * fx_adj
		else:
			signal_type = 'SELL'
			tp = current_price - pip_size * fx_adj
			sl = current_price + pip_size * fx_adj

	return {
		'signal': signal_type,
		'entry': float(round(current_price, 5)),  # Forex precision
		'take_profit': float(round(tp, 5)),
		'stop_loss': float(round(sl, 5))
	}

# Main function
def main():
	# Initialize FX rates in session state if not present
	if 'fx_rates' not in st.session_state:
		st.session_state['fx_rates'] = {'USD': 1.0, 'GBP': 1.0}
	fxtxt = f"EUR/USD: {st.session_state['fx_rates'].get('USD', 'N/A')} | EUR/GBP: {st.session_state['fx_rates'].get('GBP', 'N/A')}"
	st.info(f"Current FX Rates: {fxtxt}")
	# Compact sidebar input for pip size
	with st.sidebar:
		st.markdown("**Pip Size**")
		pip_size = st.number_input(
			"Pip size (set value)",
			min_value=0.00001,
			max_value=100.0,
			value=0.0001,
			step=0.00001,
			format="%f",
			label_visibility="collapsed"
		)
		st.session_state['pip_size'] = pip_size
		if st.button("Reset Data", help="Clear all chart data and reload"):
			for symbol in ["EURUSD", "EURGBP", "USDJPY", "GBPUSD"]:
				st.session_state.pop(f"data_{symbol}", None)
				st.session_state.pop(f"timeframe_{symbol}", None)
			st.experimental_rerun()
	st.set_page_config(
		page_title="Blackson Trading Signals",
		page_icon="📈",
		layout="wide",
		initial_sidebar_state="expanded",
		menu_items=None
	)

	# Custom CSS for black background and light blue accents
	st.markdown("""
	<style>
		.stApp {
			background-color: #000000;  /* Black background */
			color: #ADD8E6;  /* Light blue text */
		}
		.stButton>button {
			background-color: #ADD8E6;  /* Light blue buttons */
			color: #000000;  /* Black text on buttons */
		}
		.stSubheader {
			color: #ADD8E6;  /* Light blue subheaders */
		}
		.stWrite {
			color: #ADD8E6;  /* Light blue text */
		}
	</style>
	""", unsafe_allow_html=True)

	# Logo: Styled text-based logo with gradient
	st.markdown("""
	<div style="text-align: center; font-size: 48px; font-weight: bold; background: linear-gradient(to right, #ADD8E6, #0000FF, #800080, #008000, #00FF00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; padding: 20px; border-radius: 10px;">
		BLACKSON'S TRADING FUTURE
	</div>
	""", unsafe_allow_html=True)

	st.title("Trading Signals Dashboard")
	st.write("Historical trading signals based on RSI and MACD indicators from demo market data.")
	st.warning("This is a demo with historical data. Practice trading uses fake money.")

	# Static metrics for FX pairs
	metrics = {
		'EURUSD': {'profit_factor': 1.58, 'win_rate': 53.7},
		'EURGBP': {'profit_factor': 1.20, 'win_rate': 52.0},
		'USDJPY': {'profit_factor': 1.10, 'win_rate': 51.0},
		'GBPUSD': {'profit_factor': 0.95, 'win_rate': 50.0},
		'XAUUSD': {'profit_factor': 1.30, 'win_rate': 55.0},
		'BTCUSD': {'profit_factor': 1.40, 'win_rate': 56.0},
	}

	signals = {}

	tab1, tab2, tab3, tab4 = st.tabs(["EURUSD", "EURGBP", "USDJPY", "GBPUSD"])

	timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
	gran_map = {'1m': 'M1', '5m': 'M5', '15m': 'M15', '30m': 'M30', '1h': 'H1', '4h': 'H4', '1d': 'D', '1w': 'W'}
	gran_to_td = {'M1': '1min', 'M5': '5min', 'M15': '15min', 'M30': '30min', 'H1': '1H', 'H4': '4H', 'D': '1D', 'W': '1W'}

	for tab, symbol in zip([tab1, tab2, tab3, tab4], ["EURUSD", "EURGBP", "USDJPY", "GBPUSD"]):
		with tab:
			timeframe = st.selectbox("Timeframe", timeframes, index=0, key=f"timeframe_{symbol}")
			chart_type = st.selectbox("Chart Type", ["Line", "Candlestick"], index=0, key=f"chart_{symbol}")
			if st.button("Update Chart", key=f"update_{symbol}"):
				st.rerun()
			gran = gran_map[timeframe]
			if f"timeframe_{symbol}" not in st.session_state or st.session_state[f"timeframe_{symbol}"] != timeframe:
				st.session_state[f"timeframe_{symbol}"] = timeframe
				st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
			else:
				# Defensive: if data is missing or too short, re-fetch
				if f"data_{symbol}" not in st.session_state or len(st.session_state[f"data_{symbol}"]) < 15:
					st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
				else:
					# Append new data point
					last_close = st.session_state[f"data_{symbol}"]['close'].iloc[-1]
					new_close = last_close + np.random.normal(0, last_close * 0.001)
					new_open = new_close + np.random.normal(0, last_close * 0.0001)
					new_high = max(new_open, new_close) + abs(np.random.normal(0, last_close * 0.0005))
					new_low = min(new_open, new_close) - abs(np.random.normal(0, last_close * 0.0005))
					new_volume = np.random.randint(100, 1000)
					new_index = st.session_state[f"data_{symbol}"].index[-1] + pd.Timedelta(gran_to_td[gran])
					new_row = pd.DataFrame({
						'open': [new_open],
						'high': [new_high],
						'low': [new_low],
						'close': [new_close],
						'volume': [new_volume]
					}, index=[new_index])
					st.session_state[f"data_{symbol}"] = pd.concat([st.session_state[f"data_{symbol}"], new_row])
			min_rows = 15
			df_raw = st.session_state[f"data_{symbol}"]
			def pad_col(col, default=0):
				vals = df_raw[col].tolist() if col in df_raw else []
				pad_value = vals[-1] if vals else default
				vals = [pad_value] * (min_rows - len(vals)) + vals
				return vals[-min_rows:]
			closes = pad_col('close', 0)
			opens = pad_col('open', closes[0] if closes else 0)
			highs = pad_col('high', closes[0] if closes else 0)
			lows = pad_col('low', closes[0] if closes else 0)
			volumes = pad_col('volume', 0)
			for arr in [closes, opens, highs, lows, volumes]:
				if len(arr) < min_rows:
					arr[:] = [arr[-1] if arr else 0] * (min_rows - len(arr)) + arr
			df = pd.DataFrame({
				'close': closes,
				'open': opens,
				'high': highs,
				'low': lows,
				'volume': volumes
			}, index=[pd.Timestamp.now() - pd.Timedelta(minutes=i) for i in reversed(range(min_rows))])
			st.metric(label=f"Live {symbol} Price", value=closes[-1])
			sig = generate_signal(df, metrics[symbol], None, symbol)
			signals[symbol] = sig
			if isinstance(sig, dict) and 'signal' in sig:
				st.write(f"**Signal**: {sig['signal']} | Entry: {sig['entry']} | TP: {sig['take_profit']} | SL: {sig['stop_loss']}")
				fig = go.Figure()
				if chart_type == "Candlestick":
					fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Candles'))
				else:
					fig.add_trace(go.Scatter(x=df.index, y=df['close'], mode='lines', name='Close Price'))

				# Mark entry and TP/SL for this symbol's latest signal
				entry_time = df.index[-1]
				entry_price = sig['entry']
				tp = sig.get('take_profit')
				sl = sig.get('stop_loss')
				color = 'lime' if sig['signal'] == 'BUY' else 'red'

				# Entry marker
				fig.add_trace(go.Scatter(
					x=[entry_time],
					y=[entry_price],
					mode='markers',
					name=f"{symbol} {sig['signal']} Entry",
					marker=dict(color=color, size=10, symbol='triangle-up' if sig['signal'] == 'BUY' else 'triangle-down')
				))

				# TP line
				if tp is not None:
					fig.add_trace(go.Scatter(
						x=[entry_time, entry_time],
						y=[entry_price, tp],
						mode='lines',
						line=dict(color=color, width=1, dash='dash'),
						showlegend=False
					))

				# SL line
				if sl is not None:
					fig.add_trace(go.Scatter(
						x=[entry_time, entry_time],
						y=[entry_price, sl],
						mode='lines',
						line=dict(color='gray', width=1, dash='dot'),
						showlegend=False
					))

				fig.update_layout(title=f"{symbol} {timeframe} Chart", xaxis_title="Time", yaxis_title="Price")
				config = {'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape']}
				st.plotly_chart(fig, config=config)
				with st.expander("Order Flow"):
					levels = [sig['entry'] + i * (sig['entry'] * 0.0001) for i in range(-10, 11)]
					bid_vol = [np.random.randint(10, 100) for _ in levels]
					ask_vol = [np.random.randint(10, 100) for _ in levels]
					fig_of = go.Figure()
					fig_of.add_trace(go.Bar(x=levels, y=bid_vol, name='Bid Volume', marker_color='green', offsetgroup=0))
					fig_of.add_trace(go.Bar(x=levels, y=ask_vol, name='Ask Volume', marker_color='red', offsetgroup=1))
					fig_of.update_layout(title="Order Flow", xaxis_title="Price Level", yaxis_title="Volume", barmode='group')
					st.plotly_chart(fig_of)
			else:
				st.write(f"Error - {sig}")
		symbol = 'XAUUSD'
		timeframe = st.selectbox("Timeframe", timeframes, index=0, key=f"timeframe_{symbol}")
		chart_type = st.selectbox("Chart Type", ["Line", "Candlestick"], index=0, key=f"chart_{symbol}")
		if st.button("Update Chart", key=f"update_{symbol}"):
			st.rerun()
		gran = gran_map[timeframe]
		if f"timeframe_{symbol}" not in st.session_state or st.session_state[f"timeframe_{symbol}"] != timeframe:
			st.session_state[f"timeframe_{symbol}"] = timeframe
			st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		else:
			# Append new data point
			if f"data_{symbol}" in st.session_state:
				last_close = st.session_state[f"data_{symbol}"]['close'].iloc[-1]
				new_close = last_close + np.random.normal(0, last_close * 0.001)
				new_open = new_close + np.random.normal(0, last_close * 0.0001)
				new_high = max(new_open, new_close) + abs(np.random.normal(0, last_close * 0.0005))
				new_low = min(new_open, new_close) - abs(np.random.normal(0, last_close * 0.0005))
				new_volume = np.random.randint(100, 1000)
				new_index = st.session_state[f"data_{symbol}"].index[-1] + pd.Timedelta(gran_to_td[gran])
				new_row = pd.DataFrame({
					'open': [new_open],
					'high': [new_high],
					'low': [new_low],
					'close': [new_close],
					'volume': [new_volume]
				}, index=[new_index])
				st.session_state[f"data_{symbol}"] = pd.concat([st.session_state[f"data_{symbol}"], new_row])
			else:
				st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		df = st.session_state[f"data_{symbol}"].tail(100)
		sig = generate_signal(df, metrics[symbol])
		signals[symbol] = sig
		if isinstance(sig, dict) and 'signal' in sig:
			st.write(f"**Signal**: {sig['signal']} | Entry: {sig['entry']} | TP: {sig['take_profit']} | SL: {sig['stop_loss']}")
			fig = go.Figure()
			if chart_type == "Candlestick":
				fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Candles'))
			else:
				fig.add_trace(go.Scatter(x=df.index, y=df['close'], mode='lines', name='Close Price'))

			# Visualize entry, TP and SL for gold signal
			entry_time = df.index[-1]
			entry_price = sig['entry']
			tp = sig.get('take_profit')
			sl = sig.get('stop_loss')
			color = 'lime' if sig['signal'] == 'BUY' else 'red'

			fig.add_trace(go.Scatter(
				x=[entry_time],
				y=[entry_price],
				mode='markers',
				name=f"{symbol} {sig['signal']} Entry",
				marker=dict(color=color, size=10, symbol='triangle-up' if sig['signal'] == 'BUY' else 'triangle-down')
			))

			if tp is not None:
				fig.add_trace(go.Scatter(
					x=[entry_time, entry_time],
					y=[entry_price, tp],
					mode='lines',
					line=dict(color=color, width=1, dash='dash'),
					showlegend=False
				))

			if sl is not None:
				fig.add_trace(go.Scatter(
					x=[entry_time, entry_time],
					y=[entry_price, sl],
					mode='lines',
					line=dict(color='gray', width=1, dash='dot'),
					showlegend=False
				))

			fig.update_layout(title=f"{symbol} {timeframe} Chart", xaxis_title="Time", yaxis_title="Price")
			config = {'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape']}
			st.plotly_chart(fig, config=config)
			with st.expander("Order Flow"):
				levels = [sig['entry'] + i * (sig['entry'] * 0.0001) for i in range(-10, 11)]
				bid_vol = [np.random.randint(10, 100) for _ in levels]
				ask_vol = [np.random.randint(10, 100) for _ in levels]
				fig_of = go.Figure()
				fig_of.add_trace(go.Bar(x=levels, y=bid_vol, name='Bid Volume', marker_color='green', offsetgroup=0))
				fig_of.add_trace(go.Bar(x=levels, y=ask_vol, name='Ask Volume', marker_color='red', offsetgroup=1))
				fig_of.update_layout(title="Order Flow", xaxis_title="Price Level", yaxis_title="Volume", barmode='group')
				st.plotly_chart(fig_of)
		else:
			st.write(f"Error - {sig}")

	with tab3:
		symbol = 'GBPUSD'
		timeframe = st.selectbox("Timeframe", timeframes, index=0, key=f"timeframe_{symbol}")
		chart_type = st.selectbox("Chart Type", ["Line", "Candlestick"], index=0, key=f"chart_{symbol}")
		if st.button("Update Chart", key=f"update_{symbol}"):
			st.rerun()
		gran = gran_map[timeframe]
		if f"timeframe_{symbol}" not in st.session_state or st.session_state[f"timeframe_{symbol}"] != timeframe:
			st.session_state[f"timeframe_{symbol}"] = timeframe
			st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		else:
			# Append new data point
			if f"data_{symbol}" in st.session_state:
				last_close = st.session_state[f"data_{symbol}"]['close'].iloc[-1]
				new_close = last_close + np.random.normal(0, last_close * 0.001)
				new_open = new_close + np.random.normal(0, last_close * 0.0001)
				new_high = max(new_open, new_close) + abs(np.random.normal(0, last_close * 0.0005))
				new_low = min(new_open, new_close) - abs(np.random.normal(0, last_close * 0.0005))
				new_volume = np.random.randint(100, 1000)
				new_index = st.session_state[f"data_{symbol}"].index[-1] + pd.Timedelta(gran_to_td[gran])
				new_row = pd.DataFrame({
					'open': [new_open],
					'high': [new_high],
					'low': [new_low],
					'close': [new_close],
					'volume': [new_volume]
				}, index=[new_index])
				st.session_state[f"data_{symbol}"] = pd.concat([st.session_state[f"data_{symbol}"], new_row])
			else:
				st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		df = st.session_state[f"data_{symbol}"].tail(100)
		sig = generate_signal(df, metrics[symbol])
		signals[symbol] = sig
		if isinstance(sig, dict) and 'signal' in sig:
			st.write(f"**Signal**: {sig['signal']} | Entry: {sig['entry']} | TP: {sig['take_profit']} | SL: {sig['stop_loss']}")
			fig = go.Figure()
			if chart_type == "Candlestick":
				fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Candles'))
			else:
				fig.add_trace(go.Scatter(x=df.index, y=df['close'], mode='lines', name='Close Price'))

			# Visualize entry, TP and SL for BTC signal
			entry_time = df.index[-1]
			entry_price = sig['entry']
			tp = sig.get('take_profit')
			sl = sig.get('stop_loss')
			color = 'lime' if sig['signal'] == 'BUY' else 'red'

			fig.add_trace(go.Scatter(
				x=[entry_time],
				y=[entry_price],
				mode='markers',
				name=f"{symbol} {sig['signal']} Entry",
				marker=dict(color=color, size=10, symbol='triangle-up' if sig['signal'] == 'BUY' else 'triangle-down')
			))

			if tp is not None:
				fig.add_trace(go.Scatter(
					x=[entry_time, entry_time],
					y=[entry_price, tp],
					mode='lines',
					line=dict(color=color, width=1, dash='dash'),
					showlegend=False
				))

			if sl is not None:
				fig.add_trace(go.Scatter(
					x=[entry_time, entry_time],
					y=[entry_price, sl],
					mode='lines',
					line=dict(color='gray', width=1, dash='dot'),
					showlegend=False
				))

			fig.update_layout(title=f"{symbol} {timeframe} Chart", xaxis_title="Time", yaxis_title="Price")
			config = {'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape']}
			st.plotly_chart(fig, config=config)
			with st.expander("Order Flow"):
				levels = [sig['entry'] + i * (sig['entry'] * 0.0001) for i in range(-10, 11)]
				bid_vol = [np.random.randint(10, 100) for _ in levels]
				ask_vol = [np.random.randint(10, 100) for _ in levels]
				fig_of = go.Figure()
				fig_of.add_trace(go.Bar(x=levels, y=bid_vol, name='Bid Volume', marker_color='green', offsetgroup=0))
				fig_of.add_trace(go.Bar(x=levels, y=ask_vol, name='Ask Volume', marker_color='red', offsetgroup=1))
				fig_of.update_layout(title="Order Flow", xaxis_title="Price Level", yaxis_title="Volume", barmode='group')
				st.plotly_chart(fig_of)
		else:
			st.write(f"Error - {sig}")

	with tab4:
		symbol = 'BTCUSD'
		timeframe = st.selectbox("Timeframe", timeframes, index=0, key=f"timeframe_{symbol}")
		chart_type = st.selectbox("Chart Type", ["Line", "Candlestick"], index=0, key=f"chart_{symbol}")
		if st.button("Update Chart", key=f"update_{symbol}"):
			st.rerun()
		gran = gran_map[timeframe]
		if f"timeframe_{symbol}" not in st.session_state or st.session_state[f"timeframe_{symbol}"] != timeframe:
			st.session_state[f"timeframe_{symbol}"] = timeframe
			st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		else:
			# Append new data point
			if f"data_{symbol}" in st.session_state:
				last_close = st.session_state[f"data_{symbol}"]['close'].iloc[-1]
				new_close = last_close + np.random.normal(0, last_close * 0.001)
				new_open = new_close + np.random.normal(0, last_close * 0.0001)
				new_high = max(new_open, new_close) + abs(np.random.normal(0, last_close * 0.0005))
				new_low = min(new_open, new_close) - abs(np.random.normal(0, last_close * 0.0005))
				new_volume = np.random.randint(100, 1000)
				new_index = st.session_state[f"data_{symbol}"].index[-1] + pd.Timedelta(gran_to_td[gran])
				new_row = pd.DataFrame({
					'open': [new_open],
					'high': [new_high],
					'low': [new_low],
					'close': [new_close],
					'volume': [new_volume]
				}, index=[new_index])
				st.session_state[f"data_{symbol}"] = pd.concat([st.session_state[f"data_{symbol}"], new_row])
			else:
				st.session_state[f"data_{symbol}"] = fetch_realtime_data(symbol, gran)
		df = st.session_state[f"data_{symbol}"].tail(100)
		sig = generate_signal(df, metrics[symbol])
		signals[symbol] = sig
		if isinstance(sig, dict) and 'signal' in sig:
			st.write(f"**Signal**: {sig['signal']} | Entry: {sig['entry']} | TP: {sig['take_profit']} | SL: {sig['stop_loss']}")
			fig = go.Figure()
			if chart_type == "Candlestick":
				fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Candles'))
			else:
				fig.add_trace(go.Scatter(x=df.index, y=df['close'], mode='lines', name='Close Price'))
			fig.update_layout(title=f"{symbol} {timeframe} Chart", xaxis_title="Time", yaxis_title="Price")
			config = {'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape']}
			st.plotly_chart(fig, config=config)
			with st.expander("Order Flow"):
				levels = [sig['entry'] + i * (sig['entry'] * 0.0001) for i in range(-10, 11)]
				bid_vol = [np.random.randint(10, 100) for _ in levels]
				ask_vol = [np.random.randint(10, 100) for _ in levels]
				fig_of = go.Figure()
				fig_of.add_trace(go.Bar(x=levels, y=bid_vol, name='Bid Volume', marker_color='green', offsetgroup=0))
				fig_of.add_trace(go.Bar(x=levels, y=ask_vol, name='Ask Volume', marker_color='red', offsetgroup=1))
				fig_of.update_layout(title="Order Flow", xaxis_title="Price Level", yaxis_title="Volume", barmode='group')
				st.plotly_chart(fig_of)
		else:
			st.write(f"Error - {sig}")

	# Optional: Add a refresh button
	if st.button("Refresh Signals"):
		st.rerun()

	st.header("Chart Settings")
	st.write("Global settings for all charts.")
	global_timeframe = st.selectbox("Global Timeframe", timeframes, index=0, key="global_timeframe")
	global_chart_type = st.selectbox("Global Chart Type", ["Line", "Candlestick"], index=0, key="global_chart")
	auto_update = st.checkbox("Auto Update Charts (every 5 seconds)", key="auto_update")
	if st.button("Apply Global Settings"):
		st.rerun()

	# Practice Trading Area with fake money
	st.header("Practice Trading Area")
	st.write("Simulate trades with fake money based on signals.")

	if 'balance' not in st.session_state:
		st.session_state.balance = 10000.0
	if 'trades' not in st.session_state:
		st.session_state.trades = []

	st.write(f"**Fake Balance: ${st.session_state.balance:.2f}**")

	for symbol, sig in signals.items():
		if isinstance(sig, dict) and 'signal' in sig:
			st.subheader(f"{symbol} Practice Trade")
			st.write(f"Signal: {sig['signal']} | Entry: {sig['entry']} | TP: {sig['take_profit']} | SL: {sig['stop_loss']}")
			if st.button(f"Execute {sig['signal']} for {symbol}", key=f"trade_{symbol}"):
				# Simulate trade outcome: 70% chance to hit TP, 30% to hit SL
				if np.random.rand() < 0.7:
					# Hit TP
					if sig['signal'] == 'BUY':
						profit = (sig['take_profit'] - sig['entry']) * 100000  # Approx profit in USD
					else:
						profit = (sig['entry'] - sig['take_profit']) * 100000
					st.session_state.balance += profit
					st.success(f"Simulated {sig['signal']} trade executed and closed at TP. Profit: ${profit:.2f}")
					st.session_state.trades.append({'symbol': symbol, 'signal': sig['signal'], 'outcome': 'TP', 'amount': profit})
				else:
					# Hit SL
					if sig['signal'] == 'BUY':
						loss = (sig['entry'] - sig['stop_loss']) * 100000
					else:
						loss = (sig['stop_loss'] - sig['entry']) * 100000
					st.session_state.balance -= loss
					st.error(f"Simulated {sig['signal']} trade executed and closed at SL. Loss: ${loss:.2f}")
					st.session_state.trades.append({'symbol': symbol, 'signal': sig['signal'], 'outcome': 'SL', 'amount': -loss})
		else:
			st.write(f"No valid signal for {symbol}")

	st.subheader("Trade History")
	if st.session_state.trades:
		for trade in reversed(st.session_state.trades[-10:]):  # Show last 10 trades
			st.write(f"{trade['symbol']} {trade['signal']} - {trade['outcome']} - ${trade['amount']:.2f}")
	else:
		st.write("No trades yet.")

	return signals

if __name__ == "__main__":
	while True:
		signals = main()
		if not st.session_state.get('auto_update', False):
			break
		time.sleep(5)
		st.rerun()