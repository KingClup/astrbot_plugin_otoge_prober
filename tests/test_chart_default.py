from chart.commands import hardest, level_num
from chart.sdvxin import Entry


def E(game, levels):
    return Entry(game, "1", "t", "", {"levels": levels})


def test_chu_takes_ultima_or_master():
    assert hardest(E("chu", {"bsc": "_4", "adv": "_9+", "exp": "12+", "mst": "15", "ult": ""}), "chu") == "mst"
    assert hardest(E("chu", {"bsc": "3", "adv": "7", "exp": "11", "mst": "14", "ult": "14+"}), "chu") == "ult"
    assert hardest(E("chu", {"bsc": "3", "adv": "7", "exp": "11", "mst": "14+", "ult": "14+"}), "chu") == "ult"


def test_sdvx_and_pjsk():
    assert hardest(E("sdvx", {"nov": "_2", "adv": "_8", "exh": "16", "mxm": "h184"}), "sdvx") == "mxm"
    assert hardest(E("sdvx", {"nov": "_4", "adv": "_10", "exh": "15", "mxm": ""}), "sdvx") == "exh"
    assert hardest(E("pjsk", {"esy": "_10", "nml": "_16", "hrd": "_25", "exp": "32", "mst": "35", "apd": "38"}), "pjsk") == "mst"
    assert hardest(E("pjsk", {"esy": "_5", "nml": "_13", "hrd": "_18", "exp": "25", "mst": "30", "apd": "_"}), "pjsk") == "mst"
    assert level_num(E("sdvx", {"mxm": "h184"}), "mxm") == 18.4


def test_pjsk_without_master_takes_hardest():
    assert hardest(E("pjsk", {"esy": "5", "nml": "10", "hrd": "16", "exp": "22", "mst": "", "apd": "25"}), "pjsk") == "apd"
