import time
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


def load_twelvedata_catalog(uploaded_file) -> pd.DataFrame:
	if uploaded_file is None:
		return pd.DataFrame()
	try:
		frame = pd.read_csv(uploaded_file, sep=";", dtype=str).fillna("")
		return frame
	except Exception as exc:
		st.warning(f"Kon CSV niet lezen: {exc}")
		return pd.DataFrame()


def build_symbol_from_catalog_row(row: pd.Series, market_type: str) -> str:
	symbol = str(row.get("symbol", "")).strip()
	exchange = str(row.get("exchange", "")).strip()
	if market_type == "Forex":
		return symbol or "GBP/USD"
	# Voor Twelve Data werkt het vaak al met het kale symbool; exchange houden we als context.
	return symbol


def pick_symbol_from_catalog(
	market_type: str,
	stocks_df: pd.DataFrame,
	etf_df: pd.DataFrame,
	exchanges_df: pd.DataFrame,
) -> tuple[str, str, pd.DataFrame]:
	if market_type == "Forex":
		return "GBP/USD", "GBP/USD", pd.DataFrame()

	catalog = etf_df.copy() if market_type == "ETF" else stocks_df.copy()
	if catalog.empty:
		return "", "", pd.DataFrame()

	working = catalog.copy()
	working.columns = [str(column) for column in working.columns]

	if not exchanges_df.empty and "exchange" in working.columns and "name" in exchanges_df.columns:
		exchange_options = ["Alle exchanges"] + sorted(option for option in working["exchange"].dropna().unique() if option)
		selected_exchange = st.sidebar.selectbox(f"{market_type} exchange", exchange_options, index=0)
		if selected_exchange != "Alle exchanges":
			working = working[working["exchange"] == selected_exchange]

	if "country" in working.columns:
		country_options = ["Alle landen"] + sorted(option for option in working["country"].dropna().unique() if option)
		selected_country = st.sidebar.selectbox(f"{market_type} land", country_options, index=0)
		if selected_country != "Alle landen":
			working = working[working["country"] == selected_country]

	search_value = st.sidebar.text_input(f"Zoek {market_type}", value="")
	if search_value:
		search_lower = search_value.lower()
		name_series = working["name"].astype(str).str.lower() if "name" in working.columns else pd.Series("", index=working.index)
		symbol_series = working["symbol"].astype(str).str.lower() if "symbol" in working.columns else pd.Series("", index=working.index)
		working = working[name_series.str.contains(search_lower, na=False) | symbol_series.str.contains(search_lower, na=False)]

	if working.empty:
		return "", "", pd.DataFrame()

	working = working.head(300).reset_index(drop=True)
	labels = []
	for _, row in working.iterrows():
		name = row.get("name", "")
		symbol = row.get("symbol", "")
		exchange = row.get("exchange", "")
		country = row.get("country", "")
		labels.append(f"{symbol} | {name} | {exchange} | {country}")

	selected_label = st.sidebar.selectbox(f"Kies {market_type}", labels, index=0)
	selected_index = labels.index(selected_label)
	selected_row = working.iloc[selected_index]
	symbol = build_symbol_from_catalog_row(selected_row, market_type)
	pretty_label = f"{selected_row.get('symbol', symbol)} - {selected_row.get('name', '')}".strip(" -")
	return symbol, pretty_label, working
def fetch_dom_snapshot(api_url: str, symbol: str, bearer_token: str | None = None) -> dict[str, Any] | None:
	headers = {}
	if bearer_token:
		headers["Authorization"] = f"Bearer {bearer_token}"

	try:
		response = requests.get(api_url, headers=headers, params={"symbol": symbol}, timeout=10)
		response.raise_for_status()
		payload = response.json()
	except Exception as exc:
		st.error(f"Kon live DOM-data niet ophalen: {exc}")
		return None

	if not isinstance(payload, dict):
		st.error("API-response moet een JSON-object zijn.")
		return None

	bids = payload.get("bids")
	asks = payload.get("asks")
	if not isinstance(bids, list) or not isinstance(asks, list):
		st.error("API-response moet `bids` en `asks` arrays bevatten.")
		return None

	return payload


def normalize_book_rows(rows: list[dict[str, Any]], side: str) -> pd.DataFrame:
	normalized = []
	for item in rows:
		try:
			normalized.append(
				{
					"price": float(item.get("price", 0.0)),
					"size": float(item.get("size", 0.0)),
					"side": side,
				}
			)
		except (TypeError, ValueError):
			continue

	if not normalized:
		return pd.DataFrame(columns=["price", "size", "side"])

	frame = pd.DataFrame(normalized)
	return frame.sort_values("price", ascending=(side == "ask")).reset_index(drop=True)


def build_depth_chart(bids: pd.DataFrame, asks: pd.DataFrame) -> go.Figure:
	figure = go.Figure()

	if not bids.empty:
		bid_plot = bids.sort_values("price")
		bid_plot["cum_size"] = bid_plot["size"].cumsum()
		figure.add_trace(
			go.Scatter(
				x=bid_plot["price"],
				y=bid_plot["cum_size"],
				mode="lines",
				name="Bids cumulative",
				line=dict(color="#00c853", width=3),
				fill="tozeroy",
			)
		)

	if not asks.empty:
		ask_plot = asks.sort_values("price")
		ask_plot["cum_size"] = ask_plot["size"].cumsum()
		figure.add_trace(
			go.Scatter(
				x=ask_plot["price"],
				y=ask_plot["cum_size"],
				mode="lines",
				name="Asks cumulative",
				line=dict(color="#ff5252", width=3),
				fill="tozeroy",
			)
		)

	figure.update_layout(
		title="Depth of Market",
		template="plotly_dark",
		xaxis_title="Price",
		yaxis_title="Cumulative size",
		height=420,
		margin=dict(l=20, r=20, t=50, b=20),
	)
	return figure


def extract_heatmap_points(
	bids: pd.DataFrame,
	asks: pd.DataFrame,
	timestamp_label: str,
	price_rounding: int,
) -> list[dict[str, Any]]:
	rows = []
	for _, item in pd.concat([bids, asks], ignore_index=True).iterrows():
		rounded_price = round(float(item["price"]), price_rounding)
		rows.append(
			{
				"timestamp": timestamp_label,
				"price": rounded_price,
				"intensity": float(item["size"]),
				"side": item["side"],
			}
		)
	return rows


def build_heatmap_figure(history: list[dict[str, Any]]) -> go.Figure:
	figure = go.Figure()
	if not history:
		figure.update_layout(template="plotly_dark", title="Liquidity Heatmap")
		return figure

	frame = pd.DataFrame(history)
	pivot = frame.pivot_table(
		index="price",
		columns="timestamp",
		values="intensity",
		aggfunc="sum",
		fill_value=0.0,
	).sort_index(ascending=False)

	figure.add_trace(
		go.Heatmap(
			z=pivot.values,
			x=list(pivot.columns),
			y=list(pivot.index),
			colorscale="Turbo",
			colorbar=dict(title="Liquidity"),
		)
	)
	figure.update_layout(
		title="Liquidity Heatmap",
		template="plotly_dark",
		xaxis_title="Snapshot time",
		yaxis_title="Price",
		height=520,
		margin=dict(l=20, r=20, t=50, b=20),
	)
	return figure


def build_dom_table(bids: pd.DataFrame, asks: pd.DataFrame, max_levels: int) -> pd.DataFrame:
	bid_view = bids.nlargest(max_levels, "price")[["price", "size"]].reset_index(drop=True)
	ask_view = asks.nsmallest(max_levels, "price")[["price", "size"]].reset_index(drop=True)

	max_len = max(len(bid_view), len(ask_view))
	bid_view = bid_view.reindex(range(max_len))
	ask_view = ask_view.reindex(range(max_len))

	return pd.DataFrame(
		{
			"bid_price": bid_view["price"],
			"bid_size": bid_view["size"],
			"ask_price": ask_view["price"],
			"ask_size": ask_view["size"],
		}
	)


def init_state() -> None:
	if "dom_heatmap_history" not in st.session_state:
		st.session_state.dom_heatmap_history = []


def main() -> None:
	st.set_page_config(page_title="Live DOM + Heatmap", page_icon="📚", layout="wide")
	init_state()

	st.title("Live Heatmap + Depth of Market")
	st.caption("Gebouwd voor een echte live feed-adapter. Twelve Data catalogi verbeteren symboolselectie en marktcontext; live prijs en DOM komen uit je lokale adapter-feed.")

	st.sidebar.title("⚙️ Feed Settings")
	market_type = st.sidebar.selectbox("Markt type", ["Forex", "Equity", "ETF"], index=0)

	st.sidebar.markdown("---")
	st.sidebar.subheader("Twelve Data catalogi")
	st.sidebar.caption("Upload hier je Twelve Data Basic CSV-bestanden voor stocks, ETF's en exchanges.")
	stocks_file = st.sidebar.file_uploader("Stocks CSV", type=["csv"], key="stocks_csv")
	etf_file = st.sidebar.file_uploader("ETF CSV", type=["csv"], key="etf_csv")
	exchanges_file = st.sidebar.file_uploader("Exchanges CSV", type=["csv"], key="exchanges_csv")

	stocks_df = load_twelvedata_catalog(stocks_file)
	etf_df = load_twelvedata_catalog(etf_file)
	exchanges_df = load_twelvedata_catalog(exchanges_file)

	selected_symbol, default_label, filtered_catalog = pick_symbol_from_catalog(
		market_type,
		stocks_df,
		etf_df,
		exchanges_df,
	)

	twelvedata_symbol = st.sidebar.text_input(
		"Twelve Data symbol",
		value=selected_symbol or "GBP/USD",
	)
	api_url = st.sidebar.text_input("Live DOM API URL", value="http://127.0.0.1:8000/dom")
	bearer_token = st.sidebar.text_input("Bearer token (optioneel)", value="", type="password")
	symbol_label = st.sidebar.text_input("Symbol label", value=default_label or twelvedata_symbol or "GBP/USD")
	max_levels = st.sidebar.slider("Aantal DOM levels", min_value=5, max_value=50, value=15, step=5)
	history_limit = st.sidebar.slider("Aantal heatmap snapshots", min_value=10, max_value=200, value=60, step=10)
	price_rounding = st.sidebar.slider("Prijs afronding", min_value=3, max_value=6, value=5, step=1)
	auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
	refresh_seconds = st.sidebar.slider("Refresh (seconden)", min_value=1, max_value=30, value=3, step=1)

	if not stocks_df.empty or not etf_df.empty or not exchanges_df.empty:
		st.sidebar.caption(
			f"Catalog geladen: {len(stocks_df)} stocks, {len(etf_df)} ETF's, {len(exchanges_df)} exchanges"
		)

	if st.sidebar.button("Heatmap history resetten"):
		st.session_state.dom_heatmap_history = []
		st.sidebar.success("Heatmap history gewist.")

	with st.expander("Verwacht live API-formaat"):
		st.code(
			"""{
  "symbol": "GBP/USD",
  "timestamp": "2026-03-17T10:30:00Z",
  "last_price": 1.29452,
  "bids": [
	{"price": 1.29450, "size": 1800000},
	{"price": 1.29445, "size": 1350000}
  ],
  "asks": [
	{"price": 1.29455, "size": 1600000},
	{"price": 1.29460, "size": 1450000}
  ]
}""",
			language="json",
		)

	if not api_url:
		st.info("Vul eerst een live DOM API URL in.")
		st.stop()

	snapshot = fetch_dom_snapshot(api_url, twelvedata_symbol, bearer_token)
	if snapshot is None:
		st.stop()

	adapter_message = snapshot.get("message")
	if adapter_message:
		st.info(adapter_message)

	bids = normalize_book_rows(snapshot.get("bids", []), "bid")
	asks = normalize_book_rows(snapshot.get("asks", []), "ask")
	if bids.empty and asks.empty:
		st.warning("De feed gaf geen bruikbare bid/ask levels terug.")
		st.stop()

	timestamp_raw = snapshot.get("timestamp") or datetime.utcnow().isoformat()
	timestamp_label = pd.to_datetime(timestamp_raw).strftime("%H:%M:%S")
	last_price = snapshot.get("last_price")
	if last_price is None:
		if not bids.empty and not asks.empty:
			last_price = (float(bids["price"].max()) + float(asks["price"].min())) / 2
		elif not bids.empty:
			last_price = float(bids["price"].max())
		else:
			last_price = float(asks["price"].min())

	new_points = extract_heatmap_points(bids, asks, timestamp_label, price_rounding)
	history = st.session_state.dom_heatmap_history
	history.extend(new_points)

	unique_timestamps = list(dict.fromkeys(item["timestamp"] for item in history))
	if len(unique_timestamps) > history_limit:
		keep_timestamps = set(unique_timestamps[-history_limit:])
		history = [item for item in history if item["timestamp"] in keep_timestamps]
		st.session_state.dom_heatmap_history = history

	metric_col1, metric_col2, metric_col3 = st.columns(3)
	metric_col1.metric("Symbol", snapshot.get("symbol", symbol_label))
	metric_col2.metric("Laatste prijs", f"{float(last_price):.{price_rounding}f}")
	metric_col3.metric("Snapshot tijd", timestamp_label)

	if market_type in ("Equity", "ETF"):
		st.subheader("Twelve Data catalog context")
		if filtered_catalog.empty:
			st.info("Upload Twelve Data CSV's om equities of ETF's te filteren en selecteren.")
		else:
			preview_cols = [col for col in ["symbol", "name", "exchange", "country", "type", "currency"] if col in filtered_catalog.columns]
			st.dataframe(filtered_catalog[preview_cols].head(25), use_container_width=True)

	chart_col1, chart_col2 = st.columns([1.3, 1])
	with chart_col1:
		st.plotly_chart(build_heatmap_figure(st.session_state.dom_heatmap_history), use_container_width=True)
	with chart_col2:
		st.plotly_chart(build_depth_chart(bids, asks), use_container_width=True)

	st.subheader("Order Book")
	st.dataframe(build_dom_table(bids, asks, max_levels), use_container_width=True)

	raw_col1, raw_col2 = st.columns(2)
	with raw_col1:
		st.subheader("Bids")
		st.dataframe(bids.nlargest(max_levels, "price"), use_container_width=True)
	with raw_col2:
		st.subheader("Asks")
		st.dataframe(asks.nsmallest(max_levels, "price"), use_container_width=True)

	if auto_refresh:
		time.sleep(refresh_seconds)
		st.rerun()


if __name__ == "__main__":
	main()