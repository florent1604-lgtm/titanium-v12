from tools import asset_optimizer


def test_axi_row_categories_are_included_in_the_optimizer_universe():
    assert {
        "ROW_STANDARD_FX",
        "ROW_CRYPTO",
        "ROW_STANDARD_METALS",
        "ROW_CASH",
        "ROW_FUTURES",
    } <= asset_optimizer.KEEP_CATS
