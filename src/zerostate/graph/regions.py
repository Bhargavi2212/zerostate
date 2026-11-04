"""Regions of a plant graph given the closed points: one helper for every plan rule and for build.py's
witness sides.

A path never passes through a closed listed point, nor through a vent, bleed or relief that discharges
to atmosphere or flare (a sink ends a path). A discharge to `header:<id>` is an edge to that header
(added by build.graph), so it does join two parts of the plant.
"""

import networkx as nx

SINK_TARGETS = ("atmosphere", "flare")


def node(g: nx.Graph, n: str):
    return g.nodes[n]["node"]


def is_sink(g: nx.Graph, n: str) -> bool:
    d = node(g, n)
    return d.kind in ("vent", "bleed", "relief") and d.discharges_to in SINK_TARGETS


def sources(g: nx.Graph) -> list[str]:
    return [n for n in g if node(g, n).kind == "source"]


def open_graph(g: nx.Graph, closed) -> nx.Graph:
    """The plant with the closed points and the sinks taken out: what is still connected."""
    return g.subgraph([n for n in g if n not in closed and not is_sink(g, n)])


def energised(g: nx.Graph, closed) -> set[str]:
    """Every node a source still reaches."""
    og = open_graph(g, closed)
    out: set[str] = set()
    for s in sources(g):
        if s in og:
            out |= nx.node_connected_component(og, s)
    return out


def component(g: nx.Graph, closed, n: str) -> set[str]:
    """The region around n. n's own closed state is ignored: it is the thing being worked on."""
    og = open_graph(g, set(closed) - {n})
    return set(nx.node_connected_component(og, n)) if n in og else set()


def source_path(g: nx.Graph, closed, n: str) -> list[str]:
    """Shortest path from any source to n (n's own closed state ignored), or [] when none reaches it."""
    og = open_graph(g, set(closed) - {n})
    if n not in og:
        return []
    paths = [nx.shortest_path(og, s, n) for s in sources(g) if s in og and nx.has_path(og, s, n)]
    return min(paths, key=len) if paths else []  # ties: first source in map order


def sides(g: nx.Graph, closed, work: str | None) -> dict[str, str]:
    """Side of every node: `work` (the region around the work), `upstream` (a source reaches it) or
    `between_blocks` (cut off from both). A closed point or sink takes the side of its neighbours,
    work first."""
    wr = component(g, closed, work) if work in g else set()
    live = energised(g, closed)
    og = open_graph(g, closed)

    def one(n):
        return "work" if n in wr else "upstream" if n in live else "between_blocks"

    out = {n: one(n) for n in og}
    for n in g:
        if n not in og:
            near = {one(x) for x in g[n]}
            out[n] = next((s for s in ("work", "between_blocks", "upstream") if s in near), "between_blocks")
    return out
