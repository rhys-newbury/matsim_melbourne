from lxml import etree
import matplotlib.pyplot as plt

NETWORK = "scenario/v1/new_network.xml"
OUT = "network_with_bicycle.svg"

tree = etree.parse(NETWORK)
root = tree.getroot()

nodes = {}
for n in root.find("nodes").findall("node"):
    nodes[n.get("id")] = (float(n.get("x")), float(n.get("y")))

bike_xs, bike_ys = [], []
road_xs, road_ys = [], []

for l in root.find("links").findall("link"):
    modes = l.get("modes", "")

    if l.get("from") not in nodes or l.get("to") not in nodes:
        continue

    a = nodes[l.get("from")]
    b = nodes[l.get("to")]

    if "bicycle" in modes:
        bike_xs += [a[0], b[0], None]
        bike_ys += [a[1], b[1], None]
    else:
        road_xs += [a[0], b[0], None]
        road_ys += [a[1], b[1], None]

plt.figure(figsize=(14, 14))

# Other roads underneath
plt.plot(
    road_xs,
    road_ys,
    linewidth=0.15,
    alpha=0.25,
    color="gray",
    label="Other roads"
)

# Bicycle network on top
plt.plot(
    bike_xs,
    bike_ys,
    linewidth=0.45,
    alpha=0.95,
    color="red",
    label="Bicycle"
)

plt.axis("equal")
plt.axis("off")
plt.legend()
plt.title("MATSim network with bicycle links")

plt.savefig(
    OUT,
    format="svg",
    bbox_inches="tight"
)

print(f"Saved {OUT}")