# MNH LiDAR HD

Une interface de téléchargement est disponible ici : [https://cartes.gouv.fr/telechargement/IGNF_MNH-LIDAR-HD](https://cartes.gouv.fr/telechargement/IGNF_MNH-LIDAR-HD)

## Comment télécharger cette donnée de manière avancée ? 

* Cette donnée n'est pas directement hébergée par le service de Téléchargement de la Géoplateforme.  
* Elle n'est téléchargeable que via un flux WMS.
* La graphe de mosaiquage des dalles du produit est disponible via un flux WFS  

## Comment faire ?

Récupérer la liste des URL des dalles sur une emprise donnée.

Exemple sur l'emprise `xmin=881000, ymin=6220000,xmax=936000,ymax=6283000` en Lambert 93 (`EPSG:2154`) : [https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_MNH-LIDAR-HD:dalle&OUTPUTFORMAT=application/json&propertyName=url&BBOX=881000,6220000,936000,6283000,EPSG:2154](https://data.geopf.fr/wfs/?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_MNH-LIDAR-HD:dalle&OUTPUTFORMAT=application/json&propertyName=url&BBOX=881000,6220000,936000,6283000,EPSG:2154)

Exemple d'URL WMS retournée dans la réponse WFS pour la dalle `LHD_FXX_0937_6225_MNH_O_0M50_LAMB93_IGN69`: [https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNH_O_0M50_LAMB93_IGN69.tif](https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&EXCEPTIONS=text/xml&REQUEST=GetMap&LAYERS=IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93&FORMAT=image/geotiff&STYLES=&CRS=EPSG:2154&BBOX=936999.75,6224000.25,937999.75,6225000.25&WIDTH=2000&HEIGHT=2000&FILENAME=LHD_FXX_0937_6225_MNH_O_0M50_LAMB93_IGN69.tif)

Il suffit donc simplement d'utiliser ces URL pour télécharger chaque dalle du projet **MNH LiDAR HD**.

**Note :** Vous remarquerez les -0.25 et les +0.25 appliqués à la Bounding Box pour extraire correctement une dalle aux coordonnées rondes. Il est ainsi possible d'extraire, par exemples, des dalles jusqu'à 5000 pixels (limite WMS) en appliquant cette bonne pratique.