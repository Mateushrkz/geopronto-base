# -*- coding: utf-8 -*-
"""Gera os arquivos da base online do GeoPronto a partir dos zips oficiais.

Uso (no Windows, na pasta do repositório):

    py -3.12 ferramentas\\gerar_base.py C:\\caminho\\da\\pasta_com_os_zips

A pasta de entrada pode ter os zips como foram baixados ou os shapefiles já
extraídos. Cada camada é reconhecida pelo nome do .shp:

    SNCI            «Imóvel certificado SNCI Brasil»   (Incra – Acervo Fundiário)
    Assentamentos   «Assentamento Brasil»              (Incra – Acervo Fundiário)
    Quilombolas     «Áreas de Quilombolas»             (Incra – Acervo Fundiário)
    UCs             «conservation_unit»                (ICMBio)
    Biomas          «lml_bioma_e250k_…»                (IBGE)

Camada que não estiver na pasta fica como estava no índice — no mês a mês
basta pôr na pasta só o que foi baixado de novo (assentamentos e quilombolas).

Saída em ``dados/`` (ou ``--saida``):
    <camada>_<UF>.geojson.gz   uma por estado (biomas: um arquivo só, ``BR``)
    indice.json                o que existe, quantos polígonos, data e sha256

Regras:
    * coordenadas em SIRGAS 2000 geográfico, como vêm do órgão, arredondadas a
      8 casas decimais (1e-8 grau ≈ 1,1 mm — a mesma regra do SIGEF);
    * atributos exatamente como vêm no arquivo (só datas viram AAAA-MM-DD);
    * gzip sem data dentro: arquivo igual gera bytes iguais, então mês sem
      mudança não cria versão nova no GitHub.

Só depende do ``pyshp`` (já instalado com o GeoPronto) e da biblioteca padrão.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import io
import json
import os
import sys
import unicodedata
import zipfile

import shapefile  # pyshp

FORMATO = 1
CASAS = 8

UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO")

NOME_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAZONAS": "AM", "AMAPA": "AP", "BAHIA": "BA",
    "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
    "MARANHAO": "MA", "MINAS GERAIS": "MG", "MATO GROSSO DO SUL": "MS",
    "MATO GROSSO": "MT", "PARA": "PA", "PARAIBA": "PB", "PERNAMBUCO": "PE",
    "PIAUI": "PI", "PARANA": "PR", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RONDONIA": "RO", "RORAIMA": "RR", "RIO GRANDE DO SUL": "RS",
    "SANTA CATARINA": "SC", "SERGIPE": "SE", "SAO PAULO": "SP", "TOCANTINS": "TO",
}

SEM_UF = "SEM_UF"
NACIONAL = "BR"


def _sem_acento(txt: str) -> str:
    n = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in n if not unicodedata.combining(c)).upper().strip()


def _uf_campo(campo: str):
    """UF a partir de um campo com a sigla (SNCI, assentamentos, quilombolas)."""
    def achar(rec: dict):
        uf = str(rec.get(campo) or "").strip().upper()
        return [uf] if uf in UFS else [SEM_UF]
    return achar


def _uf_nomes(campo: str):
    """UFs a partir de nomes por extenso separados por vírgula (UCs)."""
    def achar(rec: dict):
        ufs = []
        for parte in str(rec.get(campo) or "").split(","):
            uf = NOME_UF.get(_sem_acento(parte))
            if uf and uf not in ufs:
                ufs.append(uf)
        return ufs or [SEM_UF]
    return achar


def _nacional(_rec: dict):
    return [NACIONAL]


# chave: nome da camada nos arquivos; "achar": palavra que identifica o .shp
CAMADAS = {
    "snci": {"achar": "snci", "titulo": "SNCI – Certificadas", "orgao": "Incra",
             "uf": _uf_campo("uf_municip")},
    "assentamentos": {"achar": "assentamento", "titulo": "Assentamentos", "orgao": "Incra",
                      "uf": _uf_campo("uf")},
    "quilombolas": {"achar": "quilombola", "titulo": "Áreas quilombolas", "orgao": "Incra",
                    "uf": _uf_campo("cd_uf")},
    # data_referencia: a data que a janela mostra («ICMBio 09/2025»), decidida
    # por Mateus em 05/10/2026 — trocar aqui quando trocar o arquivo das UCs
    "ucs": {"achar": "conservation_unit", "titulo": "Unidades de conservação", "orgao": "ICMBio",
            "uf": _uf_nomes("state_name"), "campo_id": "uc_id", "data_referencia": "2025-09"},
    "biomas": {"achar": "bioma", "titulo": "Biomas", "orgao": "IBGE", "uf": _nacional},
}


# ----------------------------------------------------------------- leitura
class Fonte:
    """Um shapefile encontrado na entrada (dentro de zip ou solto)."""

    def __init__(self, nome_shp: str, abrir, data: _dt.date, cpg: str | None):
        self.nome_shp = nome_shp          # nome do .shp, sem pasta
        self._abrir = abrir               # extensão -> bytes (ou None)
        self.data = data                  # data do arquivo (dentro do zip)
        self.cpg = cpg

    def leitor(self) -> shapefile.Reader:
        enc = (self.cpg or "").strip() or "cp1252"   # Acervo do Incra vem sem .cpg, em cp1252
        partes = {ext: self._abrir(ext) for ext in ("shp", "shx", "dbf")}
        if partes["shp"] is None or partes["dbf"] is None:
            raise ValueError("faltou .shp ou .dbf de %s" % self.nome_shp)
        return shapefile.Reader(shp=io.BytesIO(partes["shp"]),
                                shx=io.BytesIO(partes["shx"]) if partes["shx"] else None,
                                dbf=io.BytesIO(partes["dbf"]), encoding=enc)


def _fontes_do_zip(caminho: str):
    z = zipfile.ZipFile(caminho)
    nomes = {n.lower(): n for n in z.namelist()}
    for n in z.namelist():
        if not n.lower().endswith(".shp"):
            continue
        base = n[:-4]
        info = z.getinfo(n)
        cpg = nomes.get((base + ".cpg").lower())
        cpg_txt = z.read(cpg).decode("ascii", "ignore") if cpg else None

        def abrir(ext, base=base):
            real = nomes.get((base + "." + ext).lower())
            return z.read(real) if real else None
        yield Fonte(os.path.basename(n), abrir, _dt.date(*info.date_time[:3]), cpg_txt)


def _fontes_soltas(pasta: str, arquivos):
    por_nome = {a.lower(): a for a in arquivos}
    for a in arquivos:
        if not a.lower().endswith(".shp"):
            continue
        base = a[:-4]
        cpg = por_nome.get((base + ".cpg").lower())
        cpg_txt = open(os.path.join(pasta, cpg), "rb").read().decode("ascii", "ignore") if cpg else None
        data = _dt.date.fromtimestamp(os.path.getmtime(os.path.join(pasta, a)))

        def abrir(ext, base=base):
            real = por_nome.get((base + "." + ext).lower())
            if not real:
                return None
            with open(os.path.join(pasta, real), "rb") as f:
                return f.read()
        yield Fonte(a, abrir, data, cpg_txt)


def encontrar_fontes(entrada: str) -> dict:
    """camada -> Fonte, procurando zips e shapefiles soltos na pasta (e subpastas)."""
    achadas = {}
    for pasta, _dirs, arquivos in os.walk(entrada):
        candidatos = list(_fontes_soltas(pasta, arquivos))
        for a in arquivos:
            if a.lower().endswith(".zip"):
                candidatos.extend(_fontes_do_zip(os.path.join(pasta, a)))
        for f in candidatos:
            nome = _sem_acento(f.nome_shp).lower()
            for camada, cfg in CAMADAS.items():
                if cfg["achar"] in nome:
                    if camada in achadas:
                        raise ValueError("camada %s encontrada duas vezes: %s e %s"
                                         % (camada, achadas[camada].nome_shp, f.nome_shp))
                    achadas[camada] = f
    return achadas


# ----------------------------------------------------------------- conversão
def _arredondar(coords):
    if isinstance(coords, (int, float)):
        return round(float(coords), CASAS)
    return [_arredondar(c) for c in coords]


def _valor(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()[:10]
    if isinstance(v, bytes):
        return v.decode("latin-1")
    return v


def _feicao(shape, rec: dict):
    geo = shape.__geo_interface__
    geometria = {"type": geo["type"], "coordinates": _arredondar(geo["coordinates"])}
    props = {k: _valor(v) for k, v in rec.items()}
    return {"type": "Feature", "properties": props, "geometry": geometria}


def _bbox(feicoes):
    xs, ys = [], []
    for f in feicoes:
        def andar(c):
            if c and isinstance(c[0], (int, float)):
                xs.append(c[0]); ys.append(c[1])
            else:
                for x in c:
                    andar(x)
        andar(f["geometry"]["coordinates"])
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _gravar_gz(caminho: str, obj) -> bytes:
    bruto = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as g:
        g.write(bruto)
    dados = buf.getvalue()
    with open(caminho, "wb") as f:
        f.write(dados)
    return dados


def gerar_camada(camada: str, fonte: Fonte, saida: str) -> dict:
    cfg = CAMADAS[camada]
    r = fonte.leitor()
    por_uf: dict[str, list] = {}
    total = 0
    for sr in r.iterShapeRecords():
        if sr.shape.shapeType == shapefile.NULL or not sr.shape.points:
            continue
        rec = sr.record.as_dict()
        feicao = _feicao(sr.shape, rec)
        total += 1
        for uf in cfg["uf"](rec):
            por_uf.setdefault(uf, []).append(feicao)

    # apaga arquivos antigos desta camada que não serão regravados
    novos = {"%s_%s.geojson.gz" % (camada, uf) for uf in por_uf}
    for a in os.listdir(saida):
        if a.startswith(camada + "_") and a.endswith(".geojson.gz") and a not in novos:
            os.remove(os.path.join(saida, a))

    arquivos = {}
    for uf in sorted(por_uf):
        nome = "%s_%s.geojson.gz" % (camada, uf)
        fc = {"type": "FeatureCollection", "features": por_uf[uf]}
        dados = _gravar_gz(os.path.join(saida, nome), fc)
        arquivos[uf] = {"arquivo": nome, "poligonos": len(por_uf[uf]), "bytes": len(dados),
                        "sha256": hashlib.sha256(dados).hexdigest(), "bbox": _bbox(por_uf[uf])}
    entrada = {"titulo": cfg["titulo"], "orgao": cfg["orgao"], "arquivo_origem": fonte.nome_shp,
               "data_arquivo": fonte.data.isoformat(), "poligonos": total, "ufs": arquivos}
    if cfg.get("campo_id"):
        entrada["campo_id"] = cfg["campo_id"]
    if cfg.get("data_referencia"):
        entrada["data_referencia"] = cfg["data_referencia"]
    return entrada


def gerar(entrada: str, saida: str, agora: str | None = None, log=print) -> dict:
    os.makedirs(saida, exist_ok=True)
    caminho_indice = os.path.join(saida, "indice.json")
    indice = {"formato": FORMATO, "casas_decimais": CASAS, "crs": "EPSG:4674", "camadas": {}}
    if os.path.exists(caminho_indice):
        with open(caminho_indice, encoding="utf-8") as f:
            antigo = json.load(f)
        indice["camadas"].update(antigo.get("camadas", {}))

    fontes = encontrar_fontes(entrada)
    if not fontes:
        raise SystemExit("Nenhuma camada reconhecida em %s" % entrada)
    for camada in CAMADAS:
        if camada not in fontes:
            log("  %-14s não veio na pasta — mantida como estava" % camada)
            continue
        log("  %-14s lendo %s ..." % (camada, fontes[camada].nome_shp))
        indice["camadas"][camada] = gerar_camada(camada, fontes[camada], saida)
        c = indice["camadas"][camada]
        log("  %-14s %d polígonos em %d arquivo(s)" % (camada, c["poligonos"], len(c["ufs"])))

    indice["gerado_em"] = agora or _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(caminho_indice, "w", encoding="utf-8", newline="\n") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return indice


def main(argv=None):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Gera a base online do GeoPronto a partir dos zips oficiais.")
    p.add_argument("entrada", help="pasta com os zips baixados (ou shapefiles extraídos)")
    p.add_argument("--saida", default=os.path.join(raiz, "dados"), help="pasta de saída (padrão: dados/)")
    a = p.parse_args(argv)
    print("Gerando a base em %s" % a.saida)
    gerar(a.entrada, a.saida)
    print("Pronto.")


if __name__ == "__main__":
    sys.exit(main())
