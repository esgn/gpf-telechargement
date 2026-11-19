Extraction des bâtiments sur la boite englobante de la commune de Menou (58210).

## DuckDB

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
-- Le filtre sur geometrie_bbox limite la lecture aux groupes de lignes
-- couvrant l'emprise : 41 MiB au lieu de 8 GiB.
SELECT *
FROM read_parquet(
    'https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_TOUSTHEMES_3-5_GEOPARQUET_WGS84G_FRA_2026-09-15/batiment.parquet'
)
WHERE geom && ST_MakeEnvelope(3.2, 47.3, 3.4, 47.4)
  AND ST_Intersects(
      geom,
      ST_MakeEnvelope(3.2, 47.3, 3.4, 47.4)
  );
```

## GDAL GeoParquet

```bash
# Installation de gdal avec support geoparquet via conda:
# > conda create --name gdal-parquet
# > conda install -c conda-forge gdal libgdal-arrow-parquet libgdal-adbc

ogr2ogr bati_pqt.gpkg \
  /vsicurl/https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_TOUSTHEMES_3-5_GEOPARQUET_WGS84G_FRA_2026-09-15/batiment.parquet \
  -spat 3.2 47.3 3.4 47.4
```

## GDAL FlatGeoBuf SOZipls

```bash
# Attention les FlatGeoBuf sont SOZippés
# Il faut utiliser '/vsizip/vsicurl/'

ogr2ogr bati_fgb.gpkg \
  /vsizip/vsicurl/https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_TOUSTHEMES_3-5_FLATGEOBUF-ZIP_WGS84G_FRA_2026-09-15/batiment.fgb.zip \
  -spat 3.2 47.3 3.4 47.4
```

