"""
services/graph.py
---------------------
Knowledge graph traversal over a single facility's existing data.

Not a separate database -- this builds an in-memory networkx graph
fresh, on demand, from the Factory object you already have (sensors,
permits, people). It exists to answer one question cheaply: "given a
flagged node (e.g. a sensor in alarm), what else is connected to it?"
-- so a rule or an LLM prompt doesn't need custom lookup code for every
possible chain of relationships.

Edges are built from the explicit linking fields added for this
purpose (MonitoredParameter.equipment_tag, PermitRecord.equipment_tag/
contractor_id, Person.manager_id) -- NOT fuzzy text matching. If two
records don't share an equipment_tag (or aren't linked via
contractor_id/manager_id), they are NOT connected in this graph, even
if their free-text location/name fields look similar to a human.

Relationship types built today:
  sensor  <--same_equipment-->  permit    (via equipment_tag, exact match)
  permit  <--assigned_to-->     person    (via contractor_id)
  person  <--reports_to-->      person    (via manager_id)

MOC/PSSR/escalation-logic/shift-pattern edges are not built yet --
their equipment linkage is a different shape and isn't needed for the
sensor+permit+contractor pattern this was built for (see design
discussion for the reasoning).
"""

import networkx as nx


def _sensor_node(sensor_id: str) -> str:
    return f"sensor:{sensor_id}"


def _permit_node(permit_id: str) -> str:
    return f"permit:{permit_id}"


def _person_node(person_id: str) -> str:
    return f"person:{person_id}"


def build_facility_graph(factory) -> nx.Graph:
    """Builds a fresh in-memory graph from one Factory's current data.
    Cheap enough to call on demand -- not cached, since facility data
    can change between calls, and this is only ever meant to run after
    something is already flagged, not on every reading."""
    g = nx.Graph()

    for sensor in factory.monitored_parameters:
        g.add_node(
            _sensor_node(sensor.id),
            node_type="sensor",
            id=sensor.id,
            name=sensor.name,
            equipment_tag=sensor.equipment_tag,
            parameter_category=sensor.parameter_category,
            alarm_threshold=sensor.alarm_threshold,
            fault_since=sensor.fault_since,
        )

    for permit in factory.permit_records:
        g.add_node(
            _permit_node(permit.id),
            node_type="permit",
            id=permit.id,
            permit_number=permit.permit_number,
            equipment_tag=permit.equipment_tag,
            status=permit.status,
            contractor_id=permit.contractor_id,
        )

    for person in factory.people:
        g.add_node(
            _person_node(person.id),
            node_type="person",
            id=person.id,
            name=person.name,
            person_category=person.person_category,
            manager_id=person.manager_id,
            joint_hazop_conducted=person.joint_hazop_conducted,
            safety_induction_completed=person.safety_induction_completed,
        )

    # Edge: sensor <-> permit, sharing a non-empty equipment_tag
    tag_to_sensors = {}
    for sensor in factory.monitored_parameters:
        if sensor.equipment_tag:
            tag_to_sensors.setdefault(sensor.equipment_tag, []).append(sensor.id)

    for permit in factory.permit_records:
        if not permit.equipment_tag:
            continue
        for sensor_id in tag_to_sensors.get(permit.equipment_tag, []):
            g.add_edge(_sensor_node(sensor_id), _permit_node(permit.id), relation="same_equipment")

    # Edge: permit <-> person, via contractor_id
    for permit in factory.permit_records:
        if permit.contractor_id:
            g.add_edge(_permit_node(permit.id), _person_node(permit.contractor_id), relation="assigned_to")

    # Edge: person <-> person, via manager_id
    for person in factory.people:
        if person.manager_id:
            g.add_edge(_person_node(person.id), _person_node(person.manager_id), relation="reports_to")

    return g


def get_related_nodes(graph: nx.Graph, node_id: str, max_hops: int = 2) -> dict:
    """Given a flagged node (e.g. 'sensor:<id>'), returns everything
    connected to it within max_hops, as a plain dict bundle -- this is
    what a rule check or an LLM prompt will consume later. Returns an
    empty bundle (not an error) if node_id isn't in the graph -- e.g. a
    sensor with no equipment_tag has no edges at all, which is a valid
    state, not a bug."""
    if node_id not in graph:
        return {"center": node_id, "nodes": [], "edges": []}

    sub = nx.ego_graph(graph, node_id, radius=max_hops)

    nodes = [{"node_id": n, **graph.nodes[n]} for n in sub.nodes]
    edges = [
        {"from": u, "to": v, "relation": data.get("relation", "")}
        for u, v, data in sub.edges(data=True)
    ]

    return {"center": node_id, "nodes": nodes, "edges": edges}


def sensor_bundle(factory, sensor_id: str, max_hops: int = 2) -> dict:
    """Convenience wrapper -- build the graph and traverse from a
    specific sensor in one call. This is the function later steps
    (Rule Evaluator's bundle-checking, LLM correlation) will actually
    call."""
    graph = build_facility_graph(factory)
    return get_related_nodes(graph, _sensor_node(sensor_id), max_hops=max_hops)