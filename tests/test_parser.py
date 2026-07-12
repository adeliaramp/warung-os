from bot.parser import parse, parse_amount, parse_qty


# ---------------------------------------------------------------------------
# Amount parser
# ---------------------------------------------------------------------------


def test_parse_amount_rb():
    assert parse_amount("20rb") == 20_000


def test_parse_amount_ribu():
    assert parse_amount("50ribu") == 50_000


def test_parse_amount_k():
    assert parse_amount("5k") == 5_000


def test_parse_amount_plain():
    assert parse_amount("100000") == 100_000


def test_parse_amount_jt():
    assert parse_amount("1jt") == 1_000_000


# ---------------------------------------------------------------------------
# Quantity parser
# ---------------------------------------------------------------------------


def test_parse_qty_int():
    assert parse_qty("3") == 3.0


def test_parse_qty_decimal():
    assert parse_qty("3.5") == 3.5


def test_parse_qty_embedded():
    assert parse_qty("tahu 20") == 20.0


# ---------------------------------------------------------------------------
# Full message parser
# ---------------------------------------------------------------------------


def test_parse_sale_simple():
    intent = parse("indomie 3")
    assert intent["type"] == "sale"
    assert intent["sku_raw"] == "indomie"
    assert intent["qty"] == 3.0


def test_parse_sale_multiword():
    intent = parse("teh botol 2")
    assert intent["type"] == "sale"
    assert intent["sku_raw"] == "teh botol"
    assert intent["qty"] == 2.0


def test_parse_stock_keyword():
    intent = parse("stok tahu 20")
    assert intent["type"] == "stock"
    assert intent["sku_raw"] == "tahu"
    assert intent["qty"] == 20.0


def test_parse_stock_sisa():
    intent = parse("sisa indomie 5")
    assert intent["type"] == "stock"
    assert intent["qty"] == 5.0


def test_parse_command_start():
    intent = parse("/start")
    assert intent["type"] == "command"
    assert intent["name"] == "start"


def test_parse_command_help():
    intent = parse("/bantuan")
    assert intent["type"] == "command"
    assert intent["name"] == "bantuan"


def test_parse_unknown_no_number():
    intent = parse("apa kabar")
    assert intent["type"] == "unknown"


def test_parse_sale_decimal_qty():
    intent = parse("beras 2.5")
    assert intent["type"] == "sale"
    assert intent["qty"] == 2.5


# ---------------------------------------------------------------------------
# Kasbon and repayment parser
# ---------------------------------------------------------------------------


def test_parse_kasbon_simple():
    intent = parse("kasbon bu sri 20rb")
    assert intent["type"] == "kasbon"
    assert intent["customer_raw"] == "bu sri"
    assert intent["amount"] == 20_000


def test_parse_kasbon_ribu():
    intent = parse("utang pak budi 50ribu")
    assert intent["type"] == "kasbon"
    assert intent["amount"] == 50_000


def test_parse_repayment_partial():
    intent = parse("bayar bu sri 20rb")
    assert intent["type"] == "repayment"
    assert intent["customer_raw"] == "bu sri"
    assert intent["amount"] == 20_000


def test_parse_repayment_full_settlement():
    intent = parse("lunas bu sri")
    assert intent["type"] == "repayment"
    assert intent["customer_raw"] == "bu sri"
    assert intent["amount"] is None


def test_parse_kasbon_missing_amount():
    intent = parse("kasbon bu sri")
    assert intent["type"] == "unknown"
