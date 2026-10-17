# MNT LiDAR HD

🖱️ [Interface cartographique de téléchargement](https://cartes.gouv.fr/telechargement/IGNF_MNT-LIDAR-HD)  
🗺️ [Carte d'avancement de la publication des modèles LiDAR HD](https://macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD)  
📄 [Descriptif de contenu - LiDAR HD (v1.0, PDF)](https://data.geopf.fr/annexes/ressources/documentation/DC_LiDAR_HD_1-0.pdf)  
📦 [Descriptif de livraison - LiDAR HD (v1.0, PDF)](https://data.geopf.fr/annexes/ressources/documentation/DL_LiDAR_HD_1-0.pdf)  
📄 [Descriptif des métadonnées - LiDAR HD (PDF)](https://data.geopf.fr/annexes/ressources/documentation/Descriptif_MTD_LIDARHD.pdf)

## Comment télécharger cette donnée de manière avancée ? 

* Cette donnée n'est pas directement hébergée par le service de Téléchargement de la Géoplateforme.  
* Elle n'est téléchargeable que via un flux WMS, sauf en Guadeloupe, où les URL des dalles pointent directement vers des fichiers GeoTIFF.
* Le graphe de mosaïquage des dalles du produit est rendu disponible via un flux WFS  

## Comment faire ?

Récupérer la liste des URL des dalles sur une emprise donnée.

Exemple sur l'emprise `xmin=881000, ymin=6220000, xmax=936000, ymax=6283000` en Lambert 93 (`EPSG:2154`) - [exécuter la requête](https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_LIDAR-HD_METADONNEE:metadata&OUTPUTFORMAT=application/json&propertyName=url_mnt&BBOX=881000,6220000,936000,6283000,EPSG:2154) :

```
https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_LIDAR-HD_METADONNEE:metadata&OUTPUTFORMAT=application/json&propertyName=url_mnt&BBOX=881000,6220000,936000,6283000,EPSG:2154
```

Une requête WFS renvoie au plus 5000 dalles : au-delà, paginer avec les paramètres `COUNT` et `STARTINDEX`.

La réponse WFS contient, pour chaque dalle, l'URL qui permet de la télécharger. Exemple pour la dalle `LHD_FXX_0937_6225_MNT_O_0M50_LAMB93_IGN69` - [ouvrir l'image](https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNT_O_0M50_LAMB93_IGN69.tif) :

```
https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNT_O_0M50_LAMB93_IGN69.tif
```

Il suffit simplement d'utiliser ces URL pour télécharger chaque dalle du produit **MNT LiDAR HD**.

Une dalle listée peut ne pas être encore publiée (image vide, valeur `-9999`) : voir la [carte d'avancement de la publication](https://macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD).

## À noter

Vous remarquerez les `-0.25` et les `+0.25` appliqués à la bounding box pour extraire correctement une dalle aux coordonnées rondes. 

La dalle du produit a pour nomenclature `LHD_FXX_0937_6225_MNT_O_0M50_LAMB93_IGN69` : 
* `0937` et `6225` désignent les coordonnées en Lambert 93 du coin Nord-Ouest de la dalle : `x = 937000` et `y = 6225000`
* La bounding box de la dalle est donc `xmin = 937000, ymin = 6224000, xmax = 938000, ymax = 6225000` (dalle de 1 kilomètre par 1 kilomètre) 
* La bounding box pour extraire correctement la dalle à partir du flux WMS nécessite d'appliquer `-0.25,+0.25,-0.25,+0.25` soit `BBOX=936999.75,6224000.25,937999.75,6225000.25`

En appliquant cette bonne pratique, il est ainsi possible d'extraire des dalles allant jusqu'à 5000 x 5000 pixels (limite du WMS Géoplateforme) soit 2,5 km x 2,5 km.

Pour extraire plus grand sans écrire les requêtes, le [pilote WMS de GDAL](https://gdal.org/en/stable/drivers/raster/wms.html) interroge lui-même le flux à partir d'un fichier de description du service. Exemple sur l'emprise `xmin=935000, ymin=6222000, xmax=940000, ymax=6227000` (5 km x 5 km) :

```
cat > mnt.xml <<'EOF'
<GDAL_WMS>
  <Service name="WMS">
    <Version>1.3.0</Version>
    <ServerUrl>https://data.geopf.fr/wms-r?</ServerUrl>
    <Layers>IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93</Layers>
    <CRS>EPSG:2154</CRS>
    <ImageFormat>image/geotiff</ImageFormat>
  </Service>
  <DataWindow>
    <UpperLeftX>934999.75</UpperLeftX>
    <UpperLeftY>6227000.25</UpperLeftY>
    <LowerRightX>939999.75</LowerRightX>
    <LowerRightY>6222000.25</LowerRightY>
    <SizeX>10000</SizeX>
    <SizeY>10000</SizeY>
  </DataWindow>
  <DataType>Float32</DataType>
  <BandsCount>1</BandsCount>
  <BlockSizeX>2000</BlockSizeX>
  <BlockSizeY>2000</BlockSizeY>
</GDAL_WMS>
EOF

gdal_translate -a_nodata -9999 mnt.xml mnt.tif
```
