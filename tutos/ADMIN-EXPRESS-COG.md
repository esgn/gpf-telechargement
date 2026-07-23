Extraction des communes du département de la Nièvre (58), par filtre sur le code INSEE du département.

## DuckDB

```sql
INSTALL httpfs; LOAD httpfs;

SELECT *
FROM read_parquet('https://data.geopf.fr/chunk/telechargement/download/ADMIN-EXPRESS-COG-PARTIEL/ADMIN-EXPRESS-COG_4-0__GEOPARQUET_WGS84G_FRA_2026-01-01/commune.parquet')
WHERE code_insee_du_departement = '58';
```

## GDAL GeoParquet

```bash
# Installation avec conda:
# > conda create --name gdal-parquet
# > conda install -c conda-forge gdal libgdal-arrow-parquet libgdal-adbc

ogr2ogr communes_pqt.gpkg \
  /vsicurl/https://data.geopf.fr/chunk/telechargement/download/ADMIN-EXPRESS-COG-PARTIEL/ADMIN-EXPRESS-COG_4-0__GEOPARQUET_WGS84G_FRA_2026-01-01/commune.parquet \
  -where "code_insee_du_departement = '58'"
```

## GDAL FlatGeoBuf

```bash
ogr2ogr communes_fgb.gpkg \
  "/vsicurl/https://data.geopf.fr/chunk/telechargement/download/ADMIN-EXPRESS-COG-PARTIEL/ADMIN-EXPRESS-COG_4-0__FLATGEOBUF_WGS84G_FRA_2026-01-01/commune.fgb" \
  -where "code_insee_du_departement = '58'"
```
