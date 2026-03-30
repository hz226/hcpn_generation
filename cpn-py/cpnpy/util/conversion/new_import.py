import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple
import json
import re

def json_to_cpn_xml(json_data: Dict[str, Any], coords_data: Dict[str, Any]) -> str:
    unique_counter = 100
    def generate_id(prefix: str) -> str:
        nonlocal unique_counter
        unique_counter += 1
        return f"ID{prefix}{unique_counter}"

    def find_node_position(name: str) -> Tuple[float, float]:
        for node in coords_data.get("nodes", []):
            if node.get("title") == name:
                geom = node.get("geometry", {})
                t = geom.get("type", "")
                if t == "ellipse":
                    return geom.get("cx", 0.0), geom.get("cy", 0.0)
                elif t == "rect":
                    return geom.get("x",0.0)+geom.get("width",0.0)/2, geom.get("y",0.0)+geom.get("height",0.0)/2
                elif t == "polygon":
                    pts = geom.get("points", [])
                    if pts:
                        return sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts)
                    return 0.0, 0.0
                elif t == "path":
                    coords = [(float(x),float(y)) for x,y in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", geom.get("d",""))]
                    if coords:
                        xs, ys = zip(*coords)
                        return (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
                    return 0.0,0.0
        return 0.0,0.0

    def parse_cpn_colorset(cs_def: str) -> Tuple[str, ET.Element]:
        line = cs_def.strip()[len("colset "):-1].strip()  # remove colset ...;
        name, typ = [x.strip() for x in line.split("=",1)]
        color_elem = ET.Element("color", {"id": generate_id("color")})
        ET.SubElement(color_elem, "id").text = name
        ET.SubElement(color_elem, "layout").text = cs_def
        t = typ.lower()
        if "unit" in t: ET.SubElement(color_elem, "unit")
        elif "bool" in t: ET.SubElement(color_elem, "bool")
        elif "intinf" in t: ET.SubElement(color_elem, "intinf")
        elif "int" in t: ET.SubElement(color_elem, "int")
        elif "time" in t: ET.SubElement(color_elem, "time")
        elif "real" in t: ET.SubElement(color_elem, "real")
        elif "string" in t: ET.SubElement(color_elem, "string")
        elif "{" in t and "}" in t:
            enum_elem = ET.SubElement(color_elem, "enum")
            for val in typ[typ.index("{")+1:typ.rindex("}")].split(","):
                ET.SubElement(enum_elem, "id").text = val.strip()
        else:
            ET.SubElement(color_elem, "string")
        return name, color_elem

    def gather_all_variables(json_data: Dict[str, Any]) -> Dict[str, List[str]]:
        var_map = {}
        for trans in json_data.get("transitions", []):
            for v in trans.get("variables", []):
                var_map.setdefault("INT", []).append(v)
        return var_map

    def create_var_elements(block_elem: ET.Element, var_map: Dict[str, List[str]]):
        for cs_name, vars_list in var_map.items():
            if not vars_list: continue
            var_elem = ET.SubElement(block_elem, "var", {"id": generate_id("var")})
            t = ET.SubElement(var_elem, "type")
            ET.SubElement(t, "id").text = cs_name
            for v in vars_list: ET.SubElement(var_elem, "id").text = v
            ET.SubElement(var_elem, "layout").text = f"var {','.join(vars_list)} : {cs_name};"

    def build_marking_expression(place_name: str) -> str:
        init = json_data.get("initialMarking", {}).get(place_name)
        if not init: return ""
        tokens = init.get("tokens", [])
        timestamps = init.get("timestamps", [0]*len(tokens))
        if len(timestamps) < len(tokens): timestamps=[0]*len(tokens)
        parts=[]
        for tok,ts in zip(tokens,timestamps):
            if isinstance(tok,(int,float)): tok_repr=str(tok)
            elif isinstance(tok,str): tok_repr=f"\"{tok}\""
            elif isinstance(tok,(list,tuple)):
                tok_repr="(" + ",".join([str(x) if isinstance(x,(int,float)) else f"\"{x}\"" for x in tok]) + ")"
            else: tok_repr=str(tok)
            parts.append(f"1`{tok_repr}" + (f"@{ts}" if ts!=0 else ""))
        return "++".join(parts)

    root = ET.Element("workspaceElements")
    ET.SubElement(root, "generator", {"tool":"CPN Tools","version":"4.0.1","format":"6"})
    cpnet = ET.SubElement(root, "cpnet")
    globbox = ET.SubElement(cpnet, "globbox")

    # main block
    block_decls = ET.SubElement(globbox, "block", {"id": generate_id("blk")})
    ET.SubElement(block_decls, "id").text="Standard declarations"
    color_name_to_element={}
    for cs_def in json_data.get("colorSets", []):
        cname, celem=parse_cpn_colorset(cs_def)
        block_decls.append(celem)
        color_name_to_element[cname]=celem
    var_map = gather_all_variables(json_data)
    create_var_elements(block_decls,var_map)

    page_id = generate_id("page")
    page = ET.SubElement(cpnet, "page", {"id": page_id})
    ET.SubElement(page, "pageattr", {"name": "myNet"})
    place_name_to_id={}
    transition_name_to_id={}

    # Places
    for p in json_data.get("places", []):
        pname=p["name"]; cset=p["colorSet"]
        pid=generate_id("place"); place_name_to_id[pname]=pid
        place_elt=ET.SubElement(page,"place",{"id":pid})
        px,py=find_node_position(pname)
        ET.SubElement(place_elt,"posattr",{"x":f"{px:.6f}","y":f"{py:.6f}"})
        ET.SubElement(place_elt,"fillattr",{"colour":"White","pattern":"","filled":"false"})
        ET.SubElement(place_elt,"lineattr",{"colour":"Black","thick":"1","type":"Solid"})
        ET.SubElement(place_elt,"textattr",{"colour":"Black","bold":"false"})
        ET.SubElement(place_elt,"text").text=pname
        ET.SubElement(place_elt,"ellipse",{"w":"60.0","h":"40.0"})
        type_elt=ET.SubElement(place_elt,"type",{"id":generate_id("type")})
        ET.SubElement(type_elt,"posattr",{"x":f"{px+40:.6f}","y":f"{py-30:.6f}"})
        ET.SubElement(type_elt,"fillattr",{"colour":"White","pattern":"Solid","filled":"false"})
        ET.SubElement(type_elt,"lineattr",{"colour":"Black","thick":"0","type":"Solid"})
        ET.SubElement(type_elt,"textattr",{"colour":"Black","bold":"false"})
        ET.SubElement(type_elt,"text",{"tool":"CPN Tools","version":"4.0.1"}).text=cset
        mark_expr=build_marking_expression(pname)
        mark_elt=ET.SubElement(place_elt,"marking",{"x":f"{px:.6f}","y":f"{py:.6f}","hidden":"false"})
        ET.SubElement(mark_elt,"text").text=mark_expr if mark_expr else "empty"

    # Transitions
    for t in json_data.get("transitions", []):
        tname=t["name"]; tid=generate_id("trans"); transition_name_to_id[tname]=tid
        t_elt=ET.SubElement(page,"trans",{"id":tid,"explicit":"false"})
        tx,ty=find_node_position(tname)
        ET.SubElement(t_elt,"posattr",{"x":f"{tx:.6f}","y":f"{ty:.6f}"})
        ET.SubElement(t_elt,"fillattr",{"colour":"White","pattern":"","filled":"false"})
        ET.SubElement(t_elt,"lineattr",{"colour":"Black","thick":"1","type":"solid"})
        ET.SubElement(t_elt,"textattr",{"colour":"Black","bold":"false"})
        ET.SubElement(t_elt,"text").text=tname
        ET.SubElement(t_elt,"box",{"w":"60.0","h":"40.0"})

    # Arcs
    for t in json_data.get("transitions", []):
        tid=transition_name_to_id[t["name"]]
        for arc in t.get("inArcs", []):
            pid=place_name_to_id[arc["place"]]
            a=ET.SubElement(page,"arc",{"id":generate_id("arc"),"orientation":"PtoT","order":"1"})
            ET.SubElement(a,"placeend",{"idref":pid})
            ET.SubElement(a,"transend",{"idref":tid})
            ann=ET.SubElement(a,"annot",{"id":generate_id("annot")})
            ET.SubElement(ann,"text",{"tool":"CPN Tools","version":"4.0.1"}).text=arc["expression"]
            ET.SubElement(a,"text").text=""
        for arc in t.get("outArcs", []):
            pid=place_name_to_id[arc["place"]]
            a=ET.SubElement(page,"arc",{"id":generate_id("arc"),"orientation":"TtoP","order":"1"})
            ET.SubElement(a,"transend",{"idref":tid})
            ET.SubElement(a,"placeend",{"idref":pid})
            ann=ET.SubElement(a,"annot",{"id":generate_id("annot")})
            ET.SubElement(ann,"text",{"tool":"CPN Tools","version":"4.0.1"}).text=arc["expression"]
            ET.SubElement(a,"text").text=""

    ET.SubElement(page,"constraints")
    ET.indent(root, space="  ")
    xml_str=ET.tostring(root,encoding="utf-8",method="xml").decode("utf-8")
    doctype='<?xml version="1.0" encoding="iso-8859-1"?>\n<!DOCTYPE workspaceElements PUBLIC "-//CPN//DTD CPNXML 1.0//EN" "http://cpntools.org/DTD/6/cpn.dtd">\n'
    return doctype+xml_str
