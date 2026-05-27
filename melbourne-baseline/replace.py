#!/usr/bin/env python3

import argparse
import geopandas as gpd
from lxml import etree
from shapely.geometry import LineString, MultiLineString


def parse_modes(link):
    modes = link.get("modes", "")
    return set(m.strip() for m in modes.split(",") if m.strip())


def is_bike_link(link):
    return "bicycle" in parse_modes(link)


def coord_key(x, y, precision=3):
    return (round(float(x), precision), round(float(y), precision))


def flatten_lines(geom):
    if geom is None:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def get_next_numeric_id(existing_ids, prefix):
    nums = []
    for x in existing_ids:
        x = str(x)
        if x.startswith(prefix):
            try:
                nums.append(int(x.replace(prefix, "")))
            except ValueError:
                pass
    return max(nums, default=0) + 1


def infer_old_network_crs(nodes_el):
    xs, ys = [], []

    for node in nodes_el.findall("node"):
        xs.append(float(node.get("x")))
        ys.append(float(node.get("y")))

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    print(f"Old network coordinate range:")
    print(f"  x: {min_x} to {max_x}")
    print(f"  y: {min_y} to {max_y}")

    # Longitude / latitude

    # WGS84 / UTM zone 60S — likely Auckland / upper North Island NZ
    if (
        166_000 <= min_x <= 834_000
        and 1_000_000 <= min_y <= 10_000_000
    ):
        return "EPSG:32760"
    
    if (
        -180 <= min_x <= 180
        and -180 <= max_x <= 180
        and -90 <= min_y <= 90
        and -90 <= max_y <= 90
    ):
        return "EPSG:4326"

    # New Zealand Transverse Mercator
    if (
        1_000_000 <= min_x <= 3_000_000
        and 4_000_000 <= min_y <= 7_000_000
    ):
        return "EPSG:2193"

    raise ValueError(
        "Could not infer CRS from old MATSim network coordinates. "
        "Paste the coordinate range above and we can identify it."
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--old-network", required=True)
    parser.add_argument("--new-bike-network", required=True)
    parser.add_argument("--output", required=True)

    parser.add_argument("--bike-speed", type=float, default=4.5)
    parser.add_argument("--bike-capacity", type=float, default=1000)
    parser.add_argument("--bike-lanes", type=float, default=1)

    parser.add_argument(
        "--make-bidirectional",
        action="store_true",
        help="Add reverse bike links too"
    )

    args = parser.parse_args()

    # -------------------------
    # Read old MATSim network
    # -------------------------
    xml_parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(args.old_network, xml_parser)
    root = tree.getroot()

    nodes_el = root.find("nodes")
    links_el = root.find("links")

    if nodes_el is None or links_el is None:
        raise ValueError("Old network must contain <nodes> and <links>.")

    scenario_crs = infer_old_network_crs(nodes_el)
    print(f"Inferred old MATSim CRS: {scenario_crs}")

    # -------------------------
    # Existing node lookup
    # -------------------------
    coord_to_node_id = {}
    existing_node_ids = set()
    existing_link_ids = set()

    for node in nodes_el.findall("node"):
        node_id = node.get("id")
        existing_node_ids.add(node_id)

        key = coord_key(node.get("x"), node.get("y"))
        coord_to_node_id[key] = node_id

    for link in links_el.findall("link"):
        existing_link_ids.add(link.get("id"))

    # -------------------------
    # Remove old bike links
    # -------------------------
    removed_bike_links = 0

    for link in list(links_el.findall("link")):
        if is_bike_link(link):
            links_el.remove(link)
            removed_bike_links += 1

    print(f"Removed old bike links: {removed_bike_links}")

    # -------------------------
    # Read new GIS bike network
    # -------------------------
    gdf = gpd.read_file(args.new_bike_network)

    if gdf.crs is None:
        raise ValueError(
            "New bike network has no CRS metadata. "
            "Open it in QGIS and set/export the layer CRS first."
        )

    print(f"New bike network original CRS: {gdf.crs}")

    # gdf = gdf.to_crs(scenario_crs)

    print(f"New bike network reprojected to: {scenario_crs}")

    # -------------------------
    # ID counters
    # -------------------------
    next_node_num = get_next_numeric_id(existing_node_ids, "bike_node_")
    next_link_num = get_next_numeric_id(existing_link_ids, "bike_link_")

    added_nodes = 0
    added_links = 0

    def get_or_create_node(x, y):
        nonlocal next_node_num, added_nodes

        key = coord_key(x, y)

        if key in coord_to_node_id:
            return coord_to_node_id[key]

        node_id = f"bike_node_{next_node_num}"
        next_node_num += 1

        etree.SubElement(
            nodes_el,
            "node",
            id=node_id,
            x=str(float(x)),
            y=str(float(y))
        )

        coord_to_node_id[key] = node_id
        added_nodes += 1

        return node_id

    def add_bike_link(from_id, to_id, length):
        nonlocal next_link_num, added_links

        link_id = f"bike_link_{next_link_num}"
        next_link_num += 1

        etree.SubElement(
            links_el,
            "link",
            id=link_id,
            **{
                "from": str(from_id),
                "to": str(to_id),
                "length": str(max(float(length), 1.0)),
                "freespeed": str(args.bike_speed),
                "capacity": str(args.bike_capacity),
                "permlanes": str(args.bike_lanes),
                "modes": "bicycle",
            }
        )

        added_links += 1

    # -------------------------
    # Add new bike network
    # -------------------------
    for _, row in gdf.iterrows():
        for line in flatten_lines(row.geometry):
            coords = list(line.coords)

            if len(coords) < 2:
                continue

            start = coords[0]
            end = coords[-1]

            from_node = get_or_create_node(start[0], start[1])
            to_node = get_or_create_node(end[0], end[1])

            length = line.length

            add_bike_link(from_node, to_node, length)

            if args.make_bidirectional:
                add_bike_link(to_node, from_node, length)

    # -------------------------
    # Write output
    # -------------------------
    tree.write(
        args.output,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8"
    )

    print("Done.")
    print(f"Added bike nodes: {added_nodes}")
    print(f"Added bike links: {added_links}")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()