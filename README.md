# geopronto-base
Bases oficiais públicas usadas pelo GeoPronto

Arquivos que a janela **«Confrontantes – base online»** do GeoPronto baixa quando precisa. São dados públicos dos órgãos, sem nenhuma alteração além do formato e do arredondamento descrito abaixo. Este repositório não tem licença própria: os dados continuam sendo dos órgãos de origem (Lei 14.129/2021, art. 29). SIGEF, CAR e Terras indígenas **não** ficam aqui, porque o programa consulta esses dados na hora, direto no Incra, no SICAR e na FUNAI.

## Camadas

| Camada | Arquivos | Órgão | De onde vem | Atualização |
|---|---|---|---|---|
| SNCI – Certificadas | `snci_<UF>.geojson.gz` | Incra | Acervo Fundiário → Exportar shapefile → «Imóvel certificado SNCI Total» | parada (certificações de 2004 a 2018) |
| Assentamentos | `assentamentos_<UF>.geojson.gz` | Incra | Acervo Fundiário → Exportar shapefile | todo mês |
| Áreas quilombolas | `quilombolas_<UF>.geojson.gz` | Incra | Acervo Fundiário → Exportar shapefile | todo mês |
| Unidades de conservação | `ucs_<UF>.geojson.gz` | ICMBio | `conservation_unit` | quando sair versão nova |
| Biomas | `biomas_BR.geojson.gz` | IBGE | `lml_bioma_e250k` (1:250.000) | quando sair versão nova |

## Formato

- **Divisão:** um arquivo por estado, em GeoJSON compactado em gzip. Biomas é um arquivo só (`BR`).
- **Coordenadas:** SIRGAS 2000 geográfico (EPSG:4674), arredondadas a **8 casas decimais** (1e-8 grau ≈ 1,1 mm, a mesma regra do SIGEF). O maior deslocamento é de meio milímetro.
- **Atributos:** exatamente como vêm no arquivo do órgão. Só as datas viram `AAAA-MM-DD`.
- **Polígono sem geometria no arquivo de origem:** fica de fora.
- **SNCI sem estado no campo `uf_municip`:** vai para `snci_SEM_UF.geojson.gz`.
- **UC em mais de um estado:** vai para o arquivo de cada estado (campo `state_name`). O programa junta pelo `campo_id` (`uc_id`).
- **Estado de cada polígono:** é o que o órgão escreveu no campo de estado (`uf_municip`, `uf`, `cd_uf`), e isso nem sempre é onde o polígono está. Exemplo: 205 assentamentos marcados `DF` ficam no Entorno, em GO e MG. Por isso **o programa escolhe os arquivos pelo `bbox` de cada arquivo no índice, e não pelo nome do estado.** Assim nenhum polígono fica de fora.

### `dados/indice.json`

O programa lê o índice primeiro e baixa só os arquivos cujo `bbox` encosta na área da tela.

```json
{
 "formato": 1, "crs": "EPSG:4674", "casas_decimais": 8, "gerado_em": "2026-10-05T21:47:24-03:00",
 "camadas": {
  "snci": {
   "titulo": "SNCI – Certificadas", "orgao": "Incra",
   "arquivo_origem": "Imóvel certificado SNCI Brasil.shp", "data_arquivo": "2026-10-05",
   "poligonos": 52784,
   "ufs": {"GO": {"arquivo": "snci_GO.geojson.gz", "poligonos": 5004, "bytes": 5146188,
                  "sha256": "…", "bbox": [-56.5, -24.02, -45.97, -12.79]}}
  }
 }
}
```

- `data_arquivo`: data do arquivo de dentro do zip, que no Acervo é o dia do download.
- `data_referencia`, quando existe, é a data que a janela mostra no lugar da `data_arquivo`. Hoje só as UCs têm, com `2025-09` («ICMBio 09/2025»). Ela fica no `gerar_base.py` e precisa ser trocada quando o arquivo das UCs mudar.
- `sha256`: o programa confere o arquivo baixado.

## Atualização do mês

1. No Acervo Fundiário, em **Exportar shapefile**, baixe **assentamentos** e **áreas quilombolas**, Brasil inteiro, sem escolher estado.
2. Ponha os zips numa pasta. Não precisa extrair. Exemplo: `C:\base_mensal`.
3. Na pasta deste repositório, rode:
   ```
   py -3.12 ferramentas\gerar_base.py C:\base_mensal
   ```
4. Confira a quantidade de polígonos que aparece na tela.
5. Suba a pasta `dados/` para o GitHub.

**Camada que não estiver na pasta continua como estava.** Por isso o SNCI, as UCs e os biomas não precisam ser baixados de novo. Arquivo que não mudou sai com os mesmos bytes, então não cria versão nova no GitHub.

## Trava

```
py -3.12 -m pytest tests
```
