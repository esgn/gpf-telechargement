# MNS LiDAR HD

Une interface de téléchargement est disponible ici : [https://cartes.gouv.fr/telechargement/IGNF_MNS-LIDAR-HD](https://cartes.gouv.fr/telechargement/IGNF_MNS-LIDAR-HD)

La spécification du produit est ici : [https://data.geopf.fr/annexes/ressources/documentation/DC_LiDAR_HD_1-0.pdf](https://data.geopf.fr/annexes/ressources/documentation/DC_LiDAR_HD_1-0.pdf)

## Comment télécharger cette donnée de manière avancée ? 

* Cette donnée n'est pas directement hébergée par le service de Téléchargement de la Géoplateforme.  
* Elle n'est téléchargeable que via un flux WMS.
* La graphe de mosaiquage des dalles du produit est disponible via un flux WFS  

## Comment faire ?

Récupérer la liste des URL des dalles sur une emprise donnée.

Exemple sur l'emprise `xmin=881000, ymin=6220000,xmax=936000,ymax=6283000` en Lambert 93 (`EPSG:2154`) : [https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_MNS-LIDAR-HD:dalle&OUTPUTFORMAT=application/json&propertyName=url&BBOX=881000,6220000,936000,6283000,EPSG:2154](https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_MNS-LIDAR-HD:dalle&OUTPUTFORMAT=application/json&propertyName=url&BBOX=881000,6220000,936000,6283000,EPSG:2154)

Exemple d'URL WMS retournée dans la réponse WFS pour la dalle `LHD_FXX_0937_6225_MNS_O_0M50_LAMB93_IGN69`: [https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNS_O_0M50_LAMB93_IGN69.tif](https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNS_O_0M50_LAMB93_IGN69.tif)

Il suffit simplement d'utiliser ces URLs pour télécharger chaque dalle du produit **MNS LiDAR HD**.

## A noter

Vous remarquerez les `-0.25` et les `+0.25` appliqués à la Bounding Box pour extraire correctement une dalle aux coordonnées rondes.

La dalle du produit a pour nomenclature `LHD_FXX_0937_6225_MNS_O_0M50_LAMB93_IGN69` : 
* `0937` et `6225` désigne la coordonnée en LAMBERT 93 du coin nord-ouest de l'image : `x = 937000` et `y = 6225000`
* La bounding box de l'image est donc `xmin = 937000, ymin = 6224000, xmax = 938000, ymin = 6224000` (dalle de 1 kilomètre par 1 kilomètre) 
* La bounding box pour extraire correctement à partir du flux WMS se voit appliquer `-0.25,+0.25,-0.25,+0.25` soit `BBOX=936999.75,6224000.25,937999.75,6225000.25`

En appliquant cette bonne pratique, il est ainsi possible d'extraire des dalles allant jusqu'à 5000x5000 pixels (limite du WMS Géoplateforme) soit 2.5km x 2.5km.
