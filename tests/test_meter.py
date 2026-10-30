"""Lane 2: transport-level cost meter + model column discipline (AM-5).

The meter prices calls from token counts at the transport boundary —
never from a worker's self-reported cost_usd (advisory only) — and
splits spend by lane so the burn audit can read canonical spend
against the canonical ceiling (AM-9vi $40 target; EA-5 $60 hard stop).
"""
from chancellor import api_client
from chancellor.api_client import ChatMessage, ChatResponse, MetaModelClient


def _fixed_transport(prompt_tokens, completion_tokens, reported_cost=None):
    def transport(model, messages, **kwargs):
        usage = {"prompt_tokens": prompt_tokens,
                 "completion_tokens": completion_tokens}
        if reported_cost is not None:
            usage["cost_usd"] = reported_cost
        return ChatResponse(text="ok", model=model, usage=usage)
    return transport


def _client(transport):
    return MetaModelClient(base_url="", api_key="", transport=transport)


def test_meter_prices_spark_from_tokens():
    client = _client(_fixed_transport(1_000_000, 1_000_000))
    client.chat(api_client.MUSE_SPARK, [ChatMessage("user", "hi")])
    # 1M in x $1.25 + 1M out x $4.25 (Scout 1 Standard prices)
    assert client.meter.canonical_spend() == 5.50
    assert client.meter.total_cost() == 5.50


def test_meter_prices_wonder_from_tokens():
    client = _client(_fixed_transport(1_000_000, 1_000_000))
    client.chat(api_client.MUSE_WONDER, [ChatMessage("user", "hi")])
    # 1M in x $4.00 + 1M out x $20.00
    assert client.meter.canonical_spend() == 24.00


def test_worker_reported_cost_is_advisory_only():
    # Transport claims the call cost $999; tokens say $5.50. Meter: $5.50.
    client = _client(_fixed_transport(1_000_000, 1_000_000,
                                      reported_cost=999.0))
    client.chat(api_client.MUSE_SPARK, [ChatMessage("user", "hi")])
    entry = client.meter.entries[0]
    assert entry.cost_usd == 5.50
    assert entry.advisory_cost_usd == 999.0
    assert client.meter.canonical_spend() == 5.50


def test_lanes_split_and_ceiling_reads_canonical_only():
    meter = api_client.CostMeter()
    client = MetaModelClient(base_url="", api_key="",
                             transport=_fixed_transport(1_000_000, 1_000_000),
                             meter=meter)
    client.chat(api_client.MUSE_SPARK, [ChatMessage("user", "a")])
    client.chat(api_client.MUSE_SPARK_CONTRIBUTOR, [ChatMessage("user", "b")])
    client.chat(api_client.MUSE_GLIMMER, [ChatMessage("user", "c")])

    lanes = meter.per_lane_totals()
    assert lanes["canonical"]["cost_usd"] == 5.50
    assert lanes["contributor"]["cost_usd"] == 0.30  # 0.10 in + 0.20 out
    assert lanes["nvidia"]["cost_usd"] == 0.0        # free trial endpoint
    assert lanes["nvidia"]["prompt_tokens"] == 1_000_000

    status = meter.ceiling_status()
    assert status["ceiling_usd"] == 60.0
    assert status["canonical_spend_usd"] == 5.50
    assert status["remaining_usd"] == 54.50
    assert status["exceeded"] is False


def test_ceiling_exceeded_flag():
    meter = api_client.CostMeter()
    meter.record(api_client.MUSE_WONDER,
                 {"prompt_tokens": 0, "completion_tokens": 4_000_000})
    status = meter.ceiling_status()  # 4M out x $20 = $80 > $60 hard stop
    assert status["canonical_spend_usd"] == 80.0
    assert status["exceeded"] is True


def test_unpriced_model_is_flagged_not_zeroed():
    meter = api_client.CostMeter()
    entry = meter.record("muse-image-1.0",
                         {"prompt_tokens": 10, "completion_tokens": 10})
    assert entry.cost_usd is None  # no price row: unknown, NOT free
    assert meter.unpriced_calls == 1
    assert meter.ceiling_status()["unpriced_calls"] == 1


def test_fake_transport_meters_zero_on_fake_lane():
    client = api_client.offline_client()
    client.chat(api_client.MUSE_SPARK, [ChatMessage("user", "ping")])
    entry = client.meter.entries[0]
    assert entry.lane == "fake"
    assert entry.cost_usd == 0.0
    assert client.meter.canonical_spend() == 0.0


def test_model_column_is_versioned_only():
    assert api_client.MUSE_SPARK == "muse-spark-1.3"
    assert api_client.MUSE_WONDER == "muse-wonder-1.0"
    assert api_client.MUSE_IMAGE == "muse-image-1.0"
    assert api_client.SAM_3_1 == "sam-3.1"
    assert api_client.MUSE_GLIMMER == "meta/muse-glimmer-30b"
    # AM-5: Wonder Full is not an API model; the constant must not exist.
    assert not hasattr(api_client, "MUSE_WONDER_FULL")
    for model_id in api_client.MODEL_IDS:
        assert model_id in api_client.PRICE_TABLE or \
            model_id in (api_client.MUSE_IMAGE, api_client.SAM_3_1)
