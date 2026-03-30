import os
import xml.etree.ElementTree as ET

from sympy.physics.units import current


def get_declaration(root):
    blocks = root.find(".//globbox").findall("block")
    current_block = None
    for block in blocks:
        if block.find("id").text == "Standard declarations":
            current_block = block
            break
    if current_block is None:
        return []
    color_set = current_block.findall("color")
    var_set = current_block.findall("var")
    globref_set = current_block.findall("globref")
    return color_set, var_set, globref_set

def add_color_set(root, new_set, item_name):
    blocks = root.find(".//globbox").findall("block")
    current_block = None

    # Find the block with id == "Standard declarations"
    for block in blocks:
        if block.find("id").text == "Standard declarations":
            current_block = block
            break

    if current_block is None:
        return []

    # Collect existing <item> elements
    existing_items = current_block.findall(item_name)

    # Deduplicate by id
    seen = set()

    # Remove them from the block
    for item in existing_items:
        seen.add(item.find("id").text)

    for color_set in new_set:
        color_id = color_set.find("id").text
        if color_id not in seen:
            seen.add(color_id)
            current_block.append(color_set)

    return new_set

def merge_sub_pages(target_xml: str, new_xml: str, merged_xml: str):
    # Load the new XML
    new_tree = ET.parse(target_xml)
    new_root = new_tree.getroot()
    new_pages = new_root.findall(".//page")
    new_instances = new_root.find(".//instances")
    new_sub_instances = new_instances.findall("instance") if new_instances is not None else []
    new_color_set, new_var_set, new_globref_set = get_declaration(new_root)

    # Load the target XML
    target_tree = ET.parse(new_xml)
    target_root = target_tree.getroot()

    # Find the <page> elements in the target XML
    target_cpnet = target_root.find("cpnet")
    target_pages = target_cpnet.findall("page") if target_cpnet is not None else []

    # Find the <instance> elements in the target XML
    target_instances = target_root.find(".//instances")
    target_sub_instances = target_instances.findall("instance") if target_instances is not None else []
    add_color_set(target_root, new_color_set, "color")
    add_color_set(target_root, new_var_set, "var")
    add_color_set(target_root, new_globref_set, "globref")

    if target_pages and new_pages is not None:
        # Update last page name
        last_page = target_pages[-1]
        last_page_name = last_page.find("pageattr")
        if last_page_name is None:
            last_page_name = ET.SubElement(last_page, "pageattr")
        last_page_name.set("name", os.path.splitext(os.path.basename(new_xml))[0])

        # Insert the new page *after the last page*
        index = list(target_cpnet).index(last_page)

        # Update new page name
        for each_page in new_pages:
            new_page_name = each_page.find("pageattr")
            if new_page_name is None:
                new_page_name = ET.SubElement(each_page, "pageattr")
            if new_page_name.get("name") == "myNet":
                new_page_name.set("name", os.path.splitext(os.path.basename(target_xml))[0])
            target_cpnet.insert(index + 1, each_page)
            index +=1

    if target_sub_instances and new_sub_instances:
        for inst in new_sub_instances:
            target_instances.append(inst)

    # Save the merged XML
    target_tree.write(merged_xml, encoding="iso-8859-1", xml_declaration=True)

    print(f"Merge {new_xml} into {merged_xml}: DONE")
    return merged_xml

def get_page_info (pages, page_name):
    page_id = ""
    page_current = None
    for page in pages:
        pageattr = page.find("pageattr")
        if pageattr is not None and pageattr.get("name") == page_name:
            page_id = page.get("id")
            page_current =page
            break
    return page_id, page_current

def find_page_info (pages, page_name):
    input_place = ""
    output_place = ""
    input_type = ""
    output_type = ""
    page_id, page = get_page_info(pages, page_name)
    for place in page.findall("place"):
        port = place.find("port")
        if port is not None:
            place_value = place.get("id")
            type_value = place.find("type").find("text").text
            if port.get("type") == "In":
                input_place = place_value
                input_type = type_value
            elif port.get("type") == "Out":
                output_place = place_value
                output_type = type_value
    return page_id, input_place, output_place, input_type, output_type

def find_arcs_transition(arcs, trans_id):
    """Find incoming and outgoing arc IDs for a transition by its name."""
    in_place_id, out_place_id = "", ""
    # Now, find arcs connected to that transition
    for arc in arcs:
        transend = arc.find("transend")
        if transend is not None and transend.get("idref") == trans_id:
            if arc.get("orientation") == "PtoT":
                in_place_id = arc.find("placeend").get("idref")
            elif arc.get("orientation") == "TtoP":
                out_place_id = arc.find("placeend").get("idref")

    return in_place_id, out_place_id

def generate_id(prefix: str, unique_counter) -> str:
    """Simple incremental ID generator, to produce unique 'IDxxxx' strings."""
    return f"ID{prefix}{unique_counter}"

def set_place_type(page_ele, place_id, type_value):
    places = page_ele.findall("place")
    current_place = None
    for place in places:
        if place.get("id") == place_id:
            current_place = place
            break
    if current_place is not None:
        current_place.find("type").find("text").text = type_value

def transform_to_substitution(config, trans_elt_p, counter,page_trans, super_place_element):
    # TODO link a subpage to a transition
    trans_name_p = trans_elt_p.find("text").text
    pages = config[0]
    arcs = config[1]
    sub_page_name = trans_name_p
    trans_id = trans_elt_p.get("id")
    posattr = trans_elt_p.find("posattr")
    t_tx = float(posattr.get("x", "0"))
    t_ty = float(posattr.get("y", "0"))

    sub_page_id, input_port, output_port, input_type, output_type = find_page_info(pages, sub_page_name)
    page_trans.append({"trans_id": trans_id, "page": sub_page_id})
    in_place, out_place = find_arcs_transition(arcs, trans_id)
    subst_elt = ET.Element(
        "subst",
        {
            "subpage": sub_page_id,
            "portsock": "({},{})({},{})".format(input_port, in_place, output_port, out_place)
        }
    )
    set_place_type(super_place_element, in_place, input_type)
    set_place_type(super_place_element, out_place, output_type)

    # Find index of the <binder> tag
    children = list(trans_elt_p)
    binder_index = next((i for i, c in enumerate(children) if c.tag == "binding"), None)

    if binder_index is not None:
        # Insert before binder
        trans_elt_p.insert(binder_index-1, subst_elt)
    else:
        # Fallback: just append if no binder found
        trans_elt_p.append(subst_elt)

    new_id = generate_id("subpage", counter)

    sub_page_elt = ET.SubElement(subst_elt, "subpageinfo", {"id":new_id, "name": sub_page_name})
    ET.SubElement(sub_page_elt, "posattr", {
        "x": f"{t_tx-34:.6f}",
        "y": f"{t_ty-34:.6f}"
    })
    ET.SubElement(sub_page_elt, "fillattr", {"colour": "White", "pattern": "", "filled": "false"})
    ET.SubElement(sub_page_elt, "lineattr", {"colour": "Black", "thick": "1", "type": "solid"})
    ET.SubElement(sub_page_elt, "textattr", {"colour": "Black", "bold": "false"})
    return counter + 1, page_trans

def update_relationship_instances(tree_root, super_page_id, page_trans, counter_new):
    instances = tree_root.find(".//instances")
    new_instances = []
    for instance in instances.findall("instance"):
        instance_id = instance.get("id")
        mapping = None
        for item in page_trans:
            if item.get("page") == instance.get("page"):
                mapping = item
                break
        if mapping is None:
            continue
        trans_id = mapping.get("trans_id")
        new_instances.append({"instance_id": instance_id, "trans_id": trans_id})
        instances.remove(instance)
    for sub_sti in page_trans:
        trans_id = sub_sti.get("trans_id")
        exist = False
        for item in new_instances:
            if trans_id == item.get("trans_id"):
                exist = True
                break
        if not exist:
            counter_new = counter_new + 1
            new_instances.append({"instance_id": f"{counter_new}", "trans_id": trans_id})
    for parent_inst in instances.findall("instance"):
        if parent_inst.get("page") != super_page_id:
            continue
        for substitution in new_instances:
            ET.SubElement(parent_inst, "instance", {"id": substitution.get("instance_id"),
                                                              "trans": substitution.get("trans_id")})
from xml.dom import minidom

def pretty_print_xml(file_in, file_out):
    # Parse the XML
    tree = ET.parse(file_in)
    xml_bytes = ET.tostring(tree.getroot(), encoding="iso-8859-1")

    # minidom expects a string, so decode bytes using the same encoding
    xml_str = xml_bytes.decode("iso-8859-1")

    # Parse with minidom and pretty print
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ")

    # Remove extra blank lines
    pretty_xml = "\n".join([line for line in pretty_xml.splitlines() if line.strip()])

    # Write to file with the correct encoding
    with open(file_out, "w", encoding="iso-8859-1") as f:
        f.write(pretty_xml)



def transform_to_hcpn(xml, super_page_name, counter, module_list):
    tree = ET.parse(xml)
    root = tree.getroot()
    pages = root.findall(".//page")
    trans = []
    arcs = []
    super_page_element = None
    for page in pages:
        if page.find("pageattr").get("name") == super_page_name:
            trans = page.findall("trans")
            arcs = page.findall("arc")
            super_page_element = page
            break
    config = [pages, arcs]
    counter_new = counter
    page_trans = []
    for tran in trans:
        if tran.find("text").text not in module_list:
            continue
        counter_new, page_trans = transform_to_substitution(config,tran,
                                                            counter_new, page_trans, super_page_element)

    super_page_id, page = get_page_info(pages, super_page_name)
    update_relationship_instances (root, super_page_id, page_trans, counter_new)

    tree.write(xml, encoding="iso-8859-1", xml_declaration=True)
    # pretty_print_xml(xml, "pretty1.cpn")
    print("transform_to_hcpn: Finished")

