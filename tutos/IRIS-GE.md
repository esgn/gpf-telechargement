Extraction des îlots IRIS sur la boite englobante du département de la Nièvre.

## DuckDB

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT *
FROM read_parquet('https://data.geopf.fr/chunk/telechargement/download/IRIS-GE-PARTIEL/IRIS-GE_3-0__GEOPARQUET_WGS84G_FRA_2026-01-01/iris.parquet')
WHERE ST_Within(geometrie, ST_MakeEnvelope(2.8, 46.6, 4.2, 47.6));
```

## GDAL GeoParquet

```bash
# Installation avec conda:
# > conda create --name gdal-parquet
# > conda install -c conda-forge gdal libgdal-arrow-parquet libgdal-adbc

ogr2ogr iris_pqt.gpkg \
  /vsicurl/https://data.geopf.fr/chunk/telechargement/download/IRIS-GE-PARTIEL/IRIS-GE_3-0__GEOPARQUET_WGS84G_FRA_2026-01-01/iris.parquet \
  -spat 2.8 46.6 4.2 47.6
```

## GDAL FlatGeoBuf

```bash
ogr2ogr iris_fgb.gpkg \
  "/vsicurl/https://data.geopf.fr/chunk/telechargement/download/IRIS-GE-PARTIEL/IRIS-GE_3-0__FLATGEOBUF_WGS84G_FRA_2026-01-01/iris.fgb" \
  -spat 2.8 46.6 4.2 47.6
```
