# 1. Download South Dakota OSM extract

rm south-dakota-latest.osm.pbf
wget https://download.geofabrik.de/north-america/us/south-dakota-latest.osm.pbf

REL=194968

# 1. Get proper boundary geometry
osmium getid south-dakota-latest.osm.pbf r$REL -r \
  -o sioux-falls-boundary.osm.pbf --overwrite

# 2. Export as polygon-only GeoJSON
# osmium export sioux-falls-boundary.osm.pbf \
#   --geometry-types=polygon \
#   -o sioux-falls-boundary.geojson --overwrite

osmium extract \
  -b -96.86,43.45,-96.62,43.66 \
  south-dakota-latest.osm.pbf \
  -o sioux-falls-full.osm.pbf \
  --overwrite

osmium cat sioux-falls-full.osm.pbf \
  -o sioux-falls-full.osm \
  --overwrite  

# Convert the FULL clipped PBF to OSM XML
osmium cat sioux-falls-full.osm.pbf \
  -o sioux-falls-full.osm \
  --overwrite

# Convert to MATSim
# Do this in osm2matsim
# ./bin/convert.sh input/sioux-falls-full.osm output/sioux-falls-network.xml