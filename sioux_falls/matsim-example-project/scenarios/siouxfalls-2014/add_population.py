import gzip
from lxml import etree

inp = "Siouxfalls_population.xml.gz"
out = "Siouxfalls_population_with_subpopulation.xml.gz"

parser = etree.XMLParser(remove_blank_text=False)

with gzip.open(inp, "rb") as f:
    tree = etree.parse(f, parser)

root = tree.getroot()

for person in root.findall("person"):
    attrs = person.find("attributes")
    if attrs is None:
        attrs = etree.Element("attributes")
        person.insert(0, attrs)

    if attrs.find("attribute[@name='subpopulation']") is None:
        attr = etree.SubElement(attrs, "attribute")
        attr.set("name", "subpopulation")
        attr.set("class", "java.lang.String")
        attr.text = "person"

with gzip.open(out, "wb") as f:
    tree.write(
        f,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
        doctype='<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v5.dtd">'
    )

print(f"Wrote {out}")