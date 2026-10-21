"""The ChemLab-Assets instruments the chemlab suite uses: where each one is in the dataset, how its URDF becomes a
scene, and how its behaviour runtime is driven.

Numbers here are facts about the instruments taken from their URDFs and contracts (positions of handles, joint scales,
documented thresholds), recorded so that tasks can be written and checked without the files; tests/test_chemlab.py
checks them against the downloaded contracts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .runtime import Bridge, RuntimeSpec

DATASET = "MBZUAI/ChemLab-Assets"
REVISION = "4ca4a42dab2ca0a884e449d202e9ad96625d5648"  # Hugging Face dataset revision of release 1.3.0 (2026-10-17)
RELEASE = "1.3.0"
# the release's own licence and citation files, downloaded with the instruments
RELEASE_FILES = ("LICENSE", "LICENSE-ASSETS.md", "CITATION.cff")
PLANT = {"ambient_k": 295.15, "pressure_pa": 101325.0, "noise_seed": 1}  # 22 degC, sea level (the runtimes' example)


@dataclass(frozen=True)
class Point:
    """A point on a moving link, in the link's frame, reported in the world frame by `robo observe`."""

    link: str
    offset: tuple[float, float, float]


@dataclass(frozen=True)
class Part:
    """An operable part: a joint and how `robo observe` reports it."""

    joint: str
    label: str  # e.g. "sash"
    quantity: str  # the reported field, e.g. "opening_m" (prismatic: joint / scale) or "angle_deg"
    scale: float = 1.0  # reported value = joint position / scale (for angles: in degrees after the division)
    points: dict[str, Point] = field(default_factory=dict)
    sizes: dict[str, object] = field(default_factory=dict)  # fixed facts reported with the part (diameters, ...)


@dataclass(frozen=True)
class Instrument:
    slug: str  # the dataset's folder name
    chem_id: str
    name: str
    maker: str
    model: str
    path: str  # dataset folder
    runtime: RuntimeSpec | None = None
    joints: dict[str, dict] = field(default_factory=dict)  # dynamics of moving joints (others: DEFAULT_JOINT)
    colliders: tuple[dict, ...] = ()  # collision geoms the URDF lacks (each with its reason)
    bench_half: tuple[float, float] = (1.0, 0.6)
    cameras: dict[str, tuple] = field(default_factory=dict)  # name -> (position, target, fovy)
    extra_files: tuple[str, ...] = ()  # dataset files outside `path` (shared libraries)

    @property
    def urdf(self) -> str:
        return f"{self.path}/model.urdf"

    @property
    def contract(self) -> str:
        return f"{self.path}/asset.contract.json"

    def files(self) -> tuple[str, ...]:
        """Dataset files beyond the meshes: the URDF, the contract, and what the runtime needs."""
        return (self.urdf, self.contract, *(self.runtime.files if self.runtime else ()), *self.extra_files)


# Joints no task operates keep still unless pushed hard (buttons, feet, rotors).
DEFAULT_JOINT = {"damping": 5.0, "frictionloss": 5.0, "armature": 0.01}
KEY = {"damping": 2.0, "frictionloss": 0.2, "armature": 0.001, "stiffness": 2000.0, "springref": 0.0}


def _cam(pos, target, fovy=45.0) -> tuple:
    return (tuple(pos), tuple(target), fovy)


INSTRUMENTS: dict[str, Instrument] = {}


def _add(i: Instrument) -> None:
    INSTRUMENTS[i.slug] = i


ESCO = "assets/expansion_batch05/t2_vacuum/esco_efa5uduvw"
_add(
    Instrument(
        slug="esco_efa5uduvw",
        chem_id="CHEM-199",
        name="Chemical fume hood",
        maker="Esco Lifesciences",
        model="Frontier Acela EFA-5UDUVW-9",
        path=ESCO,
        runtime=RuntimeSpec(
            module="scripts/asset_runtime/esco_efa5uduvw.py",
            cls="EscoEfa5uduvwRuntime",
            # building exhaust with the damper fully open: the monitor reads SAFE at the 457 mm stop and LOW AIRFLOW
            # with the sash fully open (the release's example, damper half open, reads low already at the stop)
            setup=(
                ("plant.configure", PLANT),
                ("exhaust.configure", {"mode": "building", "suction_pa": 250.0, "duct_k": 3000.0, "damper_open": 1.0}),
            ),
            # the contract's scene binding (matterix.bindings knobs): joint travel along the 5-degree rail =
            # sash.height_m x 1.0038; the sash creeps down to the 457 mm stop when let go above it
            joints={
                "sash_joint": Bridge(
                    "sash.height_m",
                    "sash.set",
                    "height_m",
                    scale=1.0038198375433474,
                    held_arg="hold",
                    tol=2e-4,
                    limits=(0.0, 0.67),
                )
            },
            readouts=("display.text", "monitor.reading_m_s", "indicator.safe", "indicator.unsafe"),
            files=(
                "scripts/asset_runtime/esco_efa5uduvw.py",
                f"{ESCO}/instrument_model.json",
                f"{ESCO}/vapour_templates.json",
            ),
            warmup_s=30.0,
        ),
        # a counterweighted sash on a chain: it stays where it is let go (the runtime moves it above the stop)
        joints={"sash_joint": {"damping": 60.0, "frictionloss": 20.0, "armature": 0.5}},
        colliders=(
            # the sash handle, a 24 mm aluminium bar along the sash's bottom edge (the contract's port sash_handle);
            # the URDF's sash proxy is one box that leaves it out
            {"link": "sash", "type": "capsule", "fromto": (-0.6, -0.0313, 0.0328, 0.6, -0.0313, 0.0328), "size": 0.012},
        ),
        bench_half=(1.0, 0.65),
        cameras={
            "front": _cam((0.0, -2.35, 1.25), (0.0, -0.2, 0.45), 45),
            "side": _cam((-1.25, -1.65, 1.05), (0.0, -0.35, 0.35), 45),
        },
    )
)

XPR = "assets/basic40_batch02/t4_measure/mt_xpr204e"
_add(
    Instrument(
        slug="mt_xpr204e",
        chem_id="CHEM-001",
        name="Analytical balance",
        maker="METTLER TOLEDO",
        model="XPR204E",
        path=XPR,
        runtime=RuntimeSpec(
            module="scripts/basic40_runtime_measure.py",
            cls="XPR204ERuntime",
            kind="xpr204e",
            setup=(("power.set", {"enabled": True}),),
            # the contract's scene binding: each door joint is the door's opening (scene.set_door); any change
            # restarts the stability check
            joints={
                f"door_{side}_joint": Bridge(
                    f"door.{side}.opening_m",
                    "scene.set_door",
                    "opening_m",
                    fixed={"side": side},
                    tol=2e-4,
                    limits=(0.0, 0.109),
                )
                for side in ("left", "right", "top")
            },
            readouts=("balance.status", "balance.net_kg"),
            files=("scripts/basic40_runtime_measure.py", "scripts/balance_runtime.py"),
            warmup_s=10.0,  # the filter warms up for five time constants after power-on
        ),
        joints={
            f"door_{side}_joint": {"damping": 8.0, "frictionloss": 1.5, "armature": 0.05}
            for side in ("left", "right", "top")
        },
        bench_half=(0.6, 0.45),
        cameras={
            "front": _cam((0.0, -0.75, 0.62), (0.0, 0.0, 0.17), 45),
            "side": _cam((0.62, -0.55, 0.55), (0.03, 0.02, 0.17), 45),
        },
    )
)

IKA = "assets/expansion_batch05/t4_measure/ika_plate_rctdigital"
_add(
    Instrument(
        slug="ika_plate_rctdigital",
        chem_id="CHEM-008",
        name="Magnetic hotplate stirrer",
        maker="IKA",
        model="Plate RCT digital",
        path=IKA,
        runtime=RuntimeSpec(
            module="scripts/asset_runtime/ika_plate_rctdigital.py",
            cls="IkaPlateRctdigitalRuntime",
            setup=(("plant.configure", {**PLANT, "mains_v": 230.0}), ("power.set", {"on": True})),
            # the contract's scene bindings: knob angle = heating.set_k x 0.0628 - 17.16 (one turn per 100 K, 0 degC
            # at the stop) and knob angle = stirring.set_rad_s x 0.12
            joints={
                "knob_temperature_joint": Bridge(
                    "heating.set_k",
                    "heating.set_temperature",
                    "temperature_k",
                    scale=0.06283185307179587,
                    offset=-17.16252066656104,
                    tol=2e-3,
                    limits=(273.15, 583.15),  # 0 to 310 degC
                ),
                "knob_speed_joint": Bridge(
                    "stirring.set_rad_s",
                    "stirring.set_speed",
                    "speed_rad_s",
                    scale=0.12000000000000001,
                    tol=2e-3,
                    limits=(0.0, 1500 * math.pi / 30),  # 0 to 1500 rpm
                ),
            },
            readouts=("display.set_temperature", "display.temperature", "display.set_speed"),
            files=(
                "scripts/asset_runtime/ika_plate_rctdigital.py",
                f"{IKA}/instrument_model.json",
                f"{IKA}/liquid_templates.json",
            ),
        ),
        # knobs turn with a little friction and stay where they are left
        joints={
            "knob_temperature_joint": {"damping": 0.02, "frictionloss": 0.02, "armature": 2e-4},
            "knob_speed_joint": {"damping": 0.02, "frictionloss": 0.02, "armature": 2e-4},
            "temp_push_key_joint": KEY,
            "speed_push_key_joint": KEY,
        },
        bench_half=(0.45, 0.4),
        cameras={
            "front": _cam((0.0, -0.48, 0.38), (0.0, -0.06, 0.04), 45),
            "side": _cam((-0.36, -0.36, 0.34), (-0.02, -0.07, 0.04), 45),
        },
    )
)

FD = "assets/expansion_batch05/t4_measure/binder_fd056"
_add(
    Instrument(
        slug="binder_fd056",
        chem_id="CHEM-011",
        name="Forced-convection drying oven",
        maker="BINDER",
        model="FD 56",
        path=FD,
        runtime=RuntimeSpec(
            module="scripts/asset_runtime/binder_fd056.py",
            cls="BinderFd056Runtime",
            setup=(
                ("plant.configure", {**PLANT, "mains_v": 230.0}),
                ("power.set", {"on": True}),
                ("temperature.set", {"temperature_k": 378.15}),  # 105 degC
            ),
            # the contract's scene binding: door angle = door.angle_rad; the door switch opens above 0.05 rad and
            # stops the heater and the fan
            joints={
                "door_joint": Bridge(
                    "door.angle_rad", "door.set", "angle_rad", tol=2e-3, limits=(0.0, 1.806415775814131)
                )
            },
            readouts=("display.text", "display.temperature", "indicator.heating", "fan.running"),
            files=("scripts/asset_runtime/binder_fd056.py", f"{FD}/instrument_model.json", f"{FD}/load_templates.json"),
            warmup_s=120.0,
        ),
        joints={"door_joint": {"damping": 3.0, "frictionloss": 0.6, "armature": 0.05}},
        bench_half=(0.8, 0.7),
        cameras={
            "front": _cam((0.25, -1.85, 1.2), (0.12, -0.35, 0.3), 45),
            "side": _cam((1.2, -1.45, 1.05), (0.15, -0.35, 0.3), 45),
        },
    )
)

HX = "assets/expansion_batch04/t4_measure/mt_hx204"
HX_LIBRARY = "assets/reactions/mt_hx204_moisture_library/templates.json"
_add(
    Instrument(
        slug="mt_hx204",
        chem_id="CHEM-002",
        name="Halogen moisture analyzer",
        maker="METTLER TOLEDO",
        model="HX204",
        path=HX,
        runtime=RuntimeSpec(
            module="scripts/asset_runtime/mt_hx204.py",
            cls="MtHx204Runtime",
            setup=(("power.set", {"enabled": True}),),
            # the contract's scene binding: the lid slides 145 mm back and 108.5 mm up; joint travel along that
            # diagonal = lid.position_m x 1.6691
            joints={
                "lid_joint": Bridge(
                    "lid.position_m", "lid.set_position", "position_m", scale=1.6691, tol=5e-4, limits=(0.0, 0.1085)
                )
            },
            files=("scripts/asset_runtime/mt_hx204.py", "scripts/asset_runtime/_annotations.py", HX_LIBRARY),
        ),
        joints={"lid_joint": {"damping": 6.0, "frictionloss": 1.0, "armature": 0.05}},
        bench_half=(0.45, 0.5),
        extra_files=(HX_LIBRARY,),
        cameras={
            "front": _cam((0.0, -0.72, 0.5), (0.0, -0.05, 0.1), 45),
            "side": _cam((-0.55, -0.55, 0.45), (0.0, -0.03, 0.1), 45),
        },
    )
)

KS = "assets/expansion_batch03/t4_measure/ika_ks4000"
_add(
    Instrument(
        slug="ika_ks4000",
        chem_id="CHEM-009",
        name="Incubated orbital shaker",
        maker="IKA",
        model="KS 4000 i control",
        path=KS,
        runtime=RuntimeSpec(
            module="scripts/asset_runtime/ika_ks4000.py",
            cls="IkaKs4000Runtime",
            setup=(("power.set", {"enabled": True}),),
            # the contract's scene binding: hood joint = hood.angle_rad; the platform can be loaded once the hood is
            # open by at least 1.4 rad
            joints={
                "hood_joint": Bridge(
                    "hood.angle_rad", "hood.set_angle", "angle_rad", tol=2e-3, limits=(0.0, math.pi / 2)
                )
            },
            # the module imports helpers from two other runtimes of the release
            files=(
                "scripts/asset_runtime/ika_ks4000.py",
                "scripts/asset_runtime/_annotations.py",
                "scripts/asset_runtime/mt_hx204.py",
                "scripts/asset_runtime/antonpaar_abbematadvanced.py",
            ),
        ),
        # gas springs hold the hood wherever it is let go
        joints={"hood_joint": {"damping": 4.0, "frictionloss": 1.0, "armature": 0.05}},
        bench_half=(0.8, 0.7),
        cameras={
            "front": _cam((0.0, -1.75, 1.25), (0.0, -0.1, 0.45), 45),
            "side": _cam((-1.25, -1.35, 1.15), (0.0, -0.1, 0.45), 45),
        },
    )
)
