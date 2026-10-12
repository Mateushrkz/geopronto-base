# -*- coding: utf-8 -*-
"""Gera a camada «bacias» do geopronto-base a partir do micro_RH do IBGE
(DHN250, 2021). Um arquivo por MESORREGIÃO (54), cada um com as micros dela.

    python gerar_bacias.py <pasta com micro_RH.shp> <indice_publicado.json> <saida>

Saída: <saida>/dados/bacias_<cd_meso>.geojson.gz, <saida>/dados/indice.json
(o publicado + a camada nova) e <saida>/relatorio_bacias.txt.
Campos curtos: cd (cd_microRH), micro, meso, macro, area (km², IBGE).
"""
import gzip
import hashlib
import json
import os
import sys
import time
from collections import defaultdict

import shapefile
import shapely
from shapely.geometry import mapping, shape

TOL = 0.0002            # ~22 m: invisível na escala 1:250.000 (pontos do IBGE a ~99 m)
CASAS = 6


def arred(c):
    if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
        return [round(c[0], CASAS), round(c[1], CASAS)]
    return [arred(x) for x in c]


def main(pasta, publicado, saida):
    t0 = time.time()
    r = shapefile.Reader(os.path.join(pasta, "micro_RH.shp"), encoding="utf-8")
    geoms, recs = [], []
    for sr in r.iterShapeRecords():
        geoms.append(shape(sr.shape.__geo_interface__))
        recs.append(sr.record.as_dict())
    n_orig = sum(len(shapely.get_coordinates(g)) for g in geoms)
    # simplificação de COBERTURA: a divisa comum de duas bacias continua a
    # mesma linha nas duas (sem fresta nem sobreposição entre vizinhas)
    simp = list(shapely.coverage_simplify(geoms, TOL))
    invalidas = 0
    for i, g in enumerate(simp):
        if not g.is_valid:
            invalidas += 1
            simp[i] = g.buffer(0)
    n_simp = sum(len(shapely.get_coordinates(g)) for g in simp)

    por_meso = defaultdict(list)
    for g, rc in zip(simp, recs):
        por_meso[rc["cd_mesoRH"]].append({
            "type": "Feature",
            "properties": {"cd": rc["cd_microRH"], "micro": rc["nm_microRH"],
                           "meso": rc["nm_mesoRH"], "macro": rc["nm_macroRH"],
                           "area": round(float(rc["area"]), 1)},
            "geometry": {"type": g.geom_type, "coordinates": arred(mapping(g)["coordinates"])}})

    dados = os.path.join(saida, "dados")
    os.makedirs(dados, exist_ok=True)
    ufs, tamanhos = {}, []
    for cd in sorted(por_meso):
        feats = por_meso[cd]
        fc = {"type": "FeatureCollection", "features": feats}
        corpo = gzip.compress(json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                              mtime=0)
        nome = "bacias_%s.geojson.gz" % cd
        with open(os.path.join(dados, nome), "wb") as f:
            f.write(corpo)
        b = shapely.total_bounds([shape(x["geometry"]) for x in feats])
        ufs[cd] = {"arquivo": nome, "sha256": hashlib.sha256(corpo).hexdigest(),
                   "bbox": [round(float(v), CASAS) for v in b], "n": len(feats)}
        tamanhos.append((len(corpo), cd, feats[0]["properties"]["meso"], len(feats)))

    with open(publicado, encoding="utf-8") as f:
        ind = json.load(f)
    ind["camadas"]["bacias"] = {
        "orgao": "IBGE", "titulo": "Bacias hidrográficas", "campo_id": "cd",
        "data_referencia": "2021", "data_arquivo": "2021-09-22",
        "arquivo_origem": "micro_RH.shp", "fonte": "IBGE – DHN250 (2021)",
        "poligonos": len(recs), "ufs": ufs}
    with open(os.path.join(dados, "indice.json"), "w", encoding="utf-8") as f:
        json.dump(ind, f, ensure_ascii=False, indent=1, sort_keys=False)

    tamanhos.sort(reverse=True)
    total = sum(t for t, *_ in tamanhos)
    linhas = [
        "Arquivo do IBGE: micro_RH.shp (DHN250, 2021)",
        "Microrregiões: %d   mesorregiões (arquivos): %d   macrorregiões: %d"
        % (len(recs), len(por_meso), len({rc["cd_macroRH"] for rc in recs})),
        "Pontos: %d no original -> %d simplificado (tolerância %.4f°, ~%d m)"
        % (n_orig, n_simp, TOL, TOL * 111000),
        "Polígonos que precisaram de conserto depois de simplificar: %d" % invalidas,
        "TAMANHO TOTAL (compactado): %.1f MB" % (total / 1e6),
        "Maior arquivo: %.2f MB   médio: %.2f MB" % (tamanhos[0][0] / 1e6, total / len(tamanhos) / 1e6),
        "Os 5 maiores:",
    ] + ["  bacias_%s  %.2f MB  (%s, %d micros)" % (cd, t / 1e6, nm, n) for t, cd, nm, n in tamanhos[:5]] + [
        "Tempo: %d s" % (time.time() - t0)]
    with open(os.path.join(saida, "relatorio_bacias.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    print("\n".join(linhas))


if __name__ == "__main__":
    main(*sys.argv[1:4])
