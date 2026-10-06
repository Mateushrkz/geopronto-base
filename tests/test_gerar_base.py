# -*- coding: utf-8 -*-
"""Trava do gerador da base online (ferramentas/gerar_base.py).

Monta shapefiles pequenos, zipados como o Acervo do Incra e o ICMBio entregam,
e confere: divisão por estado, UC em dois estados indo para os dois, 8 casas
decimais, acento em cp1252, índice com contagem/sha256/data, gzip
determinístico, camada ausente preservada e arquivo de estado antigo apagado.
"""
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sys
import zipfile

import pytest
import shapefile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ferramentas"))
import gerar_base as gb  # noqa: E402

DATA_ZIP = (2026, 10, 5, 14, 51, 56)


def _quadrado(x, y, lado=0.01):
    return [[[x, y], [x, y + lado], [x + lado, y + lado], [x + lado, y], [x, y]]]


def _zip_shapefile(caminho_zip, nome_base, campos, linhas, encoding):
    """linhas = [(anel, {campo: valor})]; grava .shp/.shx/.dbf no zip, sem .cpg."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding=encoding)
    for nome, tipo, tam, dec in campos:
        w.field(nome, tipo, size=tam, decimal=dec)
    for anel, valores in linhas:
        w.poly(anel)
        w.record(**valores)
    w.close()
    with zipfile.ZipFile(caminho_zip, "w") as z:
        for ext, buf in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            info = zipfile.ZipInfo("%s.%s" % (nome_base, ext), date_time=DATA_ZIP)
            z.writestr(info, buf.getvalue())


def _snci(pasta, ufs=("GO", "GO", "MG")):
    linhas = []
    for i, uf in enumerate(ufs):
        anel = _quadrado(-49.123456789123 - i, -16.987654321987)
        linhas.append((anel, {"num_certif": "C%d" % i, "nome_imove": "FAZENDA SÃO JOÃO %d" % i,
                              "data_certi": dt.date(2012, 3, 4), "uf_municip": uf}))
    _zip_shapefile(os.path.join(pasta, "Imóvel_certificado_SNCI_Brasil.zip"), "Imóvel certificado SNCI Brasil",
                   [("num_certif", "C", 20, 0), ("nome_imove", "C", 60, 0), ("data_certi", "D", 8, 0),
                    ("uf_municip", "C", 2, 0)], linhas, "cp1252")


def _ucs(pasta):
    linhas = [(_quadrado(-49.5, -16.5), {"uc_id": "10", "name": "PARQUE A", "state_name": "GOIÁS"}),
              (_quadrado(-47.5, -15.9), {"uc_id": "11", "name": "APA B", "state_name": "MINAS GERAIS, GOIÁS"})]
    _zip_shapefile(os.path.join(pasta, "uc.zip"), "conservation_unit",
                   [("uc_id", "C", 10, 0), ("name", "C", 60, 0), ("state_name", "C", 80, 0)], linhas, "cp1252")


def _ler(saida, nome):
    with gzip.open(os.path.join(saida, nome), "rt", encoding="utf-8") as f:
        return json.load(f)


def _indice(saida):
    with open(os.path.join(saida, "indice.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def pastas(tmp_path):
    entrada, saida = tmp_path / "entrada", tmp_path / "dados"
    entrada.mkdir()
    return str(entrada), str(saida)


def test_divide_por_estado_e_arredonda_8_casas(pastas):
    entrada, saida = pastas
    _snci(entrada)
    gb.gerar(entrada, saida, agora="2026-10-05T21:00:00-03:00", log=lambda *a: None)
    go = _ler(saida, "snci_GO.geojson.gz")
    mg = _ler(saida, "snci_MG.geojson.gz")
    assert len(go["features"]) == 2 and len(mg["features"]) == 1
    x, y = go["features"][0]["geometry"]["coordinates"][0][0]
    assert x == round(-49.123456789123, 8) and y == round(-16.987654321987, 8)
    assert len(repr(x).split(".")[1]) <= 8
    props = go["features"][0]["properties"]
    assert props["nome_imove"] == "FAZENDA SÃO JOÃO 0"      # acento do cp1252 preservado
    assert props["data_certi"] == "2012-03-04"              # data vira AAAA-MM-DD


def test_uc_em_dois_estados_vai_para_os_dois(pastas):
    entrada, saida = pastas
    _ucs(entrada)
    gb.gerar(entrada, saida, agora="x", log=lambda *a: None)
    go = _ler(saida, "ucs_GO.geojson.gz")
    mg = _ler(saida, "ucs_MG.geojson.gz")
    assert sorted(f["properties"]["uc_id"] for f in go["features"]) == ["10", "11"]
    assert [f["properties"]["uc_id"] for f in mg["features"]] == ["11"]
    ind = _indice(saida)["camadas"]["ucs"]
    assert ind["campo_id"] == "uc_id" and ind["poligonos"] == 2   # 2 UCs, mesmo aparecendo 3 vezes


def test_indice_confere_com_os_arquivos(pastas):
    entrada, saida = pastas
    _snci(entrada)
    gb.gerar(entrada, saida, agora="2026-10-05T21:00:00-03:00", log=lambda *a: None)
    ind = _indice(saida)
    assert ind["formato"] == gb.FORMATO and ind["casas_decimais"] == 8 and ind["crs"] == "EPSG:4674"
    c = ind["camadas"]["snci"]
    assert c["poligonos"] == 3 and sorted(c["ufs"]) == ["GO", "MG"]
    assert c["data_arquivo"] == "2026-10-05"                 # data de dentro do zip
    for uf, info in c["ufs"].items():
        bruto = open(os.path.join(saida, info["arquivo"]), "rb").read()
        assert info["bytes"] == len(bruto)
        assert info["sha256"] == hashlib.sha256(bruto).hexdigest()
        minx, miny, maxx, maxy = info["bbox"]
        assert minx < maxx and miny < maxy


def test_mesmo_dado_gera_mesmos_bytes(pastas):
    entrada, saida = pastas
    _snci(entrada)
    gb.gerar(entrada, saida, agora="a", log=lambda *a: None)
    antes = open(os.path.join(saida, "snci_GO.geojson.gz"), "rb").read()
    gb.gerar(entrada, saida, agora="b", log=lambda *a: None)
    assert open(os.path.join(saida, "snci_GO.geojson.gz"), "rb").read() == antes


def test_camada_ausente_fica_como_estava(pastas, tmp_path):
    entrada, saida = pastas
    _snci(entrada)
    gb.gerar(entrada, saida, agora="a", log=lambda *a: None)
    so_uc = tmp_path / "so_uc"
    so_uc.mkdir()
    _ucs(str(so_uc))
    gb.gerar(str(so_uc), saida, agora="b", log=lambda *a: None)
    ind = _indice(saida)["camadas"]
    assert "snci" in ind and "ucs" in ind
    assert os.path.exists(os.path.join(saida, "snci_GO.geojson.gz"))


def test_estado_que_sumiu_tem_o_arquivo_apagado(pastas, tmp_path):
    entrada, saida = pastas
    _snci(entrada)
    gb.gerar(entrada, saida, agora="a", log=lambda *a: None)
    so_go = tmp_path / "so_go"
    so_go.mkdir()
    _snci(str(so_go), ufs=("GO",))
    gb.gerar(str(so_go), saida, agora="b", log=lambda *a: None)
    assert not os.path.exists(os.path.join(saida, "snci_MG.geojson.gz"))
    assert sorted(_indice(saida)["camadas"]["snci"]["ufs"]) == ["GO"]


def test_camada_repetida_na_pasta_para_com_erro(pastas):
    entrada, saida = pastas
    _snci(entrada)
    os.makedirs(os.path.join(entrada, "copia"))
    _snci(os.path.join(entrada, "copia"))
    with pytest.raises(ValueError):
        gb.gerar(entrada, saida, agora="a", log=lambda *a: None)
