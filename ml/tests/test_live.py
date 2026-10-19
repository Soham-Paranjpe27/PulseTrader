"""Phase 17 live system tests: Kite parser, candles, validation, feed states, providers and the
live pipeline's feature parity with the research dataset (golden fixture, offline)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from pulsetrader.config import FEATURE_VERSION
from pulsetrader.labels.labels import label_name
from pulsetrader.live import kite
from pulsetrader.live.cache import BarCache
from pulsetrader.live.candles import CandleAggregator
from pulsetrader.live.evaluate import evaluate, round_trip_cost_bp
from pulsetrader.live.events import IST, Bar, FeedState, Tick, in_session
from pulsetrader.live.features import FeatureMismatch, LiveUniverse, check_features
from pulsetrader.live.pipeline import LivePipeline, MemorySink, PipelineConfig
from pulsetrader.live.providers import (
    HistoricalProvider,
    MockProvider,
    ProviderError,
    ReservedPeriodError,
    SnapshotProvider,
    provider_from_env,
)
from pulsetrader.live.validate import BarValidator, FeedMonitor

T0 = datetime(2025, 6, 13, 10, 0, tzinfo=IST)


# --- Kite binary protocol -------------------------------------------------------------------------
def _full_packet(token: int, ltp_paise: int, vol: int, ts: int) -> bytes:
    head = struct.pack(">11i", token, ltp_paise, 10, ltp_paise, vol, 5, 6, ltp_paise - 100,
                       ltp_paise + 200, ltp_paise - 300, ltp_paise - 50)  # fmt: skip
    tail = struct.pack(">5i", ts - 1, 0, 0, 0, ts)
    return head + tail + bytes(120)  # market depth (ignored)


def _message(*packets: bytes) -> bytes:
    out = struct.pack(">H", len(packets))
    for p in packets:
        out += struct.pack(">H", len(p)) + p
    return out


def test_kite_parses_full_quote_index_and_ltp_packets():
    ts = int(T0.timestamp())
    full = _full_packet(738561, 142_050, 1_234_567, ts)
    assert len(full) == 184
    quote = full[:44]
    index = struct.pack(">8i", 256265, 2_450_010, 2_460_000, 2_440_000, 2_445_000, 2_449_000, 1000, ts)
    ltp = struct.pack(">2i", 738561, 142_100)
    d = kite.parse_message(_message(full, quote, index, ltp))
    assert [x["mode"] for x in d] == ["full", "quote", "full", "ltp"]
    assert d[0]["last_price"] == 1420.50 and d[0]["volume_traded"] == 1_234_567
    assert d[0]["exchange_timestamp"] == T0.astimezone(UTC)
    assert d[0]["open"] == 1419.50 and d[0]["high"] == 1422.50
    assert "exchange_timestamp" not in d[1]
    assert d[2]["tradable"] is False and d[2]["last_price"] == 24500.10  # index: segment 9
    assert d[3]["last_price"] == 1421.0
    assert kite.parse_message(b"\x00") == []  # heartbeat
    with pytest.raises(ValueError):
        kite.parse_message(_message(full)[:-10])


def test_kite_tick_uses_exchange_time_and_cumulative_volume():
    d = kite.parse_message(_message(_full_packet(738561, 142_050, 500, int(T0.timestamp()))))[0]
    recv = T0.astimezone(UTC) + timedelta(seconds=1)
    t = kite.to_tick(d, "RELIANCE", recv)
    assert t.ts == T0 and t.price == 1420.5 and t.volume == 500.0 and t.received == recv


def test_kite_instrument_map_and_checksum():
    csv_text = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
        "instrument_type,segment,exchange\n"
        "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.1,1,EQ,NSE,NSE\n"
        "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
        "260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0,0,EQ,INDICES,NSE\n"
        "12345,99,RELIANCE,RELIANCE FUT,0,2025-06-26,0,0.1,250,FUT,NFO-FUT,NFO\n"
    )
    m = kite.instrument_map(csv_text, ["RELIANCE", "NIFTY", "BANKNIFTY", "TCS"])
    assert m == {"RELIANCE": 738561, "NIFTY": 256265, "BANKNIFTY": 260105}
    assert kite.checksum("k", "r", "s") == hashlib.sha256(b"krs").hexdigest()
    assert kite.login_url("abc").endswith("v=3&api_key=abc")


def test_kite_provider_needs_credentials(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "kite")
    with pytest.raises(ProviderError, match="MARKET_DATA_API_KEY"):
        provider_from_env(Path("."))


# --- candles, validation, feed state ---------------------------------------------------------------
def test_candle_aggregator_builds_minute_bars_from_cumulative_volume():
    agg = CandleAggregator()
    t = [Tick("A", T0 + timedelta(seconds=s), p, v) for s, p, v in
         [(1, 10.0, 100), (20, 10.5, 130), (40, 9.8, 160), (59, 10.1, 200), (61, 10.2, 260)]]  # fmt: skip
    out = [b for x in t for b in agg.add(x)]
    assert out == [Bar("A", T0, 10.0, 10.5, 9.8, 10.1, 100.0)]  # first tick has no increment
    assert agg.add(Tick("A", T0 + timedelta(seconds=30), 99.0, 300)) == []  # out-of-order tick dropped
    assert agg.flush(T0 + timedelta(seconds=121)) == []  # grace not over for the 10:01 bar
    (b,) = agg.flush(T0 + timedelta(seconds=122))
    assert (b.ts, b.close, b.volume) == (T0 + timedelta(minutes=1), 10.2, 60.0)


def test_validator_rejects_bad_bars_by_reason():
    v = BarValidator({"A"})
    now = T0 + timedelta(minutes=1)
    good = Bar("A", T0, 10, 11, 9, 10.5, 100)
    assert v.check(Bar("B", T0, 10, 11, 9, 10, 1), now) == "UNKNOWN_SYMBOL"
    assert v.check(Bar("A", T0.replace(tzinfo=None), 10, 11, 9, 10, 1), now) == "NAIVE_TIMESTAMP"
    assert v.check(Bar("A", T0.replace(hour=16), 10, 11, 9, 10, 1), now) == "OUTSIDE_SESSION"
    assert v.check(Bar("A", T0 + timedelta(minutes=5), 10, 11, 9, 10, 1), now) == "FUTURE_TIMESTAMP"
    assert v.check(Bar("A", T0, 10, 11, -9, 10, 1), now) == "BAD_PRICE"
    assert v.check(Bar("A", T0, 10, 9, 9.5, 10, 1), now) == "BAD_OHLC"
    assert v.check(Bar("A", T0, 10, 11, 9, 10, float("nan")), now) == "BAD_VOLUME"
    assert v.accept(good, now)
    assert v.check(good, now) == "DUPLICATE"
    assert v.check(Bar("A", T0 - timedelta(minutes=1), 10, 11, 9, 10, 1), now) == "OUT_OF_SEQUENCE"
    assert not in_session(datetime(2025, 6, 14, 10, 0, tzinfo=IST))  # Saturday


def test_feed_states_never_live_without_a_fresh_real_feed():
    v = BarValidator({"A"})
    replay = FeedMonitor("replay", is_live=False, connected=True)
    assert replay.state(T0, v)[0] == FeedState.REPLAY
    live = FeedMonitor("kite", is_live=True)
    assert live.state(T0, v)[0] == FeedState.DISCONNECTED
    live.connected = True
    assert live.state(T0, v)[0] == FeedState.STALE  # connected, nothing received
    b = Bar("A", T0, 10, 11, 9, 10, 1)
    live.on_bar(b, b.close_ts + timedelta(seconds=1))
    assert live.state(b.close_ts + timedelta(seconds=2), v)[0] == FeedState.LIVE
    assert live.state(b.close_ts + timedelta(seconds=400), v)[0] == FeedState.STALE
    slow = FeedMonitor("kite", is_live=True, connected=True)
    slow.on_bar(b, b.close_ts + timedelta(seconds=120))
    assert slow.state(b.close_ts + timedelta(seconds=121), v)[0] == FeedState.DELAYED
    for _ in range(30):
        v.accept(Bar("ZZZ", T0, 1, 1, 1, 1, 1), T0)
    assert live.state(b.close_ts + timedelta(seconds=2), v)[0] == FeedState.INVALID


def test_cache_never_returns_bars_after_the_prediction_time():
    hist = pl.DataFrame({"symbol": ["A"], "ts": [T0 - timedelta(days=1)], "open": [1.0], "high": [1.0],
                         "low": [1.0], "close": [1.0], "volume": [1.0]}).with_columns(
        pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))  # fmt: skip
    c = BarCache(hist)
    for k in range(3):
        c.add(Bar("A", T0 + timedelta(minutes=k), 2, 2, 2, 2, 2))
    f = c.frame(["A"], T0 + timedelta(minutes=1))
    assert f.height == 3 and f["ts"].max() == T0 + timedelta(minutes=1)


# --- providers ----------------------------------------------------------------------------------
def test_mock_provider_is_test_only(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PULSETRADER_TESTING", raising=False)
    with pytest.raises(ProviderError, match="test-only"):
        MockProvider([])
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "mock")
    with pytest.raises(ProviderError, match="test-only"):
        provider_from_env(Path("."))


def test_replay_refuses_the_test_period(golden_dataset):
    periods = {p["name"]: p for p in json.loads(
        (golden_dataset / "datasets" / "ds" / "dataset_manifest.json").read_text())["periods"]}  # fmt: skip
    test_day = date.fromisoformat(periods["test"]["start"])
    with pytest.raises(ReservedPeriodError):
        HistoricalProvider(golden_dataset, test_day)
    assert HistoricalProvider(golden_dataset, test_day, allow_test=True).day == test_day
    snap = SnapshotProvider(golden_dataset).latest(["AAA"])
    assert snap["AAA"].ts.date() == date(2024, 1, 5)


@dataclass
class StubModel:
    """Records what inference receives (the real LoadedModel is covered by test_serve)."""

    features: list[str]
    feature_version: str = FEATURE_VERSION
    seen: list[dict[str, Any]] = field(default_factory=list)

    @property
    def record(self) -> Any:
        return type("R", (), {"key": "stub@v1"})()

    def predict(self, items: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
        self.seen += [{**it, "now": now} for it in items]
        n0 = len(self.seen) - len(items)
        out = []
        for i, it in enumerate(items):
            k = (n0 + i) % 3  # deterministic DOWN / NEUTRAL / UP calls
            direction = ("DOWN", "NEUTRAL", "UP")[k]
            pr = {c: 0.6 if j == k else 0.2 for j, c in enumerate(("down", "neutral", "up"))}
            ts = it["market_data_timestamp"]
            out.append({
                "prediction_id": f"stub-{it['symbol']}-{ts.isoformat()}",
                "model_id": "stub", "model_version": 1, "symbol": it["symbol"],
                "market_data_timestamp": ts.isoformat(), "prediction_horizon_minutes": 5,
                "direction": direction, "model_class": direction, "label_threshold": 0.001,
                "raw_probability": pr, "calibrated_probability": pr,
            })  # fmt: skip
        return out


def _research_rows(root, day):
    return (
        pl.scan_parquet(root / "datasets" / "ds" / "part-*.parquet")
        .filter(pl.col("trade_date") == day)
        .collect()
    )


def _assert_parity(live: pl.DataFrame, research: pl.DataFrame, feats: list[str]) -> None:
    j = live.select("symbol", "ts", *feats).join(research.select("symbol", "ts", *feats),
                                                 on=["symbol", "ts"], suffix="_r")  # fmt: skip
    assert j.height == research.height > 0
    for f in feats:
        a, b = j[f].cast(pl.Float64), j[f"{f}_r"].cast(pl.Float64)
        assert (a.is_null() == b.is_null()).all(), f
        diff = ((a - b).abs() / (b.abs() + 1)).drop_nulls().drop_nans()
        assert diff.len() == 0 or diff.max() < 1e-5, (f, diff.max())


def _validation_day(root) -> date:
    m = json.loads((root / "datasets" / "ds" / "dataset_manifest.json").read_text())
    return date.fromisoformat(next(p for p in m["periods"] if p["name"] == "validation")["start"])


def test_replay_pipeline_reproduces_research_features(golden_dataset):
    root = golden_dataset
    day = _validation_day(root)
    uni = LiveUniverse.from_manifest(root / "datasets" / "ds")
    feats = json.loads((root / "datasets" / "ds" / "features.json").read_text())["features"]
    model = StubModel(feats)
    sink = MemorySink()
    pipe = LivePipeline(HistoricalProvider(root, day), uni, [model], [sink],  # type: ignore[list-item]
                        PipelineConfig(keep_features=True))  # fmt: skip
    res = asyncio.run(pipe.run())
    assert res["mode"] == "REPLAY" and res["rejected"] == {}
    assert res["sampled"] == 75  # every 5th minute of a 375-bar session
    live = pl.concat(pipe.feature_frames, how="diagonal_relaxed")
    _assert_parity(live, _research_rows(root, day), feats)
    assert {p["mode"] for p in sink.preds} == {"REPLAY"}
    assert {p["feed_state"] for p in sink.preds} == {"REPLAY"}
    assert all(s["state"] != "LIVE" for s in sink.statuses)
    # inference sees the bar-close clock and only the model's features
    first = model.seen[0]
    assert first["now"] == first["market_data_timestamp"] + timedelta(minutes=1)
    assert set(first["features"]) == set(feats)


def test_mock_ticks_through_live_provider_match_research_features(golden_dataset):
    """Ticks -> candle aggregator -> validation -> cache -> features == research rows (feature parity)."""
    root = golden_dataset
    day = _validation_day(root)
    uni = LiveUniverse.from_manifest(root / "datasets" / "ds")
    replay = HistoricalProvider(root, day)
    history = replay.history(uni.symbols)
    bars = pl.concat(
        [
            pl.read_parquet(root / "canonical" / f"{s.replace(' ', '_')}.parquet").filter(
                pl.col("trade_date") == day
            )
            for s in uni.symbols
        ]  # fmt: skip
    ).sort("ts", "symbol")
    ticks: list[Tick] = []
    cum: dict[str, float] = {}
    for s, ts, o, h, lo, c, v in bars.select(
        "symbol", "ts", "open", "high", "low", "close", "volume"
    ).iter_rows():
        base = cum.get(s, 0.0)
        for sec, price, frac in ((0, o, 0.0), (15, h, 1 / 3), (30, lo, 2 / 3), (45, c, 1.0)):
            ticks.append(Tick(s, ts + timedelta(seconds=sec), price, base + frac * v))
        cum[s] = base + v
    ticks.sort(key=lambda t: t.ts)
    feats = json.loads((root / "datasets" / "ds" / "features.json").read_text())["features"]
    sink = MemorySink()
    prov = MockProvider(ticks, history)
    pipe = LivePipeline(prov, uni, [StubModel(feats)], [sink],  # type: ignore[list-item]
                        PipelineConfig(keep_features=True))  # fmt: skip
    res = asyncio.run(pipe.run())
    assert res["mode"] == "LIVE" and res["rejected"] == {}
    live = pl.concat(pipe.feature_frames, how="diagonal_relaxed")
    research = _research_rows(root, day)
    _assert_parity(live, research, feats)
    assert {p["mode"] for p in sink.preds} == {"LIVE"}


def test_feature_check_rejects_version_or_name_drift():
    check_features(["a", "b"], ["b"], FEATURE_VERSION, FEATURE_VERSION)
    with pytest.raises(FeatureMismatch):
        check_features(["a"], ["b"], FEATURE_VERSION, FEATURE_VERSION)
    with pytest.raises(FeatureMismatch):
        check_features(["a"], ["a"], FEATURE_VERSION, "features-v0")


def test_replay_outcomes_equal_research_labels_and_evaluate(golden_dataset):
    """Phase 18: each prediction's realised outcome equals the dataset label for the same row."""
    root = golden_dataset
    day = _validation_day(root)
    uni = LiveUniverse.from_manifest(root / "datasets" / "ds")
    feats = json.loads((root / "datasets" / "ds" / "features.json").read_text())["features"]
    sink = MemorySink()
    pipe = LivePipeline(HistoricalProvider(root, day), uni, [StubModel(feats)], [sink],  # type: ignore[list-item]
                        PipelineConfig())  # fmt: skip
    res = asyncio.run(pipe.run())
    assert res["outcomes"] == res["predictions"] == len(sink.outs) > 0
    assert not pipe.tracker.pending
    o = pl.DataFrame(sink.outs, infer_schema_length=None).with_columns(
        pl.col("market_data_timestamp").str.to_datetime(time_zone="Asia/Kolkata").alias("ts")
    )
    lab = label_name(5, 0.001)
    research = _research_rows(root, day).select("symbol", "ts", "fret_5", lab)
    j = o.join(research, on=["symbol", "ts"], how="inner")
    assert j.height == o.height
    want = j[lab].replace_strict({-1: "DOWN", 0: "NEUTRAL", 1: "UP"}, default=None)
    assert ((want == j["actual_class"]) | (want.is_null() & j["actual_class"].is_null())).all()
    assert (j["actual_return"].is_null() == j["fret_5"].is_null()).all()
    assert ((j["actual_return"] - j["fret_5"].cast(pl.Float64)).abs().drop_nulls() < 1e-6).all()
    # the last bars of the session have no bar 5 minutes later: no label, no correctness
    late = o.filter(pl.col("ts").dt.time() > time(15, 24))
    assert late.height and late["actual_class"].is_null().all() and late["direction_correct"].is_null().all()
    neutral = o.filter(pl.col("direction") == "NEUTRAL")
    assert neutral["direction_correct"].is_null().all()
    called = o.filter(pl.col("direction") != "NEUTRAL").drop_nulls("actual_class")
    assert (called["direction_correct"] == (called["direction"] == called["actual_class"])).all()

    (ev,) = evaluate(sink.outs)
    assert ev["mode"] == "REPLAY" and ev["predictions"] == o.height
    assert ev["evaluated"] == o.drop_nulls("actual_class").height
    sel = ev["selective"]
    assert sel["calls"] == called.height
    assert sel["coverage"] == pytest.approx(called.height / ev["evaluated"])
    assert sel["accuracy"] == pytest.approx(called["direction_correct"].cast(pl.Float64).mean())
    for key in ("accuracy", "balanced_accuracy", "mcc", "brier", "ece_top"):
        assert ev["full_coverage"][key] is not None
    assert ev["rolling"]["last_20"]["n"] == min(20, called.height)
    assert sum(d["calls"] for d in ev["daily"]) == called.height
    gross = called["actual_return"] * pl.Series([1.0 if d == "UP" else -1.0 for d in called["direction"]])
    assert ev["paper"]["mean_net_bp"] == pytest.approx(gross.mean() * 1e4 - round_trip_cost_bp())  # type: ignore[operator]


def test_round_trip_cost_matches_backtest_costs():
    assert 9.0 < round_trip_cost_bp() < 12.0
