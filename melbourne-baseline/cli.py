#!/usr/bin/env python3
"""
matsim-query: A CLI for querying MATSim simulation output.
Parses output_plans.xml(.gz/.zst) and surfaces agent-level travel behaviour.
Supports network diagram via output_network.xml(.gz/.zst).
"""
import json
import gzip
import math
import zstandard as zstd
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET
import time
import cmd
import shlex
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from tqdm import tqdm
from rich.rule import Rule
from rich.table import Table
import pandas as pd
import pydeck as pdk
from tqdm import tqdm


from rich.text import Text
from rich import print as rprint
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import webbrowser, tempfile
import pandas as pd
import holoviews as hv
import datashader as ds
from holoviews.operation.datashader import datashade
from bokeh.embed import file_html
from bokeh.resources import CDN


hv.extension("bokeh")
console = Console()

# ── helpers ──────────────────────────────────────────────────────────────────

def parse_hms(s: str) -> float:
    """HH:MM:SS → seconds (handles values > 24h)."""
    if not s:
        return 0.0
    parts = s.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m"


def fmt_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres/1000:.2f} km"
    return f"{metres:.0f} m"


def open_plans(path: Path):
    """Return a binary stream, transparently decompressing .gz or .zst."""
    suffix = path.suffix.lower()
    if suffix == ".gz":
        return gzip.open(path, "rb")
    if suffix == ".zst":
        fh = open(path, "rb")
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(fh, closefd=True)
    return open(path, "rb")


# ── data model ───────────────────────────────────────────────────────────────

class Leg:
    """A single leg (transport stage) within a trip."""
    __slots__ = ("mode", "dep_time", "trav_time", "distance", "is_deadend")

    def __init__(self, mode, dep_time, trav_time, distance, is_deadend=False):
        self.mode = mode
        self.dep_time = dep_time        # seconds
        self.trav_time = trav_time      # seconds
        self.distance = distance        # metres
        self.is_deadend = is_deadend    # True when route type is "deadend" or distance == 0


class Trip:
    """A journey = one or more legs between two meaningful activities."""
    __slots__ = ("legs", "origin_type", "dest_type")

    def __init__(self, origin_type, dest_type, legs):
        self.legs = legs
        self.origin_type = origin_type
        self.dest_type = dest_type

    @property
    def duration(self) -> float:
        return sum(l.trav_time for l in self.legs)

    @property
    def distance(self) -> float:
        return sum(l.distance for l in self.legs)

    @property
    def main_mode(self) -> str:
        """Dominant mode by distance; fallback to first leg."""
        if not self.legs:
            return "unknown"
        by_dist = defaultdict(float)
        for l in self.legs:
            by_dist[l.mode] += l.distance
        return max(by_dist, key=by_dist.get)


class Agent:
    __slots__ = ("agent_id", "trips")

    def __init__(self, agent_id, trips):
        self.agent_id = agent_id
        self.trips = trips

    @property
    def num_trips(self) -> int:
        return len(self.trips)

    @property
    def total_duration(self) -> float:
        return sum(t.duration for t in self.trips)

    @property
    def total_distance(self) -> float:
        return sum(t.distance for t in self.trips)

    @property
    def modes_used(self) -> list[str]:
        return list({l.mode for t in self.trips for l in t.legs})

    @property
    def mode_distances(self) -> dict[str, float]:
        d: dict[str, float] = defaultdict(float)
        for t in self.trips:
            for l in t.legs:
                d[l.mode] += l.distance
        return dict(d)

    @property
    def mode_durations(self) -> dict[str, float]:
        d: dict[str, float] = defaultdict(float)
        for t in self.trips:
            for l in t.legs:
                d[l.mode] += l.trav_time
        return dict(d)


# ── network data model ────────────────────────────────────────────────────────

class NetworkNode:
    __slots__ = ("node_id", "x", "y")

    def __init__(self, node_id: str, x: float, y: float):
        self.node_id = node_id
        self.x = x
        self.y = y


class NetworkLink:
    __slots__ = ("link_id", "from_id", "to_id", "length", "modes", "capacity", "freespeed")

    def __init__(self, link_id: str, from_id: str, to_id: str,
                 length: float, modes: set[str],
                 capacity: float = 0.0, freespeed: float = 0.0):
        self.link_id   = link_id
        self.from_id   = from_id
        self.to_id     = to_id
        self.length    = length    # metres
        self.modes     = modes     # set of mode strings e.g. {"car","walk"}
        self.capacity  = capacity  # vehicles/hour
        self.freespeed = freespeed # m/s

    @property
    def primary_mode(self) -> str:
        """Single representative mode for colouring."""
        priority = ["car", "pt", "bike", "walk"]
        for m in priority:
            if m in self.modes:
                return m
        return next(iter(self.modes), "unknown")


class NetworkData:
    """Parsed road network: nodes + links."""

    def __init__(self, nodes: dict[str, NetworkNode], links: list[NetworkLink]):
        self.nodes = nodes   # {node_id: NetworkNode}
        self.links = links

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    @property
    def num_links(self) -> int:
        return len(self.links)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y)"""
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return min(xs), min(ys), max(xs), max(ys)


# ── network parser ────────────────────────────────────────────────────────────

def _open_xml_tracked(path: Path, bar: tqdm):
    """Open any xml[.gz|.zst] file for streaming parse, updating bar by compressed bytes."""
    suffix = path.suffix.lower()

    class _RawProgressFile:
        def __init__(self, p, b):
            self._fh  = open(p, "rb")
            self._bar = b
        def read(self, size=-1):
            data = self._fh.read(size)
            self._bar.update(len(data))
            return data
        def readinto(self, b):
            n = self._fh.readinto(b)
            self._bar.update(n)
            return n
        def readable(self):    return True
        def seekable(self):    return False
        def __enter__(self):   return self
        def __exit__(self, *a): self._fh.close()

    raw = _RawProgressFile(path, bar)
    if suffix == ".gz":
        return gzip.open(raw, "rb")
    if suffix == ".zst":
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(raw, closefd=True)
    return raw


def parse_network(network_path: Path) -> NetworkData:
    """Parse output_network.xml[.gz/.zst] → NetworkData."""
    file_size = network_path.stat().st_size

    bar = tqdm(
        total=file_size,
        desc=f"Parsing {network_path.name}",
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        dynamic_ncols=True,
        colour="yellow",
    )

    nodes: dict[str, NetworkNode] = {}
    links: list[NetworkLink] = []

    with _open_xml_tracked(network_path, bar) as fh:
        context = ET.iterparse(fh, events=("start",))
        for event, elem in context:
            tag = elem.tag

            if tag == "node":
                nid = elem.get("id", "")
                try:
                    x = float(elem.get("x", "0"))
                    y = float(elem.get("y", "0"))
                except ValueError:
                    x, y = 0.0, 0.0
                nodes[nid] = NetworkNode(nid, x, y)
                bar.set_postfix(nodes=len(nodes), refresh=False)

            elif tag == "link":
                lid      = elem.get("id", "")
                from_id  = elem.get("from", "")
                to_id    = elem.get("to", "")
                try:
                    length = float(elem.get("length", "0") or "0")
                except ValueError:
                    length = 0.0
                try:
                    capacity = float(elem.get("capacity", "0") or "0")
                except ValueError:
                    capacity = 0.0
                try:
                    freespeed = float(elem.get("freespeed", "0") or "0")
                except ValueError:
                    freespeed = 0.0
                modes_str = elem.get("modes", "")
                modes = {m.strip() for m in modes_str.split(",") if m.strip()}
                links.append(NetworkLink(lid, from_id, to_id, length, modes, capacity, freespeed))

            elem.clear()

    bar.close()
    console.print(f"  [dim]Loaded {len(nodes):,} nodes · {len(links):,} links[/dim]")
    return NetworkData(nodes, links)


# ── parser ────────────────────────────────────────────────────────────────────

class _RawProgressFile:
    """Wraps the *raw compressed* file handle and ticks a tqdm bar by compressed bytes read."""
    def __init__(self, path: Path, bar: tqdm):
        self._fh  = open(path, "rb")
        self._bar = bar

    def read(self, size=-1):
        data = self._fh.read(size)
        self._bar.update(len(data))
        return data

    def readinto(self, b):
        n = self._fh.readinto(b)
        self._bar.update(n)
        return n

    def readable(self):    return True
    def seekable(self):    return False
    def __enter__(self):   return self
    def __exit__(self, *a): self._fh.close()


def _open_plans_tracked(path: Path, bar: tqdm):
    """Open plans file for streaming XML parse, updating bar by *compressed* bytes."""
    suffix = path.suffix.lower()
    raw = _RawProgressFile(path, bar)
    if suffix == ".gz":
        return gzip.open(raw, "rb")
    if suffix == ".zst":
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(raw, closefd=True)
    return raw


def parse_plans(plans_path: Path, agent_filter: Optional[str] = None) -> dict[str, Agent]:
    """Parse output_plans.xml[.gz/.zst] → {agent_id: Agent}."""
    agents: dict[str, Agent] = {}
    file_size = plans_path.stat().st_size

    bar = tqdm(
        total=file_size,
        desc=f"Parsing {plans_path.name}",
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        dynamic_ncols=True,
        colour="cyan",
    )

    with _open_plans_tracked(plans_path, bar) as fh:
        context = ET.iterparse(fh, events=("start", "end"))
        current_person = None
        in_selected_plan = False
        elements: list = []

        for event, elem in context:
            tag = elem.tag

            if event == "start":
                if tag == "person":
                    current_person = elem.get("id")
                    in_selected_plan = False
                    elements = []

                elif tag == "plan":
                    if elem.get("selected", "no").lower() == "yes":
                        in_selected_plan = True
                        elements = []

                elif in_selected_plan and tag in ("activity", "leg"):
                    attrib = dict(elem.attrib)
                    attrib["_tag"] = tag
                    elements.append(attrib)

                elif in_selected_plan and tag == "route":
                    if elements and elements[-1]["_tag"] == "leg":
                        dist_str = elem.get("distance", "0") or "0"
                        try:
                            elements[-1]["_route_distance"] = float(dist_str)
                        except ValueError:
                            elements[-1]["_route_distance"] = 0.0
                        elements[-1]["_route_type"] = elem.get("type", "")

            elif event == "end":
                if tag == "plan" and in_selected_plan:
                    in_selected_plan = False
                    if agent_filter and current_person != agent_filter:
                        elements = []
                        continue
                    trips = _build_trips(elements)
                    agents[current_person] = Agent(current_person, trips)
                    bar.set_postfix(agents=len(agents), refresh=False)
                    elements = []

                elif tag == "person":
                    current_person = None

                elem.clear()

    bar.close()
    return agents


def _build_trips(elements: list) -> list[Trip]:
    trips: list[Trip] = []
    current_legs: list[Leg] = []
    prev_act_type: Optional[str] = None

    for rec in elements:
        t = rec["_tag"]
        if t == "activity":
            act_type = rec.get("type", "unknown")
            if current_legs:
                trips.append(Trip(prev_act_type or "unknown", act_type, current_legs))
                current_legs = []
            prev_act_type = act_type

        elif t == "leg":
            mode = rec.get("mode", "unknown")
            dep = parse_hms(rec.get("dep_time", "0:0:0"))
            trav = parse_hms(rec.get("trav_time", "0:0:0"))
            dist = rec.get("_route_distance", 0.0)
            rtype = rec.get("_route_type", "")
            is_deadend = (rtype == "deadend") or (dist == 0.0 and trav > 0)
            current_legs.append(Leg(mode, dep, trav, dist, is_deadend))

    return trips


# ── display helpers ───────────────────────────────────────────────────────────

MODE_COLORS = {
    "car":       "bright_red",
    "pt":        "bright_blue",
    "walk":      "bright_green",
    "bike":      "bright_yellow",
    "ride_hail": "magenta",
    "taxi":      "magenta",
}

MODE_PLOTLY = {
    "car":       "#e74c3c",
    "pt":        "#3498db",
    "walk":      "#2ecc71",
    "bike":      "#f1c40f",
    "ride_hail": "#9b59b6",
    "taxi":      "#9b59b6",
}
MODE_PLOTLY_DEADEND = {
    "car":       "#f1948a",
    "pt":        "#85c1e9",
    "walk":      "#a9dfbf",
    "bike":      "#f9e79f",
    "ride_hail": "#d2b4de",
    "taxi":      "#d2b4de",
}

# Network link colours by primary mode
NETWORK_MODE_COLORS = {
    "car":     "#e74c3c",
    "pt":      "#3498db",
    "walk":    "#2ecc71",
    "bike":    "#f1c40f",
    "unknown": "#7f8c8d",
}


def _plotly_color(mode: str, deadend: bool) -> str:
    palette = MODE_PLOTLY_DEADEND if deadend else MODE_PLOTLY
    return palette.get(mode.lower(), "#95a5a6" if not deadend else "#d5d8dc")


def _network_link_color(mode: str) -> str:
    return NETWORK_MODE_COLORS.get(mode.lower(), "#7f8c8d")


def mode_badge(mode: str) -> Text:
    color = MODE_COLORS.get(mode.lower(), "cyan")
    return Text(f" {mode.upper()} ", style=f"bold {color} on grey15")


def mode_bar(mode_distances: dict[str, float], width: int = 30) -> str:
    total = sum(mode_distances.values()) or 1
    bar = ""
    chars = {"car": "█", "pt": "▓", "walk": "░", "bike": "▒"}
    for mode, dist in sorted(mode_distances.items(), key=lambda x: -x[1]):
        count = max(1, round((dist / total) * width))
        ch = chars.get(mode, "▪")
        color = MODE_COLORS.get(mode, "cyan")
        bar += f"[{color}]{ch * count}[/{color}]"
    return bar


def _kpi(label: str, value: str) -> "Panel":
    return Panel(
        f"[bold white]{value}[/]\n[dim]{label}[/dim]",
        border_style="dim",
        expand=True,
        padding=(0, 1),
    )


def _hist(values: list, color: str = "cyan", bins: int = 8, width: int = 30):
    mn, mx = min(values), max(values)
    if mn == mx:
        console.print(f"  All values = {fmt_distance(mn)}")
        return
    step = (mx - mn) / bins
    counts = [0] * bins
    for v in values:
        b = min(int((v - mn) / step), bins - 1)
        counts[b] += 1
    max_count = max(counts) or 1
    for i, c in enumerate(counts):
        lo = mn + i * step
        hi = lo + step
        bar_w = max(1, int(c / max_count * width))
        label = f"{fmt_distance(lo):>9} – {fmt_distance(hi):<9}"
        console.print(f"  {label}  [{color}]{'█' * bar_w}[/] {c}")


# ── lazy simulation data ──────────────────────────────────────────────────────

class SimulationData:
    """Holds parsed data for one output directory. Each attribute is populated
    the first time it is accessed (lazy); subsequent accesses are free."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self._plans_path:   Optional[Path]        = None
        self._network_path: Optional[Path]        = None
        self._agents:       Optional[dict[str, Agent]] = None
        self._network:      Optional[NetworkData] = None

    @property
    def plans_path(self) -> Path:
        if self._plans_path is None:
            self._plans_path = _find_plans(self.output_dir)
        return self._plans_path

    @property
    def network_path(self) -> Optional[Path]:
        if self._network_path is None:
            self._network_path = _find_network(self.output_dir)
        return self._network_path

    @property
    def agents(self) -> dict[str, Agent]:
        if self._agents is None:
            self._agents = parse_plans(self.plans_path)
        return self._agents

    @property
    def network(self) -> Optional[NetworkData]:
        if self._network is None:
            path = self.network_path
            if path is None:
                return None
            self._network = parse_network(path)
        return self._network

    def is_loaded(self) -> bool:
        return self._agents is not None

    def is_network_loaded(self) -> bool:
        return self._network is not None


# ── display commands (pure functions, take agents dict) ───────────────────────

def cmd_summary(agents: dict[str, Agent], top: int = 10) -> None:
    total_agents  = len(agents)
    total_trips   = sum(a.num_trips for a in agents.values())
    total_dist    = sum(a.total_distance for a in agents.values())
    total_dur     = sum(a.total_duration for a in agents.values())

    all_mode_dist: dict[str, float] = defaultdict(float)
    all_mode_dur:  dict[str, float] = defaultdict(float)
    for a in agents.values():
        for m, d in a.mode_distances.items():
            all_mode_dist[m] += d
        for m, d in a.mode_durations.items():
            all_mode_dur[m] += d

    console.print()
    console.print(Panel.fit(
        f"[bold white]MATSim Output Summary[/]",
        border_style="bright_blue"
    ))
    console.print()

    kpis = Table.grid(expand=True, padding=(0, 3))
    for _ in range(4): kpis.add_column(justify="center")
    kpis.add_row(
        _kpi("Agents",     f"{total_agents:,}"),
        _kpi("Trips",      f"{total_trips:,}"),
        _kpi("Total Dist", fmt_distance(total_dist)),
        _kpi("Total Time", fmt_duration(total_dur)),
    )
    console.print(kpis)
    console.print()

    avg = Table.grid(expand=True, padding=(0, 3))
    for _ in range(3): avg.add_column(justify="center")
    avg.add_row(
        _kpi("Avg Trips/Agent", f"{total_trips/max(total_agents,1):.1f}"),
        _kpi("Avg Dist/Agent",  fmt_distance(total_dist/max(total_agents,1))),
        _kpi("Avg Time/Agent",  fmt_duration(total_dur/max(total_agents,1))),
    )
    console.print(avg)
    console.print()

    console.print(Rule("[bold]Mode Split[/bold]", style="dim"))
    mt = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    mt.add_column("Mode",         style="bold")
    mt.add_column("Distance",     justify="right")
    mt.add_column("% of Total",   justify="right")
    mt.add_column("Avg Duration", justify="right")
    mt.add_column("Bar",          no_wrap=True)
    for mode, dist in sorted(all_mode_dist.items(), key=lambda x: -x[1]):
        pct     = 100 * dist / (sum(all_mode_dist.values()) or 1)
        avg_dur = all_mode_dur[mode] / max(total_agents, 1)
        color   = MODE_COLORS.get(mode, "cyan")
        mt.add_row(
            Text(mode, style=f"bold {color}"),
            fmt_distance(dist),
            f"{pct:.1f}%",
            fmt_duration(avg_dur),
            f"[{color}]{'█' * max(1, int(pct / 3))}[/]",
        )
    console.print(mt)

    console.print(Rule(f"[bold]Top {top} Agents by Distance[/bold]", style="dim"))
    ranked = sorted(agents.values(), key=lambda a: a.total_distance, reverse=True)[:top]
    tt = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    tt.add_column("Agent ID")
    tt.add_column("Trips",    justify="right")
    tt.add_column("Distance", justify="right")
    tt.add_column("Duration", justify="right")
    tt.add_column("Main Modes")
    for a in ranked:
        modes_txt = " ".join(str(mode_badge(m)) for m in a.modes_used)
        tt.add_row(str(a.agent_id), str(a.num_trips),
                   fmt_distance(a.total_distance), fmt_duration(a.total_duration), modes_txt)
    console.print(tt)


def cmd_agent(agents: dict[str, Agent], agent_id: str, show_legs: bool = False) -> None:
    if agent_id not in agents:
        console.print(f"[bold red]Agent '{agent_id}' not found.[/]")
        console.print(f"[dim]Available IDs (first 10): {list(agents)[:10]}[/]")
        return

    a = agents[agent_id]
    console.print()
    console.print(Panel.fit(
        f"[bold white]Agent  [bright_cyan]{a.agent_id}[/bright_cyan][/bold white]",
        border_style="bright_cyan"
    ))
    console.print()

    kpis = Table.grid(expand=True, padding=(0, 3))
    for _ in range(4): kpis.add_column(justify="center")
    kpis.add_row(
        _kpi("Trips",          str(a.num_trips)),
        _kpi("Total Distance", fmt_distance(a.total_distance)),
        _kpi("Total Time",     fmt_duration(a.total_duration)),
        _kpi("Modes Used",     ", ".join(a.modes_used) or "—"),
    )
    console.print(kpis)
    console.print()

    if a.mode_distances:
        console.print(Rule("[bold]Mode Split by Distance[/bold]", style="dim"))
        console.print(" " + mode_bar(a.mode_distances, width=50))
        md_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        md_table.add_column("Mode")
        md_table.add_column("Distance",  justify="right")
        md_table.add_column("Duration",  justify="right")
        md_table.add_column("Share",     justify="right")
        total_dist = a.total_distance or 1
        for mode in sorted(a.mode_distances, key=lambda m: -a.mode_distances[m]):
            pct   = 100 * a.mode_distances[mode] / total_dist
            color = MODE_COLORS.get(mode, "cyan")
            md_table.add_row(
                Text(mode, style=f"bold {color}"),
                fmt_distance(a.mode_distances[mode]),
                fmt_duration(a.mode_durations.get(mode, 0)),
                f"{pct:.1f}%",
            )
        console.print(md_table)

    console.print(Rule("[bold]Trips (Journeys)[/bold]", style="dim"))
    for i, trip in enumerate(a.trips, 1):
        mode_color = MODE_COLORS.get(trip.main_mode, "cyan")
        console.print(
            f"  [bold]Trip {i}[/bold]  "
            f"[dim]{trip.origin_type} → {trip.dest_type}[/dim]  "
            f"[{mode_color}]{trip.main_mode}[/]  "
            f"[white]{fmt_distance(trip.distance)}[/]  "
            f"[dim]{fmt_duration(trip.duration)}[/dim]"
        )
        if show_legs and trip.legs:
            leg_tbl = Table(box=box.MINIMAL, padding=(0, 2), show_header=True,
                            header_style="dim", expand=False)
            leg_tbl.add_column("#",        justify="right", style="dim")
            leg_tbl.add_column("Mode",     style="bold")
            leg_tbl.add_column("Departs",  justify="right")
            leg_tbl.add_column("Travel",   justify="right")
            leg_tbl.add_column("Distance", justify="right")
            for j, leg in enumerate(trip.legs, 1):
                color = MODE_COLORS.get(leg.mode, "cyan")
                dep_h = int(leg.dep_time // 3600)
                dep_m = int((leg.dep_time % 3600) // 60)
                leg_tbl.add_row(
                    str(j), Text(leg.mode, style=f"bold {color}"),
                    f"{dep_h:02d}:{dep_m:02d}",
                    fmt_duration(leg.trav_time),
                    fmt_distance(leg.distance),
                )
            console.print(leg_tbl)
    console.print()


def cmd_list(agents: dict[str, Agent], sort: str = "distance",
             limit: int = 20, mode: Optional[str] = None, min_trips: int = 0) -> None:
    filtered = list(agents.values())
    if mode:
        filtered = [a for a in filtered if mode.lower() in a.modes_used]
    if min_trips:
        filtered = [a for a in filtered if a.num_trips >= min_trips]
    key_fn = {
        "id":       lambda a: a.agent_id,
        "trips":    lambda a: a.num_trips,
        "distance": lambda a: a.total_distance,
        "duration": lambda a: a.total_duration,
    }.get(sort, lambda a: a.total_distance)
    filtered.sort(key=key_fn, reverse=(sort != "id"))
    filtered = filtered[:limit]

    t = Table(title=f"Agents — sorted by {sort}, top {limit}",
              box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t.add_column("Agent ID")
    t.add_column("Trips",    justify="right")
    t.add_column("Distance", justify="right")
    t.add_column("Duration", justify="right")
    t.add_column("Modes",    no_wrap=True)
    t.add_column("Mode bar", no_wrap=True)
    for a in filtered:
        modes_str = " ".join(f"[{MODE_COLORS.get(m,'cyan')}]{m}[/]" for m in a.modes_used)
        t.add_row(str(a.agent_id), str(a.num_trips),
                  fmt_distance(a.total_distance), fmt_duration(a.total_duration),
                  modes_str, mode_bar(a.mode_distances, width=20))
    console.print()
    console.print(t)
    console.print(f"[dim]Showing {len(filtered)} of {len(agents)} agents.[/dim]\n")


def cmd_compare(agents: dict[str, Agent], agent_ids: list[str]) -> None:
    missing = [aid for aid in agent_ids if aid not in agents]
    if missing:
        console.print(f"[red]Not found: {missing}[/red]")
        return
    t = Table(title="Agent Comparison", box=box.ROUNDED, show_lines=True)
    t.add_column("Metric", style="bold dim")
    for aid in agent_ids:
        t.add_column(f"Agent {aid}", justify="right")
    sel = [agents[aid] for aid in agent_ids]
    t.add_row("Trips",          *[str(a.num_trips) for a in sel])
    t.add_row("Total Distance", *[fmt_distance(a.total_distance) for a in sel])
    t.add_row("Total Duration", *[fmt_duration(a.total_duration) for a in sel])
    t.add_row("Avg Trip Dist",  *[fmt_distance(a.total_distance/max(a.num_trips,1)) for a in sel])
    t.add_row("Modes Used",     *[", ".join(a.modes_used) for a in sel])
    all_modes = sorted({m for a in sel for m in a.mode_distances})
    for m in all_modes:
        color = MODE_COLORS.get(m, "cyan")
        t.add_row(f"[{color}]{m} dist[/]",
                  *[fmt_distance(a.mode_distances.get(m, 0)) for a in sel])
    console.print()
    console.print(t)
    console.print()


def cmd_mode_stats(agents: dict[str, Agent], mode: str) -> None:
    users = [a for a in agents.values() if mode.lower() in a.modes_used]
    if not users:
        console.print(f"[red]No agents found using mode '{mode}'.[/red]")
        return
    trips_with_mode = [t for a in users for t in a.trips
                       if any(l.mode.lower() == mode.lower() for l in t.legs)]
    legs_with_mode  = [l for a in users for t in a.trips for l in t.legs
                       if l.mode.lower() == mode.lower()]
    total_dist = sum(l.distance  for l in legs_with_mode)
    total_dur  = sum(l.trav_time for l in legs_with_mode)
    n_legs     = len(legs_with_mode)
    color      = MODE_COLORS.get(mode.lower(), "cyan")

    console.print()
    console.print(Panel.fit(f"[bold {color}]{mode.upper()}[/] — Mode Statistics",
                            border_style=color))
    console.print()
    kpis = Table.grid(expand=True, padding=(0, 3))
    for _ in range(4): kpis.add_column(justify="center")
    kpis.add_row(_kpi("Users", f"{len(users):,}"), _kpi("Trips", f"{len(trips_with_mode):,}"),
                 _kpi("Legs", f"{n_legs:,}"),      _kpi("Total Dist", fmt_distance(total_dist)))
    console.print(kpis)
    console.print()
    if n_legs:
        kpis2 = Table.grid(expand=True, padding=(0, 3))
        for _ in range(3): kpis2.add_column(justify="center")
        kpis2.add_row(_kpi("Avg Leg Dist", fmt_distance(total_dist/n_legs)),
                      _kpi("Avg Leg Time", fmt_duration(total_dur/n_legs)),
                      _kpi("Total Time",   fmt_duration(total_dur)))
        console.print(kpis2)
    dists = [l.distance for l in legs_with_mode if l.distance > 0]
    if dists:
        console.print()
        console.print(Rule(f"[bold]Distance Distribution ({mode})[/bold]", style="dim"))
        _hist(dists, color)
    console.print()


LAYER_COLORS = {
    "car_regular": [52, 152, 219],
    "car_deadend": [155, 89, 182],
    "bicycle_regular": [46, 204, 113],
    "bicycle_deadend": [241, 196, 15],
    "pt_regular": [231, 76, 60],
    "pt_deadend": [230, 126, 34],
}

def compute_disconnected_links(network, mode):
    """Return link_ids not in the largest strongly connected component for this mode."""
    # build adjacency
    mode_links = [lk for lk in network.links if mode in lk.modes]
    if not mode_links:
        return set()

    nodes = set()
    out_edges = defaultdict(list)
    in_edges  = defaultdict(list)
    for lk in mode_links:
        nodes.add(lk.from_id)
        nodes.add(lk.to_id)
        out_edges[lk.from_id].append(lk.to_id)
        in_edges[lk.to_id].append(lk.from_id)

    # Kosaraju's algorithm
    visited = set()
    order   = []

    def dfs1(v):
        stack = [(v, iter(out_edges[v]))]
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if child not in visited:
                    visited.add(child)
                    stack.append((child, iter(out_edges[child])))
            except StopIteration:
                order.append(node)
                stack.pop()

    for n in nodes:
        if n not in visited:
            visited.add(n)
            dfs1(n)

    visited2  = set()
    component = {}
    comp_id   = 0

    def dfs2(v, cid):
        stack = [v]
        while stack:
            node = stack.pop()
            component[node] = cid
            for nb in in_edges[node]:
                if nb not in visited2:
                    visited2.add(nb)
                    stack.append(nb)

    for n in reversed(order):
        if n not in visited2:
            visited2.add(n)
            dfs2(n, comp_id)
            comp_id += 1

    # largest SCC
    counts  = defaultdict(int)
    for cid in component.values():
        counts[cid] += 1
    main_cid = max(counts, key=counts.get)

    disconnected_nodes = {n for n, cid in component.items() if cid != main_cid}

    return {
        lk.link_id for lk in mode_links
        if lk.from_id in disconnected_nodes or lk.to_id in disconnected_nodes
    }

def classify_link(lk):
    mode = lk.primary_mode

    # adjust this if your dead-end flag is named differently
    is_deadend = getattr(lk, "deadend", False) or getattr(lk, "is_deadend", False)

    kind = "deadend" if is_deadend else "regular"

    if mode in {"car", "bicycle", "pt"}:
        return f"{mode}_{kind}"

    return None


MODES = ["car", "bicycle", "pt"]

LAYER_COLORS = {
    "car_regular": [52, 152, 219],
    "car_deadend": [0, 80, 180],
    "bicycle_regular": [46, 204, 113],
    "bicycle_deadend": [0, 130, 70],
    "pt_regular": [231, 76, 60],
    "pt_deadend": [150, 0, 0],
}


def compute_deadend_links(network, mode):
    in_count = defaultdict(int)
    out_count = defaultdict(int)

    mode_links = []

    for lk in network.links:
        if mode not in lk.modes:
            continue

        mode_links.append(lk)
        out_count[lk.from_id] += 1
        in_count[lk.to_id] += 1

    dead_nodes = {
        node_id
        for node_id in set(in_count) | set(out_count)
        if in_count[node_id] == 0 or out_count[node_id] == 0
    }

    return {
        lk.link_id
        for lk in mode_links
        if lk.from_id in dead_nodes or lk.to_id in dead_nodes
    }

LAYER_COLORS = {
    "car":                 [52, 152, 219],
    "bicycle":             [46, 204, 113],
    "pt":                  [231, 76, 60],
    "bicycle_disconnected": [255, 50, 50],
    "pt_disconnected":      [255, 150, 0],
}

def cmd_plot_network(network, source_crs="EPSG:28355"):
    """
    Plot MATSim network on a real Melbourne basemap.

    source_crs:
      EPSG:28355 = GDA94 / MGA Zone 55
      EPSG:7855  = GDA2020 / MGA Zone 55
    """

    try:
        from pyproj import Transformer
    except ImportError:
        console.print("[red]Missing dependency: pyproj[/red]")
        console.print("[dim]Install with: pip install pyproj[/dim]")
        return

    transformer = Transformer.from_crs(
        source_crs,
        "EPSG:4326",
        always_xy=True,
    )

    disconnected_by_mode = {
        mode: compute_disconnected_links(network, mode)
        for mode in MODES
    }

    grouped = defaultdict(list)

    for lk in tqdm(network.links, desc="Collecting links"):
        fn = network.nodes.get(lk.from_id)
        tn = network.nodes.get(lk.to_id)
        if fn is None or tn is None:
            continue

        lon1, lat1 = transformer.transform(fn.x, fn.y)
        lon2, lat2 = transformer.transform(tn.x, tn.y)

        for mode in MODES:
            if mode not in lk.modes:
                continue

            key = f"{mode}_disconnected" if lk.link_id in disconnected_by_mode[mode] else mode

            grouped[key].append({
                "path": [[lon1, lat1], [lon2, lat2]]
            })

    layer_order = [
        "car",
        "bicycle",
        "pt",
        "bicycle_disconnected",
        "pt_disconnected",
    ]

    min_x, min_y, max_x, max_y = network.bbox
    min_lon, min_lat = transformer.transform(min_x, min_y)
    max_lon, max_lat = transformer.transform(max_x, max_y)

    cx = (min_lon + max_lon) / 2
    cy = (min_lat + max_lat) / 2

    controls_html = ""
    for layer in layer_order:
        if layer not in grouped:
            continue
        c = LAYER_COLORS[layer]
        controls_html += f"""
        <label>
          <input id="{layer}" type="checkbox" checked onchange="updateLayers()">
          <span style="display:inline-block;width:12px;height:12px;
            background:rgb({c[0]},{c[1]},{c[2]});margin-right:6px;border-radius:2px;"></span>
          {layer}
        </label>"""

    js_data = {k: v for k, v in grouped.items() if k in layer_order}
    js_colors = {k: LAYER_COLORS[k] for k in js_data}
    present_layers = [l for l in layer_order if l in js_data]

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MATSim Melbourne Network</title>

<script src="https://unpkg.com/deck.gl@latest/dist.min.js"></script>
<script src="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.css" rel="stylesheet">

<style>
body {{ margin: 0; }}
#map {{ width: 100vw; height: 100vh; }}
#layer-panel {{
    position: absolute;
    top: 10px;
    left: 10px;
    z-index: 9999;
    background: rgba(20,20,40,0.92);
    color: #eee;
    padding: 12px 16px;
    border-radius: 8px;
    font-family: sans-serif;
    font-size: 13px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.5);
}}
#layer-panel label {{ display: block; margin: 6px 0; cursor: pointer; }}
#layer-panel b {{ display: block; margin-bottom: 8px; color: #adf; }}
</style>
</head>

<body>
<div id="map"></div>

<div id="layer-panel">
<b>Layers</b>
{controls_html}
</div>

<script>
const layerData   = {json.dumps(js_data)};
const layerColors = {json.dumps(js_colors)};
const layerOrder  = {json.dumps(present_layers)};

function makeLayers() {{
  return layerOrder.map(id => new deck.PathLayer({{
    id,
    data: layerData[id],
    getPath: d => d.path,
    getColor: layerColors[id],
    getWidth: 2,
    widthMinPixels: 1,
    pickable: false,
    visible: document.getElementById(id)?.checked ?? true,
  }}));
}}

const deckgl = new deck.DeckGL({{
  container: "map",
  map: maplibregl,
  mapStyle: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  initialViewState: {{
    longitude: {cx},
    latitude: {cy},
    zoom: 10,
    pitch: 0,
    bearing: 0
  }},
  controller: true,
  layers: makeLayers()
}});

function updateLayers() {{
  deckgl.setProps({{ layers: makeLayers() }});
}}
</script>
</body>
</html>"""

    html_file = "network_melbourne_basemap.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

    console.print(f"[dim]Opening basemap plot: {html_file}[/dim]")

def cmd_plot(agents: dict[str, Agent], metric: str = "distance",
             mode_filter: Optional[str] = None) -> None:
    """Open an interactive Plotly chart in the browser.

    Charts produced
    ───────────────
    distance   – stacked bar: total distance per mode (normal + deadend) per agent
    duration   – stacked bar: total travel time per mode (normal + deadend) per agent
    trips      – bar: trip count per agent, coloured by main mode split
    scatter    – distance vs duration scatter, one point per trip, coloured by mode/deadend
    mode_split – population-level pie: mode share by distance (normal vs deadend)

    For the network diagram use cmd_plot_network() directly (via do_plot in the shell).
    """
    valid = ("distance", "duration", "trips", "scatter", "mode_split")
    if metric not in valid:
        console.print(f"[red]Unknown metric '{metric}'. Choose: {', '.join(valid)}[/red]")
        return

    # ── Agent-level plots ─────────────────────────────────────────────────
    sel = list(agents.values())
    if mode_filter:
        sel = [a for a in sel if mode_filter.lower() in a.modes_used]
    if not sel:
        console.print("[red]No agents match the filter.[/red]")
        return

    sel.sort(key=lambda a: a.total_distance, reverse=True)
    agent_ids = [a.agent_id for a in sel]

    combos: set[tuple[str, bool]] = set()
    for a in sel:
        for t in a.trips:
            for l in t.legs:
                combos.add((l.mode, l.is_deadend))
    combos_sorted = sorted(combos, key=lambda c: (c[0], c[1]))

    def legend_name(mode: str, deadend: bool) -> str:
        return f"{mode} (dead-end)" if deadend else mode

    if metric in ("distance", "duration"):
        fig = go.Figure()
        attr = "distance" if metric == "distance" else "trav_time"
        unit = "km" if metric == "distance" else "min"
        divisor = 1000.0 if metric == "distance" else 60.0

        for mode, deadend in combos_sorted:
            values = []
            for a in sel:
                total = sum(
                    getattr(l, attr)
                    for t in a.trips for l in t.legs
                    if l.mode == mode and l.is_deadend == deadend
                )
                values.append(round(total / divisor, 3))
            fig.add_trace(go.Bar(
                name=legend_name(mode, deadend),
                x=agent_ids,
                y=values,
                marker_color=_plotly_color(mode, deadend),
                marker_pattern_shape="/" if deadend else "",
                hovertemplate=(
                    f"<b>%{{x}}</b><br>"
                    f"{legend_name(mode, deadend)}: %{{y:.2f}} {unit}<extra></extra>"
                ),
            ))
        fig.update_layout(
            barmode="stack",
            title=f"Total {'Distance' if metric=='distance' else 'Duration'} per Agent by Mode",
            xaxis_title="Agent ID",
            yaxis_title=f"{'Distance (km)' if metric=='distance' else 'Duration (min)'}",
            legend_title="Mode",
        )

    elif metric == "trips":
        mode_counts: dict[tuple[str, bool], list[int]] = defaultdict(lambda: [0]*len(sel))
        for i, a in enumerate(sel):
            for t in a.trips:
                deadend = all(l.is_deadend for l in t.legs) if t.legs else False
                mode_counts[(t.main_mode, deadend)][i] += 1

        fig = go.Figure()
        for (mode, deadend), counts in sorted(mode_counts.items()):
            fig.add_trace(go.Bar(
                name=legend_name(mode, deadend),
                x=agent_ids,
                y=counts,
                marker_color=_plotly_color(mode, deadend),
                marker_pattern_shape="/" if deadend else "",
                hovertemplate="<b>%{x}</b><br>" + legend_name(mode, deadend) + ": %{y} trips<extra></extra>",
            ))
        fig.update_layout(
            barmode="stack",
            title="Trip Count per Agent by Main Mode",
            xaxis_title="Agent ID",
            yaxis_title="Number of Trips",
            legend_title="Mode",
        )

    elif metric == "scatter":
        fig = go.Figure()
        for mode, deadend in combos_sorted:
            xs, ys, labels = [], [], []
            for a in sel:
                for t in a.trips:
                    for l in t.legs:
                        if l.mode == mode and l.is_deadend == deadend:
                            xs.append(round(l.distance / 1000, 3))
                            ys.append(round(l.trav_time / 60, 2))
                            labels.append(a.agent_id)
            if not xs:
                continue
            fig.add_trace(go.Scatter(
                mode="markers",
                name=legend_name(mode, deadend),
                x=xs,
                y=ys,
                text=labels,
                marker=dict(
                    color=_plotly_color(mode, deadend),
                    size=6,
                    opacity=0.7,
                    symbol="x" if deadend else "circle",
                    line=dict(width=1, color="white") if deadend else dict(width=0),
                ),
                hovertemplate=(
                    "<b>Agent %{text}</b><br>"
                    "Distance: %{x:.2f} km<br>"
                    "Duration: %{y:.1f} min<extra></extra>"
                ),
            ))
        fig.update_layout(
            title="Leg Distance vs Duration (scatter)",
            xaxis_title="Distance (km)",
            yaxis_title="Duration (min)",
            legend_title="Mode",
        )

    elif metric == "mode_split":
        normal_dist:  dict[str, float] = defaultdict(float)
        deadend_dist: dict[str, float] = defaultdict(float)
        for a in sel:
            for t in a.trips:
                for l in t.legs:
                    if l.is_deadend:
                        deadend_dist[l.mode] += l.distance
                    else:
                        normal_dist[l.mode] += l.distance

        all_modes = sorted(set(list(normal_dist) + list(deadend_dist)))
        labels, values, colors, patterns = [], [], [], []
        for m in all_modes:
            if normal_dist[m]:
                labels.append(m)
                values.append(normal_dist[m] / 1000)
                colors.append(_plotly_color(m, False))
                patterns.append("")
            if deadend_dist[m]:
                labels.append(f"{m} (dead-end)")
                values.append(deadend_dist[m] / 1000)
                colors.append(_plotly_color(m, True))
                patterns.append("/")

        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors, pattern=dict(shape=patterns)),
            hovertemplate="%{label}<br>%{value:.1f} km (%{percent})<extra></extra>",
            textinfo="label+percent",
        ))
        fig.update_layout(title="Population Mode Split by Distance (normal vs dead-end)")

    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(family="monospace", size=12),
        legend=dict(bgcolor="#0f3460", bordercolor="#444", borderwidth=1),
        hovermode="closest",
    )

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        fig.write_html(f, include_plotlyjs="cdn", full_html=True)
        path = f.name

    console.print(f"[dim]Opening plot in browser: {path}[/dim]")
    webbrowser.open(f"file://{path}")


# ── REPL ──────────────────────────────────────────────────────────────────────

HELP_TEXT = """
[bold]Commands[/bold]

  [cyan]summary[/cyan] [dim][--top N][/dim]                     Population overview
  [cyan]agent[/cyan] [dim]<id>[/dim] [dim][--legs][/dim]                  Single agent detail
  [cyan]list[/cyan] [dim][--sort id|trips|distance|duration][/dim]  List agents
       [dim][--limit N] [--mode MODE] [--min-trips N][/dim]
  [cyan]compare[/cyan] [dim]<id1> <id2> ...[/dim]               Side-by-side comparison
  [cyan]mode[/cyan] [dim]<mode>[/dim]                           Mode statistics
  [cyan]plot[/cyan] [dim][distance|duration|trips|scatter|mode_split][/dim]  Interactive Plotly chart
       [dim][--mode MODE][/dim]  (dead-ends shown separately in legend)
  [cyan]plot network[/cyan] [dim][--mode MODE][/dim]            Road network diagram
       [dim]Parses output_network.xml automatically.[/dim]
       [dim]Links coloured by primary mode. Toggle layers via legend.[/dim]
       [dim]Scroll to zoom · drag to pan · hover links for details.[/dim]
  [cyan]status[/cyan]                              Show what is loaded
  [cyan]help[/cyan]                               This message
  [cyan]quit[/cyan] / [cyan]exit[/cyan]                          Exit

Data is loaded on first use; subsequent commands reuse it.
"""


class MatsimShell(cmd.Cmd):
    intro  = None
    prompt = "[matsim] "

    def __init__(self, sim: SimulationData):
        super().__init__()
        self._sim = sim

    @property
    def _agents(self) -> dict[str, Agent]:
        return self._sim.agents

    def _args(self, line: str) -> list[str]:
        try:
            return shlex.split(line)
        except ValueError as e:
            console.print(f"[red]Parse error: {e}[/red]")
            return []

    def _flag(self, args: list[str], flag: str, default):
        try:
            i = args.index(flag)
            val = args[i + 1]
            remaining = args[:i] + args[i+2:]
            return val, remaining
        except (ValueError, IndexError):
            return default, args

    def _bool_flag(self, args: list[str], flag: str) -> tuple[bool, list[str]]:
        if flag in args:
            return True, [a for a in args if a != flag]
        return False, args

    def do_summary(self, line: str):
        """summary [--top N]   Population overview."""
        args = self._args(line)
        top_str, _ = self._flag(args, "--top", "10")
        try:
            top = int(top_str)
        except ValueError:
            console.print("[red]--top must be an integer[/red]")
            return
        cmd_summary(self._agents, top=top)

    def do_agent(self, line: str):
        """agent <id> [--legs]   Detail for one agent."""
        args = self._args(line)
        if not args:
            console.print("[red]Usage: agent <id> [--legs][/red]")
            return
        show_legs, args = self._bool_flag(args, "--legs")
        agent_id = args[0]
        cmd_agent(self._agents, agent_id, show_legs=show_legs)

    def do_list(self, line: str):
        """list [--sort distance|trips|duration|id] [--limit N] [--mode MODE] [--min-trips N]"""
        args = self._args(line)
        sort,      args = self._flag(args, "--sort",      "distance")
        limit_str, args = self._flag(args, "--limit",     "20")
        mode,      args = self._flag(args, "--mode",      None)
        mtrips,    args = self._flag(args, "--min-trips", "0")
        try:
            limit    = int(limit_str)
            min_trips = int(mtrips)
        except ValueError:
            console.print("[red]--limit and --min-trips must be integers[/red]")
            return
        cmd_list(self._agents, sort=sort, limit=limit, mode=mode, min_trips=min_trips)

    def do_compare(self, line: str):
        """compare <id1> <id2> [id3 ...]   Side-by-side agent comparison."""
        args = self._args(line)
        if len(args) < 2:
            console.print("[red]Usage: compare <id1> <id2> [id3 ...][/red]")
            return
        cmd_compare(self._agents, args)

    def do_mode(self, line: str):
        """mode <name>   Statistics for one transport mode."""
        args = self._args(line)
        if not args:
            console.print("[red]Usage: mode <name>  e.g. mode car[/red]")
            return
        cmd_mode_stats(self._agents, args[0])

    def do_plot(self, line: str):
        """plot [distance|duration|trips|scatter|mode_split|network] [--mode MODE]
  Open an interactive Plotly chart in the browser.

  Metrics:
    distance   – stacked distance per agent by mode
    duration   – stacked duration per agent by mode
    trips      – trip count per agent by mode
    scatter    – leg distance vs duration
    mode_split – population pie chart
    network    – road network diagram (reads output_network.xml)

  --mode MODE  filter to agents/links using that mode
  Dead-end legs shown separately with hatched bars / x markers."""
        args = self._args(line)
        metric = "distance"
        if args and not args[0].startswith("--"):
            metric, args = args[0], args[1:]
        mode_filter, args = self._flag(args, "--mode", None)

        # Network plot does not need plans data at all — bypass self._agents
        # so the plans file is never parsed just to render the network.
        if metric == "network":
            net = self._sim.network
            if net is None:
                console.print(
                    "[red]output_network.xml[.gz|.zst] not found in the output directory.[/red]"
                )
                return
            cmd_plot_network(net)
            return

        cmd_plot(self._agents, metric=metric, mode_filter=mode_filter)

    def do_status(self, _line: str):
        """status   Show what is currently loaded."""
        console.print()
        console.print(f"  [dim]Directory:[/dim]   {self._sim.output_dir}")
        console.print(f"  [dim]Plans file:[/dim]  {self._sim.plans_path}")
        net_path = self._sim.network_path
        console.print(f"  [dim]Network file:[/dim] {net_path if net_path else '[italic]not found[/italic]'}")
        if self._sim.is_loaded():
            console.print(f"  [dim]Agents:[/dim]     {len(self._sim._agents):,} (loaded)")
        else:
            console.print("  [dim]Agents:[/dim]     [italic]not yet loaded[/italic]")
        if self._sim.is_network_loaded():
            net = self._sim._network
            console.print(f"  [dim]Network:[/dim]    {net.num_nodes:,} nodes · {net.num_links:,} links (loaded)")
        else:
            console.print("  [dim]Network:[/dim]    [italic]not yet loaded[/italic]")
        console.print()

    def do_help(self, _line: str):
        """help   Show all commands."""
        console.print(HELP_TEXT)

    def do_quit(self, _line: str):
        """quit   Exit."""
        console.print("[dim]Bye.[/dim]")
        return True

    def do_exit(self, line: str):
        """exit   Exit."""
        return self.do_quit(line)

    def do_EOF(self, _line: str):
        console.print()
        return True

    def default(self, line: str):
        console.print(
            f"[red]Unknown command:[/red] {line.split()[0] if line.strip() else ''}"
            "  — type [cyan]help[/cyan] for available commands"
        )

    def emptyline(self):
        pass

    def cmdloop_with_interrupt(self):
        while True:
            try:
                self.cmdloop(intro="")
                break
            except KeyboardInterrupt:
                console.print("\n[dim](Ctrl-C — type quit or exit to leave)[/dim]")


# ── entry point ───────────────────────────────────────────────────────────────

def _find_plans(output_dir: str) -> Path:
    d = Path(output_dir)
    candidates = [
        d / "output_plans.xml.zst",
        d / "output_plans.xml.gz",
        d / "output_plans.xml",
        d / "output" / "output_plans.xml.zst",
        d / "output" / "output_plans.xml.gz",
        d / "output" / "output_plans.xml",
    ]
    for p in candidates:
        if p.exists():
            return p
    console.print(f"[red]Could not find output_plans.xml[.zst|.gz] in {output_dir}[/red]")
    raise SystemExit(1)


def _find_network(output_dir: str) -> Optional[Path]:
    """Locate output_network.xml[.gz|.zst] under output_dir, or return None."""
    d = Path(output_dir)
    candidates = [
        Path("scenario/v1/network/network.xml"),
        d / "output_network.xml.zst",
        d / "output_network.xml.gz",
        d / "output_network.xml",
        d / "output" / "output_network.xml.zst",
        d / "output" / "output_network.xml.gz",
        d / "output" / "output_network.xml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="matsim-query",
        description="Interactive MATSim output explorer",
    )
    parser.add_argument("output_dir", help="Path to MATSim output directory")
    parser.add_argument("--preload", action="store_true",
                        help="Parse plans immediately on startup rather than on first command")
    parser.add_argument("--preload-network", action="store_true",
                        help="Parse network immediately on startup")
    args = parser.parse_args()

    sim = SimulationData(args.output_dir)

    net_status = ""
    net_path = sim.network_path
    if net_path:
        net_status = f"\n[dim]Network: {net_path}[/dim]"
    else:
        net_status = "\n[dim yellow]output_network.xml not found — 'plot network' unavailable[/dim yellow]"

    console.print()
    console.print(Panel.fit(
        f"[bold white]matsim-query[/bold white]  [dim]v1.1[/dim]\n"
        f"[dim]{sim.plans_path}[/dim]"
        f"{net_status}\n"
        f"[dim]Type [/dim][cyan]help[/cyan][dim] for commands · [/dim][cyan]quit[/cyan][dim] to exit[/dim]",
        border_style="bright_blue",
    ))
    console.print()

    if args.preload:
        _ = sim.agents
    if args.preload_network and net_path:
        _ = sim.network

    shell = MatsimShell(sim)
    shell.cmdloop_with_interrupt()


if __name__ == "__main__":
    main()