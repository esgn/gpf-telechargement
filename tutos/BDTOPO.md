Extraction des bâtiments sur la boite englobante de la commune de Menou (58210).

## DuckDB

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
-- Ne lit que les groupes de lignes couvrant l'emprise, pas les 8 Gio du fichier.
SELECT *
FROM read_parquet('https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_3-5_TOUSTHEMES_GEOPARQUET_WGS84G_FRA_2026-03-15/batiment.parquet')
WHERE ST_Intersects(geometrie, ST_MakeEnvelope(3.2, 47.3, 3.4, 47.4));
```

## GDAL GeoParquet

```bash
# Installation avec conda:
# > conda create --name gdal-parquet
# > conda install -c conda-forge gdal libgdal-arrow-parquet libgdal-adbc

ogr2ogr bati_pqt.gpkg \
  /vsicurl/https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_3-5_TOUSTHEMES_GEOPARQUET_WGS84G_FRA_2026-03-15/batiment.parquet \
  -spat 3.2 47.3 3.4 47.4
```

## GDAL FlatGeoBuf SOZip

```bash
# Attention les FlatGeoBuf sont SOZippés
# Il faut utiliser /vsizip/vsicurl/

ogr2ogr bati_fgb.gpkg \
  /vsizip/vsicurl/https://data.geopf.fr/chunk/telechargement/download/BDTOPO_PQT/BDTOPO_3-5_TOUSTHEMES_FLATGEOBUF-ZIP_WGS84G_FRA_2026-03-15/batiment.fgb.zip \
  -spat 3.2 47.3 3.4 47.4
```

