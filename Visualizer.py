import dash_cytoscape as cyto
from dash import Dash, html, dcc, Input, Output, State, no_update

from copy import deepcopy
from dash import no_update


class HCPNCytoscapeVisualizer:
    """
    Visualize HCPN with module/submodule containers (compound nodes):
      - Each module/submodule is a parent node (container).
      - Its places/transitions are children inside the container.
      - Internal arcs are drawn between child nodes (directed).
      - Substitution edges link parent transition -> child module container (directed).
      - Super-modules are *not* parents of modules (no nesting), but appear ABOVE them:
        Achieved with invisible layout-only edges: super_module -> module.

    Additions (patch):
      - For super_modules, arrange children in *two rows* with exact same-Y alignment:
          Row 1 (top): all places (same Y)
          Row 2 (below): all transitions (same Y)
        Implementation uses invisible in-container anchor nodes + layout-only edges
        to guide Klay layout while showing all places, transitions, and arcs.

      - NEW: Module labels are folded by default and can be unfolded (expanded) by clicking
        the module container. The expanded state persists (toggle on/off).
    """

    def __init__(self):
        self.elements = []
        self._super_modules = set()
        self._roots = []  # used by 'breadthfirst' layout (if you choose it)

    def apply(self, hcpn, markings, params=None):
        """
        Build Cytoscape elements from your existing HCPN.

        Args:
          hcpn: object with:
            - modules: dict[str, cpn] where cpn has .places, .transitions, .arcs
            - substitutions: dict[(parent_module, parent_transition), child_module]
            - get_substitution_target(module_name, transition_name) -> child_module | None
          markings: dict[module_name, marking] (optional)
            - marking.get_multiset(place_name) -> object with .tokens list (optional)
          params:
            - show_tokens: bool = True
            - super_relations: dict[str, list[str]]  # explicit super -> [modules]
            - module_name_is_super: callable(name) -> bool  (default: lambda n: "I_" in n)
            - super_children_two_rows: bool = True
                # When True, inside super_modules, arrange children as:
                #   Row 1: all places ; Row 2: all transitions (each row has same Y).
                # Achieved with invisible anchors + layout-only edges; nothing is hidden.
        """
        params = params or {}
        show_tokens = params.get("show_tokens", True)
        super_relations = params.get("super_relations", None)
        is_super = params.get("module_name_is_super", lambda n: "I_" in n)
        super_children_two_rows = params.get("super_children_two_rows", True)

        elements = []

        # Identify super_modules by predicate
        modules = list(hcpn.modules.keys())
        super_modules = [m for m in modules if is_super(m)]
        self._super_modules = set(super_modules)

        # Relations: super_module -> related modules (for layout only)
        inferred_relations = {}
        if getattr(hcpn, "substitutions", None):
            for (parent_mod, _parent_trans), child_mod in hcpn.substitutions.items():
                if parent_mod in self._super_modules:
                    inferred_relations.setdefault(parent_mod, set()).add(child_mod)
        relations = {
            k: set(v) for k, v in (super_relations or inferred_relations).items()
        }
        supermodule_label_font_size = params.get("supermodule_label_font_size", 80)
        module_label_font_size = params.get("module_label_font_size", 80)

        # === Build containers and their children ===
        for module_name, cpn in hcpn.modules.items():
            is_super_mod = module_name in self._super_modules

            # Parent (container) node for this module/submodule
            folded = module_name  # folded by default
            full = module_name  # can be extended later (e.g., with conformance info)
            elements.append(
                {
                    "data": {
                        "id": module_name,
                        "label": folded,  # start folded
                        "folded_label": folded,  # source (short)
                        "full_label": full,  # source (long) - can be updated later
                        # add per-node data so stylesheet can pick it up
                        "font_size": (
                            supermodule_label_font_size
                            if is_super_mod
                            else module_label_font_size
                        ),
                        "expanded": False,
                        "is_module_parent": 1,
                    },
                    "classes": (
                        "module_parent super_module"
                        if is_super_mod
                        else "module_parent"
                    ),
                }
            )

            marking = markings.get(module_name) if markings else None

            # --- Collect children IDs for intra-module layout (esp. for super_modules) ---
            place_ids, trans_ids = [], []

            # Places (children inside the module container)
            for place in getattr(cpn, "places", []) or []:
                pid = f"{module_name}__P__{place.name}"
                label = place.name
                if show_tokens:
                    token_str = ""
                    if marking is not None and hasattr(marking, "get_multiset"):
                        ms = marking.get_multiset(place.name)
                        tokens = getattr(ms, "tokens", []) if ms else []
                        token_str = (
                            ", ".join(str(tok) for tok in tokens)
                            if tokens
                            else "No tokens"
                        )
                    label = f"{place.name}\n[{token_str}]"
                elements.append(
                    {
                        "data": {"id": pid, "label": label, "parent": module_name},
                        "classes": "place",
                    }
                )
                place_ids.append(pid)

            # Transitions (children inside the module container)
            for trans in getattr(cpn, "transitions", []) or []:
                tid = f"{module_name}__T__{trans.name}"
                target = (
                    hcpn.get_substitution_target(module_name, trans.name)
                    if hasattr(hcpn, "get_substitution_target")
                    else None
                )
                cls = "substitution" if target else "transition"
                label = trans.name + (f"\n[Sub → {target}]" if target else "")
                elements.append(
                    {
                        "data": {"id": tid, "label": label, "parent": module_name},
                        "classes": cls,
                    }
                )
                trans_ids.append(tid)

            # Internal arcs (directed edges between children)
            for arc in getattr(cpn, "arcs", []) or []:
                src_type = (
                    "P"
                    if getattr(arc.source, "__class__", None).__name__ == "Place"
                    else "T"
                )
                tgt_type = (
                    "P"
                    if getattr(arc.target, "__class__", None).__name__ == "Place"
                    else "T"
                )
                src = f"{module_name}__{src_type}__{arc.source.name}"
                tgt = f"{module_name}__{tgt_type}__{arc.target.name}"
                elements.append(
                    {"data": {"source": src, "target": tgt}, "classes": "arc"}
                )

            # --- Enforce two rows inside super_modules with SAME-Y rows ---
            # Places row (top, same Y), Transitions row (bottom, same Y)
            if is_super_mod and super_children_two_rows:
                # Vertical anchors (top & bottom of the two-row band)
                aP = f"{module_name}__A__P"  # top-row vertical anchor
                aT = f"{module_name}__A__T"  # bottom-row vertical anchor

                # Horizontal row anchors (left/right) for places and transitions
                aPL = f"{module_name}__A__PL"  # places row - left
                aPR = f"{module_name}__A__PR"  # places row - right
                aTL = f"{module_name}__A__TL"  # transitions row - left
                aTR = f"{module_name}__A__TR"  # transitions row - right

                # Add the invisible anchors as children of the same module
                for aid in (aP, aT, aPL, aPR, aTL, aTR):
                    elements.append(
                        {
                            "data": {"id": aid, "label": "", "parent": module_name},
                            "classes": "layout_anchor",
                        }
                    )

                # 1) Row ordering and single-Y constraint (horizontal guides)
                for pid in place_ids:
                    elements.append(
                        {
                            "data": {"source": aPL, "target": pid},
                            "classes": "layout_only",
                        }
                    )
                    elements.append(
                        {
                            "data": {"source": pid, "target": aPR},
                            "classes": "layout_only",
                        }
                    )

                for tid in trans_ids:
                    elements.append(
                        {
                            "data": {"source": aTL, "target": tid},
                            "classes": "layout_only",
                        }
                    )
                    elements.append(
                        {
                            "data": {"source": tid, "target": aTR},
                            "classes": "layout_only",
                        }
                    )

                # Optional: also chain horizontally to stabilize left-to-right order
                for i in range(len(place_ids) - 1):
                    elements.append(
                        {
                            "data": {
                                "source": place_ids[i],
                                "target": place_ids[i + 1],
                            },
                            "classes": "layout_only",
                        }
                    )
                for i in range(len(trans_ids) - 1):
                    elements.append(
                        {
                            "data": {
                                "source": trans_ids[i],
                                "target": trans_ids[i + 1],
                            },
                            "classes": "layout_only",
                        }
                    )

                # 2) Vertical separation: keep PLACES above TRANSITIONS
                for pid in place_ids:
                    elements.append(
                        {
                            "data": {"source": aP, "target": pid},
                            "classes": "layout_only",
                        }
                    )

                # ensure transitions are below the places layer but above aT
                if trans_ids:
                    ref_above = place_ids[0] if place_ids else aP
                    for tid in trans_ids:
                        elements.append(
                            {
                                "data": {"source": ref_above, "target": tid},
                                "classes": "layout_only",
                            }
                        )
                    # keep transitions above bottom anchor
                    for tid in trans_ids:
                        elements.append(
                            {
                                "data": {"source": tid, "target": aT},
                                "classes": "layout_only",
                            }
                        )
                else:
                    # if no transitions, still keep places above bottom anchor
                    for pid in place_ids:
                        elements.append(
                            {
                                "data": {"source": pid, "target": aT},
                                "classes": "layout_only",
                            }
                        )

                # 3) Optional: row stacking hints (right of places -> left of transitions)
                elements.append(
                    {"data": {"source": aPR, "target": aTL}, "classes": "layout_only"}
                )

        # Substitution edges: transition (child) -> child module container (parent node)
        for (parent_mod, parent_trans), child_mod in getattr(
            hcpn, "substitutions", {}
        ).items():
            parent_tid = f"{parent_mod}__T__{parent_trans}"
            elements.append(
                {
                    "data": {"source": parent_tid, "target": child_mod, "label": "sub"},
                    "classes": "subedge",
                }
            )

        # Invisible layout-only edges to place modules under super_modules (no nesting)
        for s, children in relations.items():
            for m in children:
                if s in self._super_modules and m in hcpn.modules:
                    elements.append(
                        {"data": {"source": s, "target": m}, "classes": "layout_only"}
                    )

        # Roots for breadthfirst (if you choose that layout)
        self._roots = list(self._super_modules)

        self.elements = elements
        return self

    def view(self, height=900, width="100%", layout_name="klay", orientation="TB"):
        """
        Build the Cytoscape component.

        Args:
          layout_name: 'klay' (recommended for compound parents) or 'dagre' (limited compound support)
          orientation: 'TB' or 'LR'
        """
        if not self.elements:
            raise ValueError("No elements available. Call apply() first.")

        font_size_place = 50  # TODO add it into params
        width_place = 150
        font_size_trans = 50  # TODO add it into params
        width_trans = 150
        font_size_subtrans = 50  # TODO add it into params
        width_subtrans = 150

        if layout_name == "klay":
            # Klay handles compound parents well and supports direction.
            direction = "DOWN" if orientation == "TB" else "RIGHT"
            layout = {
                "name": "klay",
                "fit": True,
                "padding": 20,
                "animate": False,
                "nodeDimensionsIncludeLabels": True,
                "klay": {
                    "direction": direction,  # DOWN or RIGHT
                    "edgeRouting": "ORTHOGONAL",  # clean elbows
                    "spacing": 40,  # slightly tighter than default
                    "borderSpacing": 20,
                    "inLayerSpacingFactor": 1.0,
                    "nodePlacement": "BRANDES_KOEPF",
                },
            }
        else:
            # Dagre: good layering, but limited compound support
            rankDir = "LR" if orientation == "LR" else "TB"
            layout = {
                "name": "dagre",
                "rankDir": rankDir,
                "nodeSep": 110,
                "rankSep": 160,
                "edgeSep": 40,
            }

        return html.Div(
            cyto.Cytoscape(
                id="hcpn",
                elements=self.elements, 
                minZoom=0.1,
                maxZoom=3,
                layout=layout,
                style={"width": width, "height": f"{height}px"},
                stylesheet=[
                    # Invisible edges that influence layout only (super_module -> module, row guides)
                    {
                        "selector": ".layout_only",
                        "style": {
                            "opacity": 0,
                            "line-color": "transparent",
                            "target-arrow-shape": "none",
                            "width": 0.0001,
                            "events": "no",
                        },
                    },
                    # Invisible in-module anchor nodes for two-row layout & row rails
                    {
                        "selector": ".layout_anchor",
                        "style": {
                            "shape": "rectangle",
                            "width": 1,
                            "height": 1,
                            "opacity": 0,
                            "background-color": "transparent",
                            "border-width": 0,
                            "label": "",
                            "events": "no",
                        },
                    },
                    # === PARENT CONTAINERS (modules & super_modules) ===
                    {
                        "selector": ".module_parent",
                        "style": {
                            "shape": "round-rectangle",
                            "background-color": "#eef2fb",
                            "background-opacity": 0.35,
                            "border-color": "#6c7ae0",
                            "border-width": 2,
                            "font-size": "data(font_size)",  # use per-node font size
                            "label": "data(folded_label)",  # "data(label)",  # folded or full (toggled)
                            "font-weight": "600",
                            "text-valign": "top",
                            "text-halign": "center",
                            "text-margin-y": -6,
                            "padding": "28px",
                            "text-wrap": "wrap",
                            "text-max-width": 600,
                        },
                    },
                    {
                        "selector": ".module_parent[?expanded]",
                        "style": {
                            "label": "data(full_label)",  # IMPROVED: show full label when expanded
                            "border-width": 4,
                            "border-color": "#2f54eb",
                            "background-opacity": 0.45,
                        },
                    },
                    {
                        "selector": ".super_module",
                        "style": {
                            "background-color": "#eaf0ff",
                            "border-color": "#4e63d9",
                        },
                    },
                    # === CHILD NODES ===
                    {
                        "selector": ".place",
                        "style": {
                            "shape": "ellipse",
                            "width": width_place,
                            "height": 60,
                            "label": "data(label)",
                            "text-valign": "center",
                            "text-halign": "center",
                            "background-color": "#ffffff",
                            "border-width": 2,
                            "border-color": "#4e79a7",
                            "font-size": font_size_place,
                            "text-wrap": "wrap",
                        },
                    },
                    {
                        "selector": ".transition",
                        "style": {
                            "shape": "rectangle",
                            "width": width_trans,
                            "height": 40,
                            "label": "data(label)",
                            "text-valign": "center",
                            "text-halign": "center",
                            "background-color": "#fff7e6",
                            "border-width": 2,
                            "border-color": "#f28e2b",
                            "font-size": font_size_trans,
                            "text-wrap": "wrap",
                        },
                    },
                    {
                        "selector": ".substitution",
                        "style": {
                            "shape": "rectangle",
                            "width": width_subtrans,
                            "height": 40,
                            "label": "data(label)",
                            "text-valign": "center",
                            "text-halign": "center",
                            "background-color": "#e8fff2",
                            "border-width": 2,
                            "border-color": "#59a14f",
                            "font-size": font_size_subtrans,
                            "text-wrap": "wrap",
                        },
                    },
                    # === EDGES (directed by default) ===
                    {
                        "selector": "edge",
                        "style": {
                            "curve-style": "bezier",
                            "line-color": "#888",
                            "width": 2,
                            "target-arrow-shape": "triangle",
                            "target-arrow-color": "#888",
                            "arrow-scale": 1.9,
                        },
                    },
                    # Internal arcs (slightly different tone)
                    {
                        "selector": ".arc",
                        "style": {
                            "line-color": "#9aa0a6",
                            "target-arrow-color": "#9aa0a6",
                            "arrow-scale": 1.9,
                        },
                    },
                    # Substitution edges (dashed + directed)
                    {
                        "selector": ".subedge",
                        "style": {
                            "line-style": "dashed",
                            "line-color": "#59a14f",
                            "target-arrow-shape": "triangle",
                            "target-arrow-color": "#59a14f",
                            "arrow-scale": 1.9,
                        },
                    },
                    # --- Transition conformance classes ---
                    {
                        "selector": ".t_modelandlogmove",
                        "style": {
                            "background-color": "#ffe4e4",
                            "border-color": "#750fc9",
                            "border-width": 3,
                            "color": "#a11",
                            "font-weight": "600",
                        },
                    },
                    {
                        "selector": ".t_modelmove",
                        "style": {
                            "background-color": "#ffe4e4",
                            "border-color": "#d64545",
                            "border-width": 3,
                            "color": "#a11",
                            "font-weight": "600",
                        },
                    },
                    {
                        "selector": ".t_logmove",
                        "style": {
                            "background-color": "#f11010",
                            "border-color": "#bd0f0f",
                            "border-width": 3,
                            "color": "#135",
                            "font-weight": "600",
                        },
                    },
                    # --- Module container deviation summaries ---
                    {
                        "selector": ".mod_dev_model",
                        "style": {
                            "background-color": "#1dceb6",
                            "border-color": "#15e00e",
                            "border-width": 3,
                        },
                    },
                    {
                        "selector": ".mod_dev_log",
                        "style": {
                            "background-color": "#f10c18",
                            "border-color": "#d10617",
                            "border-width": 3,
                        },
                    },
                    {
                        "selector": ".mod_dev_both",
                        "style": {
                            "background-color": "#fff2cc",
                            "border-color": "#b37b00",
                            "border-width": 4,
                        },
                    },
                ],
            )
        )

    def run(
        self,
        title="HCPN Visualization",
        height=1200,
        width="100%",
        layout_name="klay",
        orientation="TB",
        port=8051,
    ):
        """
        Launch the Dash app.

        Args:
          layout_name: 'klay' (recommended) or 'dagre'
          orientation: 'TB' (top→bottom) or 'LR' (left→right)
        """
        # Make extra layouts (klay, dagre, etc.) available
        cyto.load_extra_layouts()

        app = Dash(__name__)
        # Build the graph view
        graph_view = self.view(
            height=height,
            width=width,
            layout_name=layout_name,
            orientation=orientation,
        )

        app.layout = html.Div(
            [
                dcc.Store(
                    id="expanded_store", data=[], storage_type="local"
                ),  # remembers expanded modules
                html.H2(title),
                graph_view,
            ]
        )

        # --- Toggle folded/full label for module containers on click (tapNodeData) ---


        # 1) Toggle store
        @app.callback(
            Output("expanded_store", "data"),
            Input("hcpn", "tapNodeData"),
            State("expanded_store", "data"),
            prevent_initial_call=True,
        )
        def toggle_store(tapped, expanded_ids):
            if not tapped:
                return no_update
            # Only module parents toggle
            if not tapped.get("is_module_parent"):
                return no_update

            node_id = tapped.get("id")
            if not node_id:
                return no_update

            expanded = set(expanded_ids or [])
            if node_id in expanded:
                expanded.discard(node_id)
            else:
                expanded.add(node_id)
            return list(expanded)


        # 2) Apply store to elements

        @app.callback(
            Output("hcpn", "elements"),
            Input("expanded_store", "data"),
            State("hcpn", "elements"),
        )
        def apply_expanded(expanded_ids, elements):
            if not elements:
                return no_update

            expanded = set(expanded_ids or [])
            changed = False
            updated = deepcopy(elements)  # safe copy

            for el in updated:
                data = el.get("data") or {}
                el_id = data.get("id")
                if not el_id:
                    continue

                # Use the data flag, not classes
                if data.get("is_module_parent", 0) == 1:
                    new_val = (el_id in expanded)  # boolean
                    if bool(data.get("expanded", False)) != new_val:
                        data["expanded"] = new_val
                        el["data"] = data
                        changed = True

            return updated if changed else no_update


        print(f"Running on http://127.0.0.1:{port}")
        app.run(debug=False, port=port)


def visualise_conformance_result(
    hcpn,
    markings,
    deviations,
    consistency,
    *,
    # Dash/Cytoscape layout options
    layout_name="klay",
    orientation="TB",
    port=8051,
    # HCPNCytoscapeVisualizer options
    super_children_two_rows=True,
    show_tokens=False,
    module_name_is_super=lambda n: n.startswith("I_"),
    # Label font sizes (optional; respected if your class reads them)
    module_label_font_size=80,
    supermodule_label_font_size=80,
    # Aggregate deviation coloring up to super_modules
    aggregate_to_supermodules=True,
    # Run the server immediately (set False if you want to call viz.run yourself)
    parent_show_child_deviations = False,
    run=False,
):
    """
    Build a Cytoscape visualization that shows conformance:
      - For each *non-silent*, *non-synchronous* transition:
          * if in deviations -> label '<< model move >>' and class 't_modelmove'
          * else             -> label '<< log move >>'   and class 't_logmove'
      - Color the module (and optionally super_module) container based on deviations:
          * mod_dev_model | mod_dev_log | mod_dev_both

    Inputs:
      deviations: dict[module_name -> list[devObj]]
          devObj.activity: str (transition name)
          devObj.alignment_result: Optional[str] (used for module label)
      consistency: dict[module_name -> list[str] | list[tuple]]
          Each value can be a list of transition names, or list of pairs where [1] is model transition name.
    """
    # 1) Build base elements with your visualizer (no mutation of hcpn)
    viz = HCPNCytoscapeVisualizer().apply(
        hcpn,
        markings,
        params={
            "show_tokens": show_tokens,
            "module_name_is_super": module_name_is_super,
            "super_children_two_rows": super_children_two_rows,
            "module_label_font_size": module_label_font_size,
            "supermodule_label_font_size": supermodule_label_font_size,
        },
    )

    # 2) Normalize inputs
    deviations = deviations or {}
    consistency = consistency or {}

    # deviations_by_module: dict[str, list[dev]]
    deviations_by_module = {
        m: list(devs) for m, devs in deviations.items() if len(devs) > 0
    }

    # Module alignment result (optional tag for module FULL label)
    module_alignment_result = {}
    for m, devs in deviations_by_module.items():
        if devs:
            ar = getattr(devs[0], "alignment_result", None)
            if ar:
                module_alignment_result[m] = ar

    # 3) Determine deviation type per module (model/log/both)
    module_flags = {}  # m -> dict(model:bool, log:bool)
    for m, cpn in hcpn.modules.items():
        logs = []
        models = []
        for item in deviations_by_module.get(m, []):
            if item.move_type == "log":
                logs.append(item)
            elif item.move_type == "model":
                models.append(item)

        module_flags[m] = {
            "model": len(models) > 0,
            "log": len(logs) > 0,
        }

    # 3.a) Optionally aggregate to super_modules (if any child has deviations)
    supers = {name for name in hcpn.modules.keys() if module_name_is_super(name)}
    if aggregate_to_supermodules and getattr(hcpn, "substitutions", None):
        # build relation: super -> set(child_modules)
        children_by_super = {}
        for (parent_mod, _parent_trans), child_mod in hcpn.substitutions.items():
            if parent_mod in supers:
                children_by_super.setdefault(parent_mod, set()).add(child_mod)

        # propagate flags from children to super (union)
        for s, childs in children_by_super.items():
            model_any = any(module_flags.get(c, {}).get("model", False) for c in childs)
            log_any = any(module_flags.get(c, {}).get("log", False) for c in childs)
            # include super's own transitions (if any)
            base = module_flags.get(s, {"model": False, "log": False})
            module_flags[s] = {
                "model": base["model"] or model_any,
                "log": base["log"] or log_any,
            }

    # 4) Patch Cytoscape elements
    def _extract_sub_annotation(label_text: str) -> str:
        if not label_text:
            return ""
        parts = label_text.split("\n", 1)
        if len(parts) == 2 and parts[1].strip().startswith("[Sub"):
            return "\n" + parts[1]
        return ""

    for el in viz.elements:
        data = el.get("data", {})
        el_id = data.get("id", "")
        classes = el.get("classes", "") or ""

        # 4.a) Update module FULL labels and add deviation classes to containers
        if el_id in hcpn.modules:
            # Update FULL module label with alignment result, if any (leave folded label unchanged)
            if el_id in module_alignment_result:
                ar = module_alignment_result[el_id]
                data["full_label"] = f"{el_id}\n<< {ar} >>"

            # Add deviation class to module container
            flags = module_flags.get(el_id, {})
            model_f, log_f = flags.get("model", False), flags.get("log", False)
            if model_f or log_f:
                if model_f and log_f:
                    el["classes"] = (classes + " mod_dev_both").strip()
                elif model_f:
                    el["classes"] = (classes + " mod_dev_model").strip()
                else:
                    el["classes"] = (classes + " mod_dev_log").strip()

        # 4.b) Update transition labels/classes according to conformance logic
        if "__T__" in el_id:
            try:
                module_name, transition_name = el_id.split("__T__", 1)
            except ValueError:
                module_name, transition_name = None, None

            if not module_name or not transition_name:
                continue

            # skip silent transitions
            if transition_name.lower().endswith("@silent"):
                continue

            child_mod = None
            if hasattr(hcpn, "substitutions") and isinstance(
                getattr(hcpn, "substitutions", None), dict
            ):
                child_mod = hcpn.substitutions.get((module_name, transition_name))

            log_dev = 0
            model_dev = 0

            if parent_show_child_deviations and child_mod:
                # Count from the child module deviations (super transition standing in for child)
                for dev in deviations_by_module.get(child_mod, []):
                    mt = getattr(dev, "move_type", "")
                    if mt == "log":
                        log_dev += 1
                    elif mt == "model":
                        model_dev += 1
            else:
                # Count from the current module but only for this transition
                for dev in deviations_by_module.get(module_name, []):
                    if getattr(dev, "activity", None) == transition_name:
                        mt = getattr(dev, "move_type", "")
                        if mt == "log":
                            log_dev += 1
                        elif mt == "model":
                            model_dev += 1

            existing_label = data.get("label", transition_name)
            sub_annot = _extract_sub_annotation(existing_label)

            if log_dev == 0 and model_dev > 0:
                data["label"] = f"{transition_name}{sub_annot}\n<< model move >>"
                el["classes"] = (classes + " t_modelmove").strip()
            elif model_dev == 0 and log_dev > 0:
                data["label"] = f"{transition_name}{sub_annot}\n<< log move >>"
                el["classes"] = (classes + " t_logmove").strip()
            elif model_dev > 0 and log_dev > 0:
                data["label"] = (
                    f"{transition_name}{sub_annot}\n<< model and log move >>"
                )
                el["classes"] = (classes + " t_modelandlogmove").strip()

    # 5) Optionally run the server, or return the viz
    if run:
        viz.run(layout_name=layout_name, orientation=orientation, port=port)
    return viz
