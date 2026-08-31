"""Metric definitions: loaded from YAML, validated against the schema, and the only source of truth.

Frozen contract 03: one place defines each metric, and the front-end never hand-writes business
logic in SQL or TypeScript. This module is that place. A metric that fails the schema fails the
build — :func:`load_registry` raises, the service does not start, and CI goes red.
"""

from __future__ import annotations

import json
import logging
import os

import jsonschema
import yaml

_logger = logging.getLogger(__name__)


class MetricDefinitionError(RuntimeError):
    """A metric file is invalid. Fatal at startup: a half-valid registry is not servable."""


class Metric:
    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.name = raw["name"]
        self.label = raw["label"]
        self.description = raw.get("description", "")
        self.grain = list(raw["grain"])
        self.dimensions = list(raw["dimensions"])
        self.filters = dict(raw["filters"])
        self.type = raw["type"]
        self.unit = raw.get("unit")
        self.aggregation = raw["aggregation"]
        self.source_model = raw["source_model"]
        self.measure = raw["measure"]
        self.refresh_sla_seconds = int(raw["refresh_sla_seconds"])
        self.pdp_class = raw["pdp_class"]

    def __repr__(self) -> str:
        return "<Metric %s -> %s>" % (self.name, self.source_model)


class Registry:
    def __init__(self, metrics: dict) -> None:
        self._metrics = metrics

    def __contains__(self, name) -> bool:
        return name in self._metrics

    def __len__(self) -> int:
        return len(self._metrics)

    def get(self, name):
        return self._metrics.get(name)

    def names(self) -> list:
        return sorted(self._metrics)

    def all(self) -> list:
        return [self._metrics[n] for n in self.names()]


def load_registry(directory: str) -> Registry:
    schema_path = os.path.join(directory, "metric.schema.json")
    with open(schema_path, encoding="utf-8") as handle:
        schema = json.load(handle)

    metrics = {}
    problems = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(directory, filename)
        with open(path, encoding="utf-8") as handle:
            documents = yaml.safe_load(handle) or []
        if not isinstance(documents, list):
            problems.append("%s: top level must be a list of metrics" % filename)
            continue
        for entry in documents:
            try:
                jsonschema.validate(entry, schema)
            except jsonschema.ValidationError as exc:
                problems.append(
                    "%s: metric %r failed the schema at %s: %s"
                    % (filename, entry.get("name", "<unnamed>"),
                       "/".join(str(p) for p in exc.absolute_path) or "<root>", exc.message)
                )
                continue

            metric = Metric(entry)

            # Contract 03 rule 1: tenant_id is always in grain. A metric that can be computed
            # across tenants does not exist -- so this is checked, not assumed. The schema cannot
            # express it, which is exactly why it is here.
            if "tenant_id" not in metric.grain:
                problems.append(
                    "%s: metric %r omits tenant_id from grain. Contract 03 rule 1: a metric that "
                    "can be computed across tenants does not exist." % (filename, metric.name)
                )

            # Contract 03 rule: a metric may never expose a `secret` class.
            if metric.pdp_class == "secret":
                problems.append(
                    "%s: metric %r is pdp_class=secret. A secret-class column is dropped at "
                    "extraction and does not exist in the warehouse, so a metric over one cannot "
                    "be computed at all." % (filename, metric.name)
                )

            # Every grain key must also be a legal group-by, or the metric cannot be queried at
            # the grain it declares.
            ungroupable = [g for g in metric.grain if g not in metric.dimensions]
            if ungroupable:
                problems.append(
                    "%s: metric %r declares grain %s that are not in dimensions, so it cannot be "
                    "requested at its own grain." % (filename, metric.name, ungroupable)
                )

            if metric.name in metrics:
                problems.append("%s: duplicate metric name %r" % (filename, metric.name))
            metrics[metric.name] = metric

    if problems:
        raise MetricDefinitionError(
            "%d metric definition problem(s):\n  - %s" % (len(problems), "\n  - ".join(problems))
        )
    _logger.info("loaded %d metric definitions from %s", len(metrics), directory)
    return Registry(metrics)
