"""Pipeline templates — built-in pre-made graphs the editor can instantiate."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


def _t_intrusion() -> dict[str, Any]:
    return {
        "id": "tpl_intrusion",
        "name": "Intrusion: person detected → record clip + ntfy",
        "description": "Person detection on any camera, debounced. Records a clip with pre-roll, "
                       "broadcasts via ntfy.sh and the dashboard.",
        "definition": {
            "id": "intrusion", "name": "Intrusion",
            "nodes": [
                {"id": "src", "type": "source.camera", "config": {"camera_id": "REPLACE_ME"}},
                {"id": "yolo", "type": "detector.yolo",
                 "config": {"model": "yolov8n.pt", "device": "${profile.default_device}",
                             "classes": ["person"], "conf": 0.4}},
                {"id": "tracker", "type": "transform.tracker", "config": {"frame_rate": 10}},
                {"id": "match", "type": "condition.metadata_match",
                 "config": {"expression": "d.label == 'person'"}},
                {"id": "cool", "type": "condition.cooldown",
                 "config": {"cooldown_s": 60, "scope": "per_camera"}},
                {"id": "rec", "type": "sink.recorder",
                 "config": {"pre_roll_s": 5, "post_roll_s": 30, "cooldown_s": 60}},
                {"id": "ntfy", "type": "sink.ntfy",
                 "config": {"topic": "camera_dash_intrusion", "priority": 4,
                             "tags": ["bell", "warning"]}},
            ],
            "edges": [
                {"from": "src.frame", "to": "yolo.frame"},
                {"from": "yolo.detections", "to": "tracker.payload"},
                {"from": "tracker.payload", "to": "match.detections"},
                {"from": "match.match", "to": "cool.payload"},
                {"from": "cool.match", "to": "rec.trigger"},
                {"from": "cool.match", "to": "ntfy.payload"},
            ],
        },
    }


def _t_zone_dwell() -> dict[str, Any]:
    return {
        "id": "tpl_zone_dwell",
        "name": "Zone dwell: track + zone + console + ntfy",
        "description": "Tracks people; alerts when one stays in a polygon zone for 10s. "
                       "Draw the polygon on the dashboard tile.",
        "definition": {
            "id": "zone_dwell", "name": "Zone dwell",
            "nodes": [
                {"id": "src", "type": "source.camera", "config": {"camera_id": "REPLACE_ME"}},
                {"id": "yolo", "type": "detector.yolo",
                 "config": {"model": "yolov8n.pt", "device": "${profile.default_device}",
                             "classes": ["person"]}},
                {"id": "tracker", "type": "transform.tracker", "config": {"frame_rate": 10}},
                {"id": "zone", "type": "condition.zone",
                 "config": {"polygon": [[100, 100], [400, 100], [400, 300], [100, 300]],
                             "fire_on": "dwell", "dwell_s": 10, "classes": ["person"]}},
                {"id": "log", "type": "sink.console",
                 "config": {"format": "compact", "prefix": "[zone] "}},
                {"id": "ntfy", "type": "sink.ntfy",
                 "config": {"topic": "camera_dash_dwell", "priority": 4}},
            ],
            "edges": [
                {"from": "src.frame", "to": "yolo.frame"},
                {"from": "yolo.detections", "to": "tracker.payload"},
                {"from": "tracker.payload", "to": "zone.payload"},
                {"from": "zone.match", "to": "log.payload"},
                {"from": "zone.match", "to": "ntfy.payload"},
            ],
        },
    }


def _t_thermal_alarm() -> dict[str, Any]:
    return {
        "id": "tpl_thermal_alarm",
        "name": "Thermal hotspot → describe with Claude + record",
        "description": "When the FLIR sees something hot, Claude describes the visible-spectrum frame "
                       "(needs ANTHROPIC_API_KEY) and a clip is recorded.",
        "definition": {
            "id": "thermal_alarm", "name": "Thermal alarm",
            "nodes": [
                {"id": "flir", "type": "source.camera", "config": {"camera_id": "flir"}},
                {"id": "rgb", "type": "source.camera", "config": {"camera_id": "REPLACE_ME"}},
                {"id": "gate", "type": "condition.temperature_gate",
                 "config": {"min_celsius": 60, "region": "whole"}},
                {"id": "describe", "type": "detector.vision_llm",
                 "config": {"prompt": "What is in this scene that might be hot? Be specific.",
                             "trigger_only": True, "min_interval_s": 60}},
                {"id": "rec", "type": "sink.recorder",
                 "config": {"pre_roll_s": 3, "post_roll_s": 20}},
                {"id": "log", "type": "sink.console", "config": {"prefix": "[thermal] "}},
            ],
            "edges": [
                {"from": "flir.frame", "to": "gate.frame"},
                {"from": "gate.match", "to": "describe.trigger"},
                {"from": "rgb.frame", "to": "describe.frame"},
                {"from": "gate.match", "to": "rec.trigger"},
                {"from": "gate.match", "to": "log.payload"},
                {"from": "describe.event", "to": "log.payload"},
            ],
        },
    }


def _t_pet_door() -> dict[str, Any]:
    return {
        "id": "tpl_pet_door",
        "name": "Pet door: dog/cat in zone → log",
        "definition": {
            "id": "pet_door", "name": "Pet door",
            "nodes": [
                {"id": "src", "type": "source.camera", "config": {"camera_id": "REPLACE_ME"}},
                {"id": "yolo", "type": "detector.yolo",
                 "config": {"classes": ["dog", "cat"], "conf": 0.4,
                             "device": "${profile.default_device}"}},
                {"id": "tracker", "type": "transform.tracker", "config": {"frame_rate": 10}},
                {"id": "match", "type": "condition.metadata_match",
                 "config": {"expression": "d.label in ('dog', 'cat')"}},
                {"id": "cool", "type": "condition.cooldown",
                 "config": {"cooldown_s": 30, "scope": "per_camera_kind"}},
                {"id": "log", "type": "sink.console", "config": {"prefix": "[pet] "}},
            ],
            "edges": [
                {"from": "src.frame", "to": "yolo.frame"},
                {"from": "yolo.detections", "to": "tracker.payload"},
                {"from": "tracker.payload", "to": "match.detections"},
                {"from": "match.match", "to": "cool.payload"},
                {"from": "cool.match", "to": "log.payload"},
            ],
        },
    }


TEMPLATES: list[dict[str, Any]] = [
    _t_intrusion(),
    _t_zone_dwell(),
    _t_thermal_alarm(),
    _t_pet_door(),
]


@router.get("")
async def list_templates() -> list[dict[str, Any]]:
    return TEMPLATES
